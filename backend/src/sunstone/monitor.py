"""Live state served to every viewer from one shared cache.

On the 3,000-device sample, building a snapshot takes about 0.2 s,
serializing it 20 ms, compressing it 90 ms, and finding its problems about
0.3 s, every time it is asked for. With every viewer polling every 10
seconds, that soon uses up a core. So the present is rounded down to the
polling interval, and each moment's snapshot is built, serialized,
compressed, and analyzed once, then kept for everyone who asks for it.
The day's events are worked out in the background at startup, so the
first viewer does not wait for them, and while anyone is watching, each new
moment is built as it begins, so no viewer waits for that either.
"""

import gzip
import threading
from collections import OrderedDict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sunstone.impact import Failures, Network
from sunstone.live import StateSource
from sunstone.problems import LiveView, ProblemList, current_failures, find_problems

POLL = timedelta(seconds=10)
# Moments kept: the present and recent past for live viewers, plus a few
# replayed ones. Each takes about 2 MB on the large sample.
KEPT_MOMENTS = 16
# Build moments ahead only while someone asked for the present this recently.
WATCHED = timedelta(minutes=1)


@dataclass(frozen=True)
class Moment:
    """One snapshot, ready to serve, and what was found in it."""

    body: bytes
    """The snapshot as JSON."""
    gzipped: bytes
    """The same, compressed."""
    problems: ProblemList
    failures: Failures
    """Devices and links down in it, for "what if" questions asked about it."""


class Monitor:
    """Snapshots and their problems, worked out once per moment."""

    def __init__(self, network: Network, source: StateSource) -> None:
        """Wrap a state source.

        Args:
            network: The topology, indexed.
            source: Where live state comes from.

        Raises:
            None
        """
        self.network = network
        self.source = source
        self._moments: OrderedDict[datetime, Moment] = OrderedDict()
        self._lock = threading.Lock()
        self._asked: datetime | None = None

    def now(self) -> datetime:
        """The present, rounded down to the polling interval, as a viewer asks for it.

        Returns:
            The moment live viewers are shown.

        Raises:
            None
        """
        self._asked = datetime.now(UTC)
        return _rounded(self._asked)

    def moment(self, at: datetime) -> Moment:
        """The snapshot as of a moment, built on first request.

        Args:
            at: The moment, timezone-aware, within the source's history.

        Returns:
            The snapshot, serialized and compressed, with its problems.

        Raises:
            None
        """
        # One build at a time: viewers asking for the same new moment wait
        # for it instead of each building their own.
        with self._lock:
            found = self._moments.get(at)
            if found is not None:
                self._moments.move_to_end(at)
                return found
            state = self.source.snapshot(at)
            body = state.model_dump_json().encode()
            view = LiveView(state)
            found = Moment(
                body=body,
                gzipped=gzip.compress(body, compresslevel=6),
                problems=ProblemList(at=at, problems=find_problems(self.network, view)),
                failures=current_failures(self.network, view),
            )
            self._moments[at] = found
            while len(self._moments) > KEPT_MOMENTS:
                self._moments.popitem(last=False)
            return found

    def forget(self) -> None:
        """Drop every kept moment, for when what they were built from changes.

        Raises:
            None
        """
        with self._lock:
            self._moments.clear()

    def keep_ahead(self, stop: threading.Event) -> None:
        """Build each new moment as it begins, while anyone is watching.

        Meant for a background thread; returns when ``stop`` is set.

        Args:
            stop: Set to end the loop.

        Raises:
            None
        """
        while not stop.is_set():
            now = datetime.now(UTC)
            following = _rounded(now) + POLL
            if stop.wait((following - now).total_seconds()):
                return
            if self._asked and datetime.now(UTC) - self._asked < WATCHED:
                self.moment(following)

    def warm(self) -> None:
        """Work out the day's events and the present moment ahead of time.

        Meant for a background thread at startup; it only saves time, and if
        it fails, the thread reports the error and the requests themselves
        do the work.

        Raises:
            None
        """
        now = datetime.now(UTC)
        self.source.events(now - self.source.retention, now)
        self.moment(self.now())


def _rounded(at: datetime) -> datetime:
    """A moment rounded down to the polling interval."""
    step = POLL.total_seconds()
    return datetime.fromtimestamp(at.timestamp() // step * step, UTC)
