"""What the incoming shift needs to know: the last hours, and what is open now.

A handover covers a span ending now, 12 hours unless asked otherwise: the
problems there are now, who is on them and whom they have paged; the
incidents open or dealt with in the span; the outages that began or ended
in it, and how long they lasted; the
pages and acknowledgements made in it; maintenance done in it, open now,
or coming in as long again; fixes and expectations recorded in it;
discovery findings first seen in it; who is on call now; and the notes the
outgoing shift wrote for the next one.

Outages come from the source's events: each device and link is down from
one event to the next. They are grouped as the events list groups them:
devices at one site that went down at the same step are one outage, with
the links at that site that went down then. As with problems, nothing is
guessed about why.

At each shift change the on-call directory gives, the handover of the shift
ending then is saved, with the notes written during it, and kept as it was.
Someone from the incoming shift signs for it once they have read it and
taken over, so the saved handovers say who took over and when; only the
handover of the shift on now can be signed for. Each is also written as a
message to post in chat or send by email; nothing is sent.
"""

import json
import os
from datetime import UTC, datetime, time, timedelta
from functools import cached_property
from pathlib import Path
from threading import Lock
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, ValidationError, computed_field

from sunstone.changes import Change
from sunstone.discovery import Finding
from sunstone.layouts import Center, DeviceCenter, LinksCenter, SiteCenter
from sunstone.live import StateEvent
from sunstone.model import Topology
from sunstone.oncall import HandoverTimes, OnCall, Page, RoutedProblem
from sunstone.operations import ShiftNote, Window
from sunstone.problems import Ack, Note, PersonName, link_name, natural

# Saved handovers kept: a month of 12-hour shifts. Each is about 80 KB on
# the 3,000-device sample.
MAX_SAVED = 60
# Items of each kind listed in a message before "and N more".
LISTED = 10


class HandoverError(Exception):
    """The saved handovers file cannot be read."""


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Outage(_Record):
    """Devices and links that went down together, and came back."""

    title: str
    target: Center
    """What to select to look at it."""
    devices: list[str]
    links: list[str]
    start: datetime | None
    """When they went down; None if before history begins."""
    end: datetime | None
    """When the last of them came back; None if any is still down."""
    planned: bool
    """Open maintenance accounted for every one of them going down."""


class Message(_Record):
    """A handover written to post in chat or send by email."""

    subject: str
    text: str


class IncidentLine(_Record):
    """An incident, as a handover lists it."""

    number: int
    title: str
    status: Literal["open", "cleared", "closed"]
    """Where it stood at the end of the handover's span."""
    began: datetime | None
    opened_at: datetime


class SignOffIn(_Record):
    """Someone from the incoming shift taking over with a handover."""

    by: PersonName
    note: Note = ""
    """Anything to say back to the outgoing shift."""


class SignOff(SignOffIn):
    """Who took over with a handover, and when."""

    at: datetime


class Handover(_Record):
    """What the incoming shift needs to know."""

    id: str | None = None
    """The saved handover's id, for a link to it; None for one worked out now."""
    since: datetime
    until: datetime
    timezone: str = "UTC"
    """The zone the shifts change in, for the message's times."""
    notes: list[ShiftNote] = []
    """What the outgoing shift wrote for the next, oldest first: for one
    worked out now, the notes written since the last shift change."""
    problems: list[RoutedProblem]
    """Everything wrong now, most urgent first, with who is on it."""
    incidents: list[IncidentLine] = []
    """Incidents open at the end of the span, or opened, cleared, or closed
    in it, newest first."""
    outages: list[Outage]
    """Those that began or ended in the span, latest first."""
    pages: list[Page]
    """Pages sent in the span, latest first."""
    acks: list[Ack]
    """Acknowledgements made in the span, latest first."""
    windows: list[Window]
    """Maintenance that ended in the span, is open, or opens in as long
    again, earliest first."""
    changes: list[Change]
    """Fixes and expectations recorded in the span, latest first."""
    findings: list[Finding]
    """Discovery findings first seen in the span and still seen."""
    oncall: OnCall | None
    """Who is on call now; None without an on-call directory."""
    signed: SignOff | None = None
    """Who took over with a saved handover, and when; None until someone
    does, and for one worked out now."""

    @computed_field
    @cached_property
    def message(self) -> Message:
        """The handover written to post in chat or send by email.

        Returns:
            A subject line saying how much is open, and the text: the notes,
            then the first few of each section, its times in the shifts' zone.
        """
        return _message(self)


