"""Incidents: problems someone treats as one, with a timeline and, once
they clear, a postmortem.

Someone opens an incident from a problem, naming it; other problems can join
it. Its timeline is worked out from what Sunstone already records about the
devices and links its problems concern: the changes the source saw from
shortly before it began, acknowledgements, pages and whom they reached,
maintenance, and fixes, with the notes people add and the incident's own
steps. The source keeps a day of history, and cleared acknowledgements and
pages are kept a day more, so what the timeline shows is kept with the
incident, once it clears and whenever it is looked at: a postmortem written
a week later still has it.

An incident clears when the last of its problems does, and opens again if
one comes back before it is closed. Whoever writes the postmortem closes it
with a summary: what happened, and what is to be done about it. Nothing is
sent anywhere.

There is no sign-in, so people give their own name. The incidents for one
topology live in one JSON file, rewritten whole on each change, as saved
layouts are.
"""

import json
import os
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Annotated, Literal, get_args
from zoneinfo import ZoneInfo

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    computed_field,
)

from sunstone.changes import Change
from sunstone.handover import Message, duration
from sunstone.layouts import Center, DeviceCenter, LinksCenter, SiteCenter
from sunstone.live import StateEvent
from sunstone.model import Topology
from sunstone.oncall import Notice, Page
from sunstone.operations import Title, Window
from sunstone.problems import (
    Ack,
    Note,
    PersonName,
    Problem,
    ProblemKind,
    link_name,
    natural,
)

MAX_INCIDENTS = 500
MAX_NOTES = 200
# What the timeline shows from before an incident began, for what led up to it.
LEAD = timedelta(minutes=15)
# Names spelled out in one line of the timeline.
NAMED = 4
# Lines of the timeline in the copied postmortem before "and N more".
LISTED = 40

Status = Literal["open", "cleared", "closed"]
# In the order entries at the same moment come in: what happened, then what
# people did about it.
EntryKind = Literal[
    "event",
    "maintenance",
    "fix",
    "opened",
    "joined",
    "ack",
    "page",
    "notice",
    "note",
    "cleared",
    "closed",
]
# Entries worked out from what Sunstone records elsewhere, so kept with the
# incident before that record is gone.
KEPT_KINDS = {"event", "ack", "page", "notice", "maintenance", "fix"}
_ONSET = {"down", "nodata", "loss", "link-down", "busy", "congested"}
_END = {"up", "reporting", "loss-cleared", "link-up", "load-normal"}
_SAYS = {
    "down": "down",
    "up": "back up",
    "nodata": "stopped reporting",
    "reporting": "reporting again",
    "loss": "dropping packets",
    "loss-cleared": "no longer dropping packets",
    "link-down": "down",
    "link-up": "back up",
    "busy": "busy",
    "congested": "congested",
    "load-normal": "back to normal load",
}


class IncidentError(Exception):
    """The incidents file cannot be read."""


class IncidentRefused(Exception):
    """An incident cannot do that: it is closed, the problem is in another
    incident already, or there are already as many as allowed."""


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


Text = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)
]


class IncidentIn(_Record):
    """Someone opening an incident from a problem."""

    problem: str = Field(min_length=1, max_length=300)
    title: Title
    by: PersonName
    note: Note = ""
    """A first note, if any."""


class JoinIn(_Record):
    """Someone adding a problem to an incident."""

    problem: str = Field(min_length=1, max_length=300)
    by: PersonName


class IncidentNoteIn(_Record):
    """Something someone wants the incident to record."""

    text: Text
    by: PersonName


class IncidentNote(IncidentNoteIn):
    """A note on an incident, as written."""

    id: str
    at: datetime


class CloseIn(_Record):
    """Someone closing an incident with its postmortem summary."""

    summary: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)
    ]
    """What happened, and what is to be done about it."""
    by: PersonName


class Closure(CloseIn):
    """How an incident was closed."""

    at: datetime


