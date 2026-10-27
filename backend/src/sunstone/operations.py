"""Maintenance windows, acknowledged and paged problems, and covered
shifts: the work a NOC knows about.

A maintenance window names devices, sites, and links, and when they will be
worked on. While it is open, problems that it explains are marked planned,
and so are the events it causes; before it opens, "what if" shows what the
work will take down. An acknowledgement says someone is on a problem, with
a note, and a page that a team has been called about it (on paper: nothing
is sent); both last until the problem clears. A cover puts someone on call
in place of a team's primary for a while.

There is no sign-in, so people give their own name. All of these for one
topology live in one JSON file, kept in memory and rewritten whole on each
change, the same way as saved layouts.
"""

import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Annotated, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

from sunstone.impact import Failures, Network
from sunstone.layouts import Center
from sunstone.live import StateEvent
from sunstone.oncall import Cover, CoverIn, Page, PageIn
from sunstone.problems import Ack, AckIn, Note, PersonName, Problem

MAX_WINDOWS = 500
MAX_COVERS = 500
LONGEST = timedelta(days=7)
# Cleared acknowledgements and pages, and ended covers, are kept this long,
# so replaying shows them.
KEPT = timedelta(days=1)

Title = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
]


class OperationsError(Exception):
    """The operations file cannot be read."""


class OperationsFull(Exception):
    """There are already as many maintenance windows, or covers, as allowed."""


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class WindowIn(_Record):
    """A maintenance window as someone plans it."""

    title: Title
    start: AwareDatetime
    end: AwareDatetime
    targets: list[Center] = Field(min_length=1, max_length=50)
    """Devices, sites (all their devices), and links to be worked on."""
    note: Note = ""
    by: PersonName

    @model_validator(mode="after")
    def _sensible(self) -> Self:
        if not self.start < self.end:
            raise ValueError("A window must end after it starts")
        if self.end - self.start > LONGEST:
            raise ValueError(f"A window can be at most {LONGEST.days} days long")
        return self


class Window(WindowIn):
    """A planned maintenance window."""

    id: str
    saved_at: datetime


class _File(_Record):
    windows: list[Window] = []
    acks: list[Ack] = []
    pages: list[Page] = []
    covers: list[Cover] = []