class HandoverSummary(_Record):
    """A saved handover, in a line."""

    id: str
    since: datetime
    until: datetime
    problems: int
    unhandled: int
    """Problems no one was on: not acknowledged or planned."""
    outages: int
    still_down: int
    notes: int
    signed: SignOff | None


class HandoverList(_Record):
    """The handovers saved at shift changes, and when the next one is."""

    next: datetime | None
    """The next shift change; None without shift changes in the directory."""
    timezone: str | None
    current: str | None
    """The id of the handover the shift on now took over with, the only one
    that can be signed for; None if it was not saved."""
    handovers: list[HandoverSummary]
    """Latest first."""


class _Down:
    """One device or link down, from one event to the next."""

    def __init__(
        self, kind: str, name: str, start: datetime | None, planned: bool
    ) -> None:
        self.kind = kind
        self.name = name
        self.start = start
        self.end: datetime | None = None
        self.planned = planned


_DOWN = {"down": "device", "link-down": "link"}
_UP = {"up": "device", "link-up": "link"}


def outages(
    events: list[StateEvent], topology: Topology, since: datetime
) -> list[Outage]:
    """The outages that began or ended in a span, from the events of a day.

    Args:
        events: Everything the source saw, oldest first, from as far back
            as it goes.
        topology: The network, for the site of each device and link.
        since: When the span begins; it ends with the events.

    Returns:
        Devices at one site that went down at one step, with the links at
        that site that went down then, and every other link down, latest
        first. A device or link that came back with no event saying it
        went down was down before history begins.

    Raises:
        None
    """
    downs: list[_Down] = []
    now: dict[tuple[str, str], _Down] = {}
    for e in events:
        if e.kind in _DOWN:
            key = (_DOWN[e.kind], e.device or e.link or "")
            now[key] = _Down(key[0], key[1], e.at, e.planned)
            downs.append(now[key])
        elif e.kind in _UP:
            key = (_UP[e.kind], e.device or e.link or "")
            down = now.pop(key, None)
            if down is None:
                down = _Down(key[0], key[1], None, e.planned)
                downs.append(down)
            down.end = e.at
    kept = [
        d
        for d in downs
        if (d.start is not None and d.start >= since)
        or (d.end is not None and d.end >= since)
    ]
    site_of = {d.name: d.site for d in topology.devices}
    links = {ln.id: ln for ln in topology.links}
    groups: dict[tuple[datetime | None, str], list[_Down]] = {}
    alone: list[_Down] = []
    for d in kept:
        if d.kind == "device":
            groups.setdefault((d.start, site_of[d.name]), []).append(d)
    for d in kept:
        if d.kind != "link" or d.name not in links:
            continue
        link = links[d.name]
        sites = [site_of[link.a.device], site_of[link.b.device]]
        group = next(
            (groups[(d.start, s)] for s in sites if (d.start, s) in groups), None
        )
        (group if group is not None else alone).append(d)
    found = [_outage(site, members) for (_, site), members in groups.items()]
    found += [_outage(None, [d], link_name(links[d.name])) for d in alone]
    found.sort(key=lambda o: o.start.timestamp() if o.start else 0, reverse=True)
    return found


