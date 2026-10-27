"""Discovery runs over the last day, each compared once, so the findings of
any moment can be shown again, each saying when it was first and last seen.

Runs come every 15 minutes. The log keeps every run's comparison back as far
as the state source keeps history (a day), works each out once, fills in the
day in the background at startup, newest first so recent moments are ready
soonest, and compares each new run as it comes. A finding's first and last
seen times come from the unbroken stretch of runs around the moment that
show it; a stretch reaching back to the earliest run the log has may have
begun before it. Findings seen earlier in the day but not at the moment are
listed as gone, with when they were seen.

A real discovery source would keep its own history, or the log would be
kept on disk; the simulated one can work out any run again, so nothing is
stored.
"""

import threading
from datetime import UTC, datetime

from sunstone.discovery import (
    Comparison,
    DiscoverySource,
    Finding,
    compare,
    visibility,
)
from sunstone.live import StateSource
from sunstone.model import Topology

# How often to look for a new run.
CHECK_S = 60


class DiscoveryLog:
    """Comparisons of every discovery run over the last day."""

    def __init__(
        self, topology: Topology, source: DiscoverySource, state: StateSource
    ) -> None:
        """Keep a log of a discovery source's runs.

        Args:
            topology: What is documented.
            source: Where neighbor tables come from.
            state: Live state, to tell links that are down from links that
                are missing, and how far back history goes.

        Raises:
            None
        """
        self.topology = topology
        self.source = source
        self.state = state
        self._runs: dict[datetime, Comparison] = {}
        self._lock = threading.Lock()

    def run_of(self, at: datetime) -> datetime:
        """The run in effect at a moment: the latest at or before it.

        Args:
            at: The moment.

        Returns:
            When that run happened.

        Raises:
            None
        """
        step = self.source.interval.total_seconds()
        return datetime.fromtimestamp(at.timestamp() // step * step, UTC)

    def comparison(self, at: datetime) -> Comparison:
        """The comparison in effect at a moment, with when each finding was
        seen, and the findings gone by then.

        Args:
            at: The moment.

        Returns:
            The comparison of the run in effect then.

        Raises:
            None
        """
        run = self.run_of(at)
        return self._annotated(self._compared(run), run)

    def warm(self) -> None:
        """Compare every run of the last day not yet compared, newest first.

        Raises:
            None
        """
        now = datetime.now(UTC)
        run, oldest = self.run_of(now), now - self.state.retention
        while run >= oldest:
            self._compared(run)
            run -= self.source.interval

    def keep_up(self, stop: threading.Event) -> None:
        """Compare each new run as it comes, until stopped.

        Args:
            stop: Set to stop.

        Raises:
            None
        """
        while not stop.wait(CHECK_S):
            self._compared(self.run_of(datetime.now(UTC)))

    def forget(self) -> None:
        """Drop every comparison, as when planned work changes what was down.

        Raises:
            None
        """
        with self._lock:
            self._runs.clear()

    def _compared(self, run: datetime) -> Comparison:
        with self._lock:
            found = self._runs.get(run)
            if found is not None:
                return found
            seen = visibility(self.state, run)
            found = compare(self.topology, self.source.discover(run, seen), seen)
            self._runs[run] = found
            horizon = datetime.now(UTC) - self.state.retention - self.source.interval
            for old in [r for r in self._runs if r < horizon]:
                del self._runs[old]
            return found

    def _annotated(self, raw: Comparison, run: datetime) -> Comparison:
        with self._lock:
            runs = dict(self._runs)
        # Planned work may have wiped the log since this run was compared.
        runs.setdefault(run, raw)
        step = self.source.interval
        seen = {r: {f.id for f in c.findings} for r, c in runs.items()}
        latest = max(runs)
        earliest = run
        while earliest - step in runs:
            earliest -= step

        def stretch(
            finding: str, at: datetime
        ) -> tuple[datetime | None, datetime | None]:
            """First and last runs of the unbroken stretch through ``at`` that
            show a finding: None for a first run as far back as the log goes,
            and for a last run that is the latest."""
            first = last = at
            while first - step in seen and finding in seen[first - step]:
                first -= step
            while last + step in seen and finding in seen[last + step]:
                last += step
            return (None if first == earliest else first), (
                None if last == latest else last
            )

        findings = []
        for f in raw.findings:
            first, last = stretch(f.id, run)
            findings.append(
                f.model_copy(update={"first_seen": first, "last_seen": last})
            )
        gone: dict[str, Finding] = {}
        now = seen.get(run, set())
        back = run - step
        while back in runs:
            for f in runs[back].findings:
                if f.id not in now and f.id not in gone:
                    first, _ = stretch(f.id, back)
                    gone[f.id] = f.model_copy(
                        update={"first_seen": first, "last_seen": back}
                    )
            back -= step
        return raw.model_copy(
            update={
                "findings": findings,
                "gone": list(gone.values()),
                "history_from": earliest,
            }
        )