class Member(_Record):
    """One problem in an incident, as it was when it joined."""

    problem: str
    """The problem's id."""
    title: str
    kind: ProblemKind
    target: Center
    devices: list[str]
    """The devices it concerned: down, cut off, or the one it was about."""
    links: list[str]
    lost: int
    """Devices it left unreachable."""
    exposed: int
    """Devices it left without redundancy."""
    began: datetime | None
    """When it began, from the source's events; None if before history."""
    joined_at: datetime
    joined_by: str
    cleared_at: datetime | None = None
    """When it cleared; None while it lasts."""


class Incident(_Record):
    """Problems someone treats as one incident."""

    number: int
    title: str
    opened_by: str
    opened_at: datetime
    problems: list[Member]
    notes: list[IncidentNote] = []
    closed: Closure | None = None

    @computed_field
    @property
    def cleared_at(self) -> datetime | None:
        """When the last of its problems cleared, once they all have.

        Returns:
            The time, or None while any lasts.
        """
        ends = [m.cleared_at for m in self.problems]
        return None if None in ends else max(e for e in ends if e is not None)

    @computed_field
    @property
    def status(self) -> Status:
        """Closed, once someone closed it; cleared, once its problems have.

        Returns:
            ``open``, ``cleared``, or ``closed``.
        """
        if self.closed:
            return "closed"
        return "open" if self.cleared_at is None else "cleared"

    @computed_field
    @property
    def began(self) -> datetime | None:
        """When the first of its problems began.

        Returns:
            The time, or None if one began before history does.
        """
        starts = [m.began for m in self.problems]
        return None if None in starts else min(s for s in starts if s is not None)


class IncidentSummary(_Record):
    """An incident, in a line."""

    number: int
    title: str
    status: Status
    began: datetime | None
    opened_at: datetime
    opened_by: str
    cleared_at: datetime | None
    closed_at: datetime | None
    problems: list[str]
    """The ids of its problems."""


class IncidentList(_Record):
    """Every incident, newest first."""

    incidents: list[IncidentSummary]


class Entry(_Record):
    """One line of an incident's timeline."""

    at: datetime
    kind: EntryKind
    text: str
    by: str | None = None
    target: Center | None = None
    """What to select to look at it, at that moment."""
    planned: bool = False
    """Maintenance open at the time accounted for it."""


class IncidentReport(Incident):
    """An incident with its timeline, and the postmortem written from it."""

    timeline: list[Entry]
    """Oldest first."""
    acknowledged: Entry | None
    """The first acknowledgement, if anyone took it on."""
    paged: Entry | None
    """The first page, if anyone paged a team."""
    message: Message
    """The incident written to post in chat or send by email."""


@dataclass(frozen=True)
class Recorded:
    """What Sunstone records elsewhere, for incidents' timelines."""

    events: Sequence[StateEvent]
    """Everything the source saw, oldest first, marked planned where
    maintenance accounts for it."""
    acks: Sequence[Ack]
    pages: Sequence[Page]
    notified: Mapping[str, Sequence[Notice]] = field(default_factory=dict)
    """Whom each page reached, by page id."""
    windows: Sequence[tuple[Window, frozenset[str], frozenset[str]]] = ()
    """Maintenance windows, each with the devices and links it works on."""
    changes: Sequence[Change] = ()
    people: Mapping[str, str] = field(default_factory=dict)
    """Names by person id."""
    teams: Mapping[str, str] = field(default_factory=dict)
    """Names by team id."""


def scope(problem: Problem) -> tuple[list[str], list[str]]:
    """The devices and links a problem concerns.

    Args:
        problem: The problem.

    Returns:
        The devices down or cut off, or the one it is about, and the links
        down, or the ones it is about.

    Raises:
        None
    """
    devices: set[str] = set()
    links: set[str] = set()
    if problem.impact:
        devices |= set(problem.impact.failed.devices) | set(problem.impact.cut_off)
        links |= set(problem.impact.failed.links)
    if isinstance(problem.target, DeviceCenter):
        devices.add(problem.target.id)
    elif isinstance(problem.target, LinksCenter):
        links |= set(problem.target.ids)
    return sorted(devices, key=natural), sorted(links)