def _outage(site: str | None, members: list[_Down], name: str = "") -> Outage:
    devices = sorted((d.name for d in members if d.kind == "device"), key=natural)
    links = sorted(d.name for d in members if d.kind == "link")
    ends = [d.end for d in members]
    end = None if None in ends else max(e for e in ends if e is not None)
    if site is None:
        title = f"{name} down"
        target: Center = LinksCenter(kind="links", ids=links)
    elif len(devices) == 1 and not links:
        title = f"{devices[0]} down"
        target = DeviceCenter(kind="device", id=devices[0])
    else:
        parts = [_plural(len(devices), "device")]
        if links:
            parts.append(_plural(len(links), "link"))
        title = f"{site}: {' and '.join(parts)} down"
        target = SiteCenter(kind="site", id=site)
    return Outage(
        title=title,
        target=target,
        devices=devices,
        links=links,
        start=members[0].start,
        end=end,
        planned=all(d.planned for d in members),
    )


def _plural(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def shift_changes(
    times: HandoverTimes, since: datetime, until: datetime
) -> list[datetime]:
    """The shift changes after one moment, up to another.

    Args:
        times: When shifts change, in local time.
        since: Start, exclusive.
        until: End, inclusive.

    Returns:
        The changes, in order, in UTC. They stay at the same local time
        across a change to or from summer time.

    Raises:
        None
    """
    zone = ZoneInfo(times.timezone)
    day = since.astimezone(zone).date()
    found = []
    while day <= until.astimezone(zone).date():
        for clock in times.at:
            hours, minutes = (int(n) for n in clock.split(":"))
            local = datetime.combine(day, time(hours, minutes), tzinfo=zone)
            at = local.astimezone(UTC)
            if since < at <= until:
                found.append(at)
        day += timedelta(days=1)
    return found


def next_change(times: HandoverTimes, at: datetime) -> datetime:
    """The first shift change after a moment.

    Args:
        times: When shifts change.
        at: The moment.

    Returns:
        The change.

    Raises:
        None
    """
    return shift_changes(times, at, at + timedelta(days=2))[0]


def last_change(times: HandoverTimes, at: datetime) -> datetime:
    """The latest shift change before a moment.

    Args:
        times: When shifts change.
        at: The moment.

    Returns:
        The change, before the moment even if it is one itself.

    Raises:
        None
    """
    return [c for c in shift_changes(times, at - timedelta(days=2), at) if c < at][-1]


def handover_id(at: datetime) -> str:
    """The id of the handover saved at a shift change.

    Args:
        at: The change.

    Returns:
        For example ``20261027T1200Z``, in UTC.

    Raises:
        None
    """
    return at.astimezone(UTC).strftime("%Y%m%dT%H%MZ")


def summary(handover: Handover) -> HandoverSummary:
    """A saved handover, in a line.

    Args:
        handover: A saved handover.

    Returns:
        Its id and span, and how much it lists.

    Raises:
        None
    """
    return HandoverSummary(
        id=handover.id or "",
        since=handover.since,
        until=handover.until,
        problems=len(handover.problems),
        unhandled=sum(1 for p in handover.problems if not p.ack and not p.planned),
        outages=len(handover.outages),
        still_down=sum(1 for o in handover.outages if o.end is None),
        notes=len(handover.notes),
        signed=handover.signed,
    )


class _Saved(_Record):
    handovers: list[Handover] = []


class HandoverStore:
    """The handovers saved at shift changes, latest ``MAX_SAVED``, for one
    topology, in one JSON file, rewritten whole at each."""

    def __init__(self, path: Path) -> None:
        """Use a saved handovers file, created at the first shift change.

        Args:
            path: The JSON file.

        Raises:
            HandoverError: If the file exists but cannot be read.
        """
        self.path = path
        self.lock = Lock()
        """Held while working out and saving handovers, so each is saved once."""
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            raw = None
        except OSError as e:
            raise HandoverError(f"{path}: {e}") from e
        try:
            self._saved = _Saved.model_validate_json(raw) if raw else _Saved()
        except ValidationError as e:
            raise HandoverError(f"{path}: {e}") from e

    def handovers(self) -> list[Handover]:
        """Every saved handover, latest first.

        Returns:
            The handovers.

        Raises:
            None
        """
        return sorted(self._saved.handovers, key=lambda h: h.until, reverse=True)

    def get(self, handover_id: str) -> Handover | None:
        """A saved handover by id.

        Args:
            handover_id: Its id.

        Returns:
            The handover, or None if there is none.

        Raises:
            None
        """
        return next((h for h in self._saved.handovers if h.id == handover_id), None)

    def save(self, handover: Handover) -> None:
        """Keep a handover, dropping the oldest beyond ``MAX_SAVED``.

        Args:
            handover: The handover, with its id.

        Raises:
            None
        """
        kept = [h for h in self.handovers() if h.id != handover.id]
        saved = _Saved(handovers=[handover, *kept][:MAX_SAVED])
        temporary = self.path.with_name(f".{self.path.name}.tmp")
        # Without the messages and link ids, which are worked out again.
        body = saved.model_dump(mode="json", exclude_computed_fields=True)
        temporary.write_text(json.dumps(body), encoding="utf-8")
        os.replace(temporary, self.path)
        self._saved = saved

    def sign(self, handover_id: str, sign_off: SignOff) -> Handover:
        """Record who took over with a saved handover, holding ``lock``.

        Args:
            handover_id: Its id.
            sign_off: Who, when, and anything they said back.

        Returns:
            The handover, signed for.

        Raises:
            KeyError: If there is no such handover.
        """
        found = self.get(handover_id)
        if found is None:
            raise KeyError(handover_id)
        # Made again rather than copied, so its message is written again.
        signed = Handover.model_validate(
            {**found.model_dump(exclude_computed_fields=True), "signed": sign_off}
        )
        self.save(signed)
        return signed


def duration(span: timedelta) -> str:
    """A length of time, readably.

    Args:
        span: The time.

    Returns:
        For example "35 min", "1 h 05 min", "3 h".

    Raises:
        None
    """
    minutes = max(0, round(span.total_seconds() / 60))
    if minutes < 60:
        return f"{minutes} min"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes:02d} min" if minutes else f"{hours} h"