class OperationsStore:
    """Maintenance windows, acknowledgements, pages, and covers for one topology."""

    def __init__(self, path: Path, network: Network) -> None:
        """Use an operations file, created on first change.

        Args:
            path: The JSON file.
            network: The topology, to expand sites into their devices.

        Raises:
            OperationsError: If the file exists but cannot be read.
        """
        self.path = path
        self.network = network
        self._lock = Lock()
        self._data = self._read()
        self.version = 0
        """Goes up whenever the windows change, so anything worked out from
        them knows to work it out again."""

    def windows(self) -> list[Window]:
        """Every maintenance window, earliest first.

        Returns:
            The windows.

        Raises:
            None
        """
        return sorted(self._data.windows, key=lambda w: (w.start, w.end))

    def save_window(self, window: WindowIn, window_id: str | None = None) -> Window:
        """Plan a window, or change one.

        Args:
            window: What to save.
            window_id: The window to change, or None for a new one.

        Returns:
            The saved window.

        Raises:
            OperationsFull: If this is a new window and there are already
                ``MAX_WINDOWS``.
            KeyError: If ``window_id`` names no window.
        """
        with self._lock:
            windows = {w.id: w for w in self._data.windows}
            if window_id is None:
                if len(windows) >= MAX_WINDOWS:
                    raise OperationsFull(f"There are already {MAX_WINDOWS} windows")
                window_id = uuid.uuid4().hex[:12]
            elif window_id not in windows:
                raise KeyError(window_id)
            saved = Window(
                **window.model_dump(), id=window_id, saved_at=datetime.now(UTC)
            )
            windows[window_id] = saved
            self._save(windows=list(windows.values()))
            self.version += 1
            return saved

    def delete_window(self, window_id: str) -> bool:
        """Delete a window.

        Args:
            window_id: Its id.

        Returns:
            True if it existed.

        Raises:
            None
        """
        with self._lock:
            kept = [w for w in self._data.windows if w.id != window_id]
            if len(kept) == len(self._data.windows):
                return False
            self._save(windows=kept)
            self.version += 1
            return True

    def acks(self) -> list[Ack]:
        """Every acknowledgement, standing or recently cleared.

        Returns:
            The acknowledgements.

        Raises:
            None
        """
        return list(self._data.acks)

    def acknowledge(self, ack: AckIn, at: datetime, title: str | None = None) -> Ack:
        """Acknowledge a problem, replacing any standing acknowledgement of it.

        Args:
            ack: The problem, a note, and who.
            at: When.
            title: The problem's title, to keep with it.

        Returns:
            The acknowledgement.

        Raises:
            None
        """
        made = Ack(**ack.model_dump(), at=at, title=title)
        with self._lock:
            kept = [a for a in self._data.acks if not _standing(a, ack.problem)]
            self._save(acks=[*kept, made])
        return made

    def unacknowledge(self, problem: str) -> bool:
        """Withdraw a problem's standing acknowledgement.

        Args:
            problem: The problem's id.

        Returns:
            True if there was one.

        Raises:
            None
        """
        with self._lock:
            kept = [a for a in self._data.acks if not _standing(a, problem)]
            if len(kept) == len(self._data.acks):
                return False
            self._save(acks=kept)
            return True

    def clear(self, present: set[str], at: datetime) -> None:
        """End acknowledgements and pages of problems that have cleared, and
        forget them, and covers, once they ended long ago.

        Args:
            present: Ids of the problems there are now.
            at: Now.

        Raises:
            None
        """
        with self._lock:
            acks = _cleared(self._data.acks, present, at)
            pages = _cleared(self._data.pages, present, at)
            covers = [c for c in self._data.covers if at - c.end < KEPT]
            if (acks, pages, covers) != (
                self._data.acks,
                self._data.pages,
                self._data.covers,
            ):
                self._save(acks=acks, pages=pages, covers=covers)

    def pages(self) -> list[Page]:
        """Every page, standing or recently cleared.

        Returns:
            The pages.

        Raises:
            None
        """
        return list(self._data.pages)

    def page(
        self, page: PageIn, team: str, at: datetime, title: str | None = None
    ) -> Page:
        """Record a page to a problem's team, replacing any standing page of it.

        Args:
            page: The problem, a note, who is paging, and where to look.
            team: The team paged.
            at: When.
            title: The problem's title, to keep with it.

        Returns:
            The page.

        Raises:
            None
        """
        made = Page(
            **page.model_dump(), id=uuid.uuid4().hex[:12], team=team, at=at, title=title
        )
        with self._lock:
            kept = [p for p in self._data.pages if not _standing(p, page.problem)]
            self._save(pages=[*kept, made])
        return made

    def unpage(self, problem: str) -> bool:
        """Withdraw a problem's standing page, as if it had never been sent.

        Args:
            problem: The problem's id.

        Returns:
            True if there was one.

        Raises:
            None
        """
        with self._lock:
            kept = [p for p in self._data.pages if not _standing(p, problem)]
            if len(kept) == len(self._data.pages):
                return False
            self._save(pages=kept)
            return True

    def covers(self) -> list[Cover]:
        """Every cover, earliest first, until a day after it ends.

        Returns:
            The covers.

        Raises:
            None
        """
        return sorted(self._data.covers, key=lambda c: (c.start, c.saved_at))

    def save_cover(self, cover: CoverIn) -> Cover:
        """Put someone on call in place of a team's primary.

        Args:
            cover: Who, for which team, when, and who says so.

        Returns:
            The saved cover.

        Raises:
            OperationsFull: If there are already ``MAX_COVERS``.
        """
        with self._lock:
            if len(self._data.covers) >= MAX_COVERS:
                raise OperationsFull(f"There are already {MAX_COVERS} covers")
            saved = Cover(
                **cover.model_dump(),
                id=uuid.uuid4().hex[:12],
                saved_at=datetime.now(UTC),
            )
            self._save(covers=[*self._data.covers, saved])
            return saved

    def delete_cover(self, cover_id: str) -> bool:
        """Delete a cover.

        Args:
            cover_id: Its id.

        Returns:
            True if it existed.

        Raises:
            None
        """
        with self._lock:
            kept = [c for c in self._data.covers if c.id != cover_id]
            if len(kept) == len(self._data.covers):
                return False
            self._save(covers=kept)
            return True

    def planned_at(self, at: datetime) -> Failures:
        """What open windows take down at a moment.

        Args:
            at: The moment.

        Returns:
            The devices and links being worked on.

        Raises:
            None
        """
        return self.network.failures_of(
            t for w in self._data.windows if w.start <= at < w.end for t in w.targets
        )

    def _read(self) -> _File:
        try:
            raw = self.path.read_bytes()
        except FileNotFoundError:
            return _File()
        except OSError as e:
            raise OperationsError(f"{self.path}: {e}") from e
        try:
            return _File.model_validate_json(raw)
        except ValidationError as e:
            raise OperationsError(f"{self.path}: {e}") from e

    def _save(
        self, **changes: list[Window] | list[Ack] | list[Page] | list[Cover]
    ) -> None:
        """Write the file with some of its lists replaced, by name."""
        data = _File.model_validate({**self._data.model_dump(), **changes})
        temporary = self.path.with_name(f".{self.path.name}.tmp")
        temporary.write_text(
            json.dumps(data.model_dump(mode="json"), indent=1), encoding="utf-8"
        )
        os.replace(temporary, self.path)
        self._data = data