def began(
    events: Sequence[StateEvent],
    devices: Sequence[str],
    links: Sequence[str],
    at: datetime,
) -> datetime | None:
    """When a problem began, from the source's events.

    Args:
        events: Everything the source saw, oldest first.
        devices: The devices the problem concerns.
        links: The links it concerns.
        at: A moment it lasts at.

    Returns:
        The earliest time one of them went wrong without coming right before
        ``at``; None if no event says when, so it began before history.

    Raises:
        None
    """
    concerned = set(devices) | set(links)
    onset: dict[str, datetime] = {}
    for e in events:
        name = e.device or e.link
        if e.at > at or name not in concerned:
            continue
        if e.kind in _ONSET:
            onset.setdefault(name, e.at)
        elif e.kind in _END:
            onset.pop(name, None)
    return min(onset.values(), default=None)


def member(
    problem: Problem, by: str, at: datetime, events: Sequence[StateEvent]
) -> Member:
    """A problem as it joins an incident.

    Args:
        problem: The problem, as it is now.
        by: Who opened the incident or added it.
        at: When.
        events: Everything the source saw, oldest first, for when it began.

    Returns:
        The member.

    Raises:
        None
    """
    devices, links = scope(problem)
    return Member(
        problem=problem.id,
        title=problem.title,
        kind=problem.kind,
        target=problem.target,
        devices=devices,
        links=links,
        lost=problem.lost,
        exposed=problem.exposed,
        began=began(events, devices, links, at),
        joined_at=at,
        joined_by=by,
    )


def summary_of(incident: Incident) -> IncidentSummary:
    """An incident, in a line.

    Args:
        incident: The incident.

    Returns:
        Its number, title, where it stands, and when.

    Raises:
        None
    """
    return IncidentSummary(
        number=incident.number,
        title=incident.title,
        status=incident.status,
        began=incident.began,
        opened_at=incident.opened_at,
        opened_by=incident.opened_by,
        cleared_at=incident.cleared_at,
        closed_at=incident.closed.at if incident.closed else None,
        problems=[m.problem for m in incident.problems],
    )


class _Saved(_Record):
    incidents: list[Incident] = []
    kept: dict[str, list[Entry]] = {}
    """Timeline entries kept from elsewhere, by incident number."""