def standing(problem: RoutedProblem) -> str:
    """Who is on a problem, for its line in a handover.

    Args:
        problem: The problem.

    Returns:
        For example "On it: Pat · carrier ticket 4411", "Planned",
        "Paged, no one on it yet", or "No one on it".

    Raises:
        None
    """
    if problem.ack:
        note = f" · {problem.ack.note}" if problem.ack.note else ""
        return f"On it: {problem.ack.by}{note}"
    if problem.planned:
        return "Planned"
    if problem.paging and not problem.paging.stopped:
        return "Paged, no one on it yet"
    return "No one on it"


def _message(h: Handover) -> Message:
    zone = ZoneInfo(h.timezone)
    end = h.until.astimezone(zone)

    def clock(at: datetime) -> str:
        local = at.astimezone(zone)
        return local.strftime("%H:%M" if local.date() == end.date() else "%H:%M %a")

    def day(at: datetime) -> str:
        return at.astimezone(zone).strftime("%H:%M %a %d %b")

    def more(lines: list[str], total: int) -> list[str]:
        return lines + (
            [f"- and {total - len(lines)} more"] if total > len(lines) else []
        )

    teams = {t.id: t.name for t in h.oncall.teams} if h.oncall else {}
    people = {p.id: p for p in h.oncall.people} if h.oncall else {}
    unhandled = sum(1 for p in h.problems if not p.ack and not p.planned)
    down = sum(1 for o in h.outages if o.end is None)
    subject = (
        f"Shift handover {day(h.until)}: {len(h.problems)} open, "
        f"{unhandled} no one is on, {down} still down"
    )
    text = [
        f"Shift handover, {day(h.since)} to {day(h.until)} ({end.tzname()}), "
        f"the last {duration(h.until - h.since)}",
    ]
    if h.signed:
        said = f" · {h.signed.note}" if h.signed.note else ""
        text.append(f"Signed for by {h.signed.by} at {clock(h.signed.at)}{said}")
    elif h.id:
        text.append("Not signed for yet.")
    text.append("")
    if h.notes:
        text.append(f"Notes from the outgoing shift ({len(h.notes)})")
        text += [f"- {n.text} ({n.by}, {clock(n.at)})" for n in h.notes]
    else:
        text.append("No notes from the outgoing shift.")
    if h.incidents:
        text += ["", f"Incidents ({len(h.incidents)})"]
        for i in h.incidents:
            where = {
                "open": f"open since {clock(i.began or i.opened_at)}",
                "cleared": "cleared, postmortem to write",
                "closed": "closed",
            }[i.status]
            text.append(f"- {i.number} {i.title}: {where}")
    text += ["", f"Open now ({len(h.problems)}, {unhandled} no one is on)"]
    lines = []
    for p in h.problems[:LISTED]:
        parts = [p.title, *([p.detail] if p.detail else [])]
        parts += [teams.get(p.team, p.team)] if p.team else []
        lines.append(f"- {' · '.join([*parts, standing(p)])}")
    text += more(lines, len(h.problems))
    # Whole sites and links first: single devices are most of them.
    ordered = sorted(h.outages, key=lambda o: o.target.kind == "device")
    text += ["", f"Outages ({len(h.outages)} began or ended, {down} still down)"]
    lines = []
    for o in ordered[:LISTED]:
        start = clock(o.start) if o.start else "before history"
        stop = clock(o.end) if o.end else "still down"
        if o.start is None:
            lasted = "since before history" if o.end else "all day"
        else:
            lasted = duration((o.end or h.until) - o.start) + (
                "" if o.end else " so far"
            )
        planned = ", planned" if o.planned else ""
        lines.append(f"- {o.title}, {start} to {stop} ({lasted}{planned})")
    text += more(lines, len(h.outages))
    made = len(h.pages) + len(h.acks)
    if made:
        text += ["", f"Pages and acknowledgements ({made})"]
        lines = []
        for pg in h.pages:
            note = f" · {pg.note}" if pg.note else ""
            team = teams.get(pg.team, pg.team)
            lines.append(
                f"- {clock(pg.at)} {pg.by} paged {team}: {pg.title or pg.problem}{note}"
            )
        for a in h.acks:
            note = f" · {a.note}" if a.note else ""
            lines.append(f"- {clock(a.at)} {a.by} on {a.title or a.problem}{note}")
        text += more(lines[:LISTED], made)
    if h.windows:
        text += ["", f"Maintenance ({len(h.windows)})"]
        lines = []
        for w in h.windows:
            phase = (
                "Done"
                if w.end <= h.until
                else "Open now"
                if w.start <= h.until
                else "Coming"
            )
            lines.append(
                f"- {phase}: {w.title}, {clock(w.start)} to {clock(w.end)} ({w.by})"
            )
        text += more(lines[:LISTED], len(h.windows))
    if h.changes or h.findings:
        text += [
            "",
            f"Documentation: {len(h.changes)} fixed or marked expected, "
            f"{len(h.findings)} first seen by discovery",
        ]
    if h.oncall:
        text += ["", "On call now"]
        for t in h.oncall.teams:
            primary = people.get(t.now.primary)
            name = primary.name if primary else t.now.primary
            phone = f" ({primary.phone})" if primary and primary.phone else ""
            line = f"- {t.name}: {name}{phone}"
            if t.now.secondary:
                second = people.get(t.now.secondary)
                line += f", then {second.name if second else t.now.secondary}"
            text.append(f"{line}, until {day(t.now.until)}")
    return Message(subject=subject, text="\n".join(text))