def _standing(record: Ack | Page, problem: str) -> bool:
    return record.problem == problem and record.cleared_at is None


def _cleared[T: (Ack, Page)](
    records: list[T], present: set[str], at: datetime
) -> list[T]:
    """End records of problems no longer present, and drop long-ended ones."""
    return [
        r.model_copy(update={"cleared_at": at})
        if r.cleared_at is None and r.problem not in present
        else r
        for r in records
        if r.cleared_at is None or at - r.cleared_at < KEPT
    ]


def accounted_for(
    problem: Problem, windows: list[Window], network: Network
) -> list[str]:
    """Which open maintenance windows account for a problem.

    A link is accounted for when it, or a device at either end, is being
    worked on; a device when it is. An outage is accounted for when every
    link where reach stops is.

    Args:
        problem: The problem.
        windows: Windows open at the problem's moment.
        network: The topology.

    Returns:
        Ids of the windows working on any part of it, if together they
        account for all of it; else none.

    Raises:
        None
    """
    target = problem.target
    if problem.kind == "outage":
        links = problem.impact.failed.links if problem.impact else []
    elif target.kind == "links":
        links = target.ids
    else:
        links = []
    device = target.id if not links and target.kind == "device" else None
    work = {w.id: network.failures_of(w.targets) for w in windows}

    def covers(done: Failures) -> bool:
        if device is not None:
            return device in done.devices
        return bool(links) and all(_worked_on(network, ln, done) for ln in links)

    def touches(done: Failures) -> bool:
        if device is not None:
            return device in done.devices
        return any(_worked_on(network, ln, done) for ln in links)

    everything = Failures()
    for done in work.values():
        everything = everything | done
    if not covers(everything):
        return []
    return [w for w, done in work.items() if touches(done)]


def event_planned(event: StateEvent, work: Failures, network: Network) -> bool:
    """Whether work being done accounts for an event.

    Args:
        event: The event.
        work: Devices and links being worked on at its time.
        network: The topology.

    Returns:
        True if its device, or its link, is being worked on.

    Raises:
        None
    """
    if event.device is not None:
        return event.device in work.devices
    return event.link is not None and _worked_on(network, event.link, work)


def _worked_on(network: Network, link_id: str, work: Failures) -> bool:
    link = network.links.get(link_id)
    if link_id in work.links:
        return True
    return link is not None and bool({link.a.device, link.b.device} & work.devices)