class IncidentStore:
    """Every incident for one topology, newest ``MAX_INCIDENTS``, in one JSON file."""

    def __init__(self, path: Path) -> None:
        """Use an incidents file, created with the first incident.

        Args:
            path: The JSON file.

        Raises:
            IncidentError: If the file exists but cannot be read.
        """
        self.path = path
        self._lock = Lock()
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            raw = None
        except OSError as e:
            raise IncidentError(f"{path}: {e}") from e
        try:
            self._saved = _Saved.model_validate_json(raw) if raw else _Saved()
        except ValidationError as e:
            raise IncidentError(f"{path}: {e}") from e

    def incidents(self) -> list[Incident]:
        """Every incident, newest first.

        Returns:
            The incidents.

        Raises:
            None
        """
        return sorted(self._saved.incidents, key=lambda i: i.number, reverse=True)

    def get(self, number: int) -> Incident | None:
        """An incident by number.

        Args:
            number: Its number.

        Returns:
            The incident, or None if there is none.

        Raises:
            None
        """
        return next((i for i in self._saved.incidents if i.number == number), None)

    def containing(self, problem: str) -> Incident | None:
        """The incident not yet closed that a problem is in, if any.

        Args:
            problem: The problem's id.

        Returns:
            The incident, or None.

        Raises:
            None
        """
        return next(
            (
                i
                for i in self._saved.incidents
                if not i.closed and any(m.problem == problem for m in i.problems)
            ),
            None,
        )

    def kept(self, number: int) -> list[Entry]:
        """The timeline entries kept with an incident.

        Args:
            number: Its number.

        Returns:
            The entries, oldest first.

        Raises:
            None
        """
        return self._saved.kept.get(str(number), [])

    def open(self, incoming: IncidentIn, first: Member, at: datetime) -> Incident:
        """Open an incident from a problem.

        Args:
            incoming: Its title, who opens it, and a first note.
            first: The problem, as it joins.
            at: When.

        Returns:
            The incident, numbered one after the highest so far.

        Raises:
            IncidentRefused: If the problem is in an incident not yet closed.
        """
        with self._lock:
            self._free(first.problem)
            notes = [_note(incoming.note, incoming.by, at)] if incoming.note else []
            made = Incident(
                number=max((i.number for i in self._saved.incidents), default=0) + 1,
                title=incoming.title,
                opened_by=incoming.by,
                opened_at=at,
                problems=[first],
                notes=notes,
            )
            self._save([made, *self.incidents()][:MAX_INCIDENTS], self._saved.kept)
            return made

    def join(self, number: int, joining: Member) -> Incident:
        """Add a problem to an incident.

        Args:
            number: The incident.
            joining: The problem, as it joins.

        Returns:
            The incident.

        Raises:
            KeyError: If there is no such incident.
            IncidentRefused: If it is closed, or the problem is in an
                incident not yet closed.
        """
        with self._lock:
            found = self._open(number)
            self._free(joining.problem)
            return self._replace(found, problems=[*found.problems, joining])

    def add_note(self, number: int, note: IncidentNoteIn, at: datetime) -> IncidentNote:
        """Write a note on an incident.

        Args:
            number: The incident.
            note: What, and who.
            at: When.

        Returns:
            The note.

        Raises:
            KeyError: If there is no such incident.
            IncidentRefused: If it is closed, or has ``MAX_NOTES`` already.
        """
        with self._lock:
            found = self._open(number)
            if len(found.notes) >= MAX_NOTES:
                raise IncidentRefused(
                    f"Incident {number} has {MAX_NOTES} notes already"
                )
            made = _note(note.text, note.by, at)
            self._replace(found, notes=[*found.notes, made])
            return made

    def close(self, number: int, closing: CloseIn, at: datetime) -> Incident:
        """Close an incident with its postmortem summary.

        Args:
            number: The incident.
            closing: The summary, and who writes it.
            at: When.

        Returns:
            The incident, closed.

        Raises:
            KeyError: If there is no such incident.
            IncidentRefused: If it is closed already.
        """
        with self._lock:
            found = self._open(number)
            return self._replace(found, closed=Closure(**closing.model_dump(), at=at))

    def clear(self, present: set[str], at: datetime) -> list[int]:
        """Follow the problems of incidents not yet closed.

        Args:
            present: The ids of the problems there are now.
            at: Now.

        Returns:
            The numbers of the incidents whose last problem just cleared.

        Raises:
            None
        """
        with self._lock:
            changed, cleared = [], []
            for i in self._saved.incidents:
                if i.closed:
                    continue
                problems = [
                    m.model_copy(update={"cleared_at": None})
                    if m.problem in present
                    else m.model_copy(update={"cleared_at": at})
                    if m.cleared_at is None
                    else m
                    for m in i.problems
                ]
                if problems != i.problems:
                    fresh = i.model_copy(update={"problems": problems})
                    changed.append(fresh)
                    if fresh.status == "cleared":
                        cleared.append(i.number)
            if changed:
                numbers = {i.number for i in changed}
                kept = [i for i in self._saved.incidents if i.number not in numbers]
                self._save([*changed, *kept], self._saved.kept)
            return cleared

    def keep(self, number: int, entries: Sequence[Entry]) -> None:
        """Keep the entries of an incident's timeline that come from elsewhere,
        before that record is gone.

        Args:
            number: The incident.
            entries: Its timeline as worked out now.

        Raises:
            None
        """
        with self._lock:
            had = self.kept(number)
            known = {_key(e) for e in had}
            fresh = [
                e for e in entries if e.kind in KEPT_KINDS and _key(e) not in known
            ]
            if fresh:
                both = sorted([*had, *fresh], key=lambda e: e.at)
                self._save(
                    self._saved.incidents, {**self._saved.kept, str(number): both}
                )

    def _open(self, number: int) -> Incident:
        found = self.get(number)
        if found is None:
            raise KeyError(number)
        if found.closed:
            raise IncidentRefused(f"Incident {number} is closed")
        return found

    def _free(self, problem: str) -> None:
        other = self.containing(problem)
        if other:
            raise IncidentRefused(f"That problem is in incident {other.number} already")

    def _replace(self, incident: Incident, **changes: object) -> Incident:
        fresh = incident.model_copy(update=changes)
        kept = [i for i in self._saved.incidents if i.number != incident.number]
        self._save([fresh, *kept], self._saved.kept)
        return fresh

    def _save(self, incidents: list[Incident], kept: dict[str, list[Entry]]) -> None:
        """Write the file, keeping the newest ``MAX_INCIDENTS`` and their entries."""
        newest = sorted(incidents, key=lambda i: i.number, reverse=True)[:MAX_INCIDENTS]
        numbers = {str(i.number) for i in newest}
        saved = _Saved(
            incidents=newest, kept={n: e for n, e in kept.items() if n in numbers}
        )
        temporary = self.path.with_name(f".{self.path.name}.tmp")
        body = saved.model_dump(mode="json", exclude_computed_fields=True)
        temporary.write_text(json.dumps(body), encoding="utf-8")
        os.replace(temporary, self.path)
        self._saved = saved


def _upper(text: str) -> str:
    return text[:1].upper() + text[1:]


def _key(entry: Entry) -> tuple[datetime, str, str]:
    """What tells one entry from another, kept or worked out again."""
    return entry.at, entry.kind, entry.text


def _note(text: str, by: str, at: datetime) -> IncidentNote:
    return IncidentNote(text=text, by=by, id=uuid.uuid4().hex[:12], at=at)


def timeline(
    incident: Incident,
    recorded: Recorded,
    kept: Sequence[Entry],
    topology: Topology,
    now: datetime,
) -> list[Entry]:
    """An incident's timeline.

    Args:
        incident: The incident.
        recorded: What Sunstone records elsewhere.
        kept: Entries kept with the incident from earlier.
        topology: The network, for the names of links and sites.
        now: The time now.

    Returns:
        From ``LEAD`` before it began until it cleared or now, oldest first:
        the changes the source saw to its devices and links, grouped by
        moment and kind; acknowledgements and pages of its problems, and
        whom the pages reached; maintenance on its devices and links
        beginning and ending; fixes to its links; its notes; and when it
        was opened, problems joined it, they cleared, and it was closed.

    Raises:
        None
    """
    start = (incident.began or incident.opened_at) - LEAD
    until = incident.cleared_at or now
    devices = {d for m in incident.problems for d in m.devices}
    links = {ln for m in incident.problems for ln in m.links}
    titles = {m.problem: m.title for m in incident.problems}
    found = _events(recorded.events, devices, links, start, until, topology)
    for a in recorded.acks:
        if a.problem in titles and start <= a.at <= until:
            said = f": {a.note}" if a.note else ""
            found.append(
                Entry(
                    at=a.at,
                    kind="ack",
                    text=f"{a.by} took on {titles[a.problem]}{said}",
                    by=a.by,
                )
            )
    for pg in recorded.pages:
        if pg.problem not in titles or not start <= pg.at <= until:
            continue
        team = recorded.teams.get(pg.team, pg.team)
        said = f": {pg.note}" if pg.note else ""
        found.append(
            Entry(at=pg.at, kind="page", text=f"{pg.by} paged {team}{said}", by=pg.by)
        )
        for n in recorded.notified.get(pg.id, []):
            if n.at <= until:
                who = recorded.people.get(n.person, n.person)
                found.append(
                    Entry(
                        at=n.at, kind="notice", text=f"{who} told, as {team}'s {n.to}"
                    )
                )
    for w, on_devices, on_links in recorded.windows:
        if not (on_devices & devices or on_links & links):
            continue
        for at, verb in ((w.start, "began"), (w.end, "ended")):
            if start <= at <= until:
                text = f"Maintenance {verb}: {w.title}"
                found.append(Entry(at=at, kind="maintenance", text=text, by=w.by))
    for c in recorded.changes:
        if start <= c.at <= until and _touches(c, devices, links):
            found.append(
                Entry(
                    at=c.at,
                    kind="fix",
                    text=f"{c.by} fixed the documentation: {c.title}",
                    by=c.by,
                )
            )
    entries = list({_key(e): e for e in [*kept, *found]}.values())
    entries.append(
        Entry(
            at=incident.opened_at,
            kind="opened",
            text=f"{incident.opened_by} opened the incident: {incident.title}",
            by=incident.opened_by,
        )
    )
    for m in incident.problems[1:]:
        entries.append(
            Entry(
                at=m.joined_at,
                kind="joined",
                text=f"{m.joined_by} added {m.title}",
                by=m.joined_by,
                target=m.target,
            )
        )
    entries += [
        Entry(at=n.at, kind="note", text=n.text, by=n.by) for n in incident.notes
    ]
    for m in incident.problems:
        if m.cleared_at:
            entries.append(
                Entry(
                    at=m.cleared_at,
                    kind="cleared",
                    text=f"{m.title} cleared",
                    target=m.target,
                )
            )
    if incident.closed:
        c = incident.closed
        entries.append(
            Entry(at=c.at, kind="closed", text=f"{c.by} closed the incident", by=c.by)
        )
    order = {k: n for n, k in enumerate(get_args(EntryKind))}
    return sorted(entries, key=lambda e: (e.at, order[e.kind]))


def _events(
    events: Sequence[StateEvent],
    devices: set[str],
    links: set[str],
    start: datetime,
    until: datetime,
    topology: Topology,
) -> list[Entry]:
    """The source's events for some devices and links, one entry per moment and kind."""
    groups: dict[tuple[datetime, str, bool], list[StateEvent]] = {}
    for e in events:
        on_link = e.link is not None
        if not start <= e.at <= until:
            continue
        if (e.device in devices) if not on_link else (e.link in links):
            groups.setdefault((e.at, e.kind, on_link), []).append(e)
    site_of = {d.name: d.site for d in topology.devices}
    by_id = {ln.id: ln for ln in topology.links}
    found = []
    for (at, kind, on_link), group in groups.items():
        planned = all(e.planned for e in group)
        if on_link:
            ids = sorted({e.link or "" for e in group})
            names = [link_name(by_id[i]) if i in by_id else i for i in ids]
            target: Center = LinksCenter(kind="links", ids=ids)
            noun = "link"
        else:
            names = sorted({e.device or "" for e in group}, key=natural)
            sites = {site_of.get(n) for n in names}
            target = (
                DeviceCenter(kind="device", id=names[0])
                if len(names) == 1
                else SiteCenter(kind="site", id=next(iter(sites)) or "")
                if len(sites) == 1
                else DeviceCenter(kind="device", id=names[0])
            )
            noun = "device"
        load = (
            f" ({round(group[0].pct)}%)"
            if kind in ("busy", "congested") and group[0].pct is not None
            else ""
        )
        found.append(
            Entry(
                at=at,
                kind="event",
                text=f"{_list(names, noun)} {_SAYS[kind]}{load}",
                target=target,
                planned=planned,
            )
        )
    return found


def _list(names: list[str], noun: str) -> str:
    if len(names) == 1:
        return names[0]
    shown = ", ".join(names[:NAMED])
    more = f" and {len(names) - NAMED} more" if len(names) > NAMED else ""
    return f"{len(names)} {noun}s ({shown}{more})"


def _touches(change: Change, devices: set[str], links: set[str]) -> bool:
    for link in (change.fix.before, change.fix.after):
        if link and (link.id in links or {link.a.device, link.b.device} & devices):
            return True
    return False


def report(
    incident: Incident,
    entries: list[Entry],
    timezone: str,
    now: datetime,
) -> IncidentReport:
    """An incident with its timeline, and the postmortem written from it.

    Args:
        incident: The incident.
        entries: Its timeline.
        timezone: The zone to give times in.
        now: The time now.

    Returns:
        The report.

    Raises:
        None
    """
    acknowledged = next((e for e in entries if e.kind == "ack"), None)
    paged = next((e for e in entries if e.kind == "page"), None)
    return IncidentReport(
        **incident.model_dump(exclude_computed_fields=True),
        timeline=entries,
        acknowledged=acknowledged,
        paged=paged,
        message=_message(incident, entries, acknowledged, paged, timezone, now),
    )


def _message(
    i: Incident,
    entries: list[Entry],
    acknowledged: Entry | None,
    paged: Entry | None,
    timezone: str,
    now: datetime,
) -> Message:
    zone = ZoneInfo(timezone)

    def day(at: datetime) -> str:
        return at.astimezone(zone).strftime("%H:%M %a %d %b")

    def clock(at: datetime) -> str:
        return at.astimezone(zone).strftime("%H:%M")

    start = i.began or i.opened_at
    if i.cleared_at:
        span = f"lasted {duration(i.cleared_at - start)}" if i.began else ""
    elif i.closed:
        span = "its problems still there"
    else:
        span = f"{duration(now - start)} so far" if i.began else ""
    standing = f"{i.status}, {span}" if span else i.status

    def since(e: Entry | None, what: str) -> str:
        if e is None:
            return f"not {what}"
        return (
            f"{what} by {e.by} {duration(e.at - start)} in"
            if i.began
            else f"{what} by {e.by} at {clock(e.at)}"
        )

    subject = f"Incident {i.number}: {i.title} ({standing})"
    began = f"Began {day(i.began)}" if i.began else "Began before history"
    text = [
        f"Incident {i.number}: {i.title}",
        f"{began}; opened by {i.opened_by} at {day(i.opened_at)} "
        f"({i.opened_at.astimezone(zone).tzname()}).",
        f"{_upper(since(acknowledged, 'acknowledged'))}; {since(paged, 'paged')}.",
    ]
    if i.cleared_at:
        text.append(f"Cleared {day(i.cleared_at)}{'; ' + span if span else ''}.")
    elif i.closed:
        text.append("Closed while its problems were still there.")
    else:
        text.append(f"Still open{', ' + span if span else ''}.")
    text += ["", f"Problems ({len(i.problems)})"]
    for m in i.problems:
        effect = [f"{m.lost} unreachable"] if m.lost else []
        effect += [f"{m.exposed} without redundancy"] if m.exposed else []
        end = f"cleared {clock(m.cleared_at)}" if m.cleared_at else "still there"
        text.append(
            f"- {m.title}{' (' + ', '.join(effect) + ')' if effect else ''}, {end}"
        )
    if i.closed:
        text += ["", f"Summary ({i.closed.by}, {day(i.closed.at)})", i.closed.summary]
    text += ["", f"Timeline ({len(entries)})"]
    lines = []
    for e in entries[:LISTED]:
        by = f" ({e.by})" if e.by and e.kind == "note" else ""
        planned = ", planned" if e.planned else ""
        lines.append(f"- {clock(e.at)} {e.text}{by}{planned}")
    if len(entries) > LISTED:
        lines.append(f"- and {len(entries) - LISTED} more")
    text += lines
    return Message(subject=subject, text="\n".join(text))
