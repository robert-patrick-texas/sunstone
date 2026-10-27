"""Who owns what, who is on call for it, and whom a problem pages.

Teams own the network by routes, rules tried in order: the first whose
every condition matches an item owns it. A site matches on its code and
region; a device also on its role; a link on its kind and carrier and on
the sites, regions, and roles at either end. Each team has a rotation of
people who take turns as primary, the next in turn being secondary,
handing over at a set local time, and an escalation policy: who is paged
first, and who after how many minutes if no one acknowledges. Someone can
cover part of a shift. Carriers have NOC contacts for their circuits.

Sunstone sends nothing. A page is recorded and escalated on paper, the way
a paging service would, so the NOC sees who has been told and who will be
next; connecting a real service (PagerDuty, Opsgenie) is for later. The
directory is read from a YAML file beside the topology and checked against it.
"""

import zoneinfo
from collections.abc import Iterable, Mapping, Set
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Annotated, Literal, Self

import yaml
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)

from sunstone.layouts import Center
from sunstone.model import Link, LinkKind, Role, Topology
from sunstone.problems import Ack, Note, PersonName, Problem, ProblemKind

Id = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,39}$")]
Text = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
]
# A local time as "HH:MM". Quoted in YAML: unquoted, 10:00 reads as the number 600.
Clock = Annotated[str, StringConstraints(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")]
Urgency = Literal["high", "low"]
Duty = Literal["primary", "secondary", "manager"]

LONGEST_COVER = timedelta(days=14)
DEFAULT_URGENCY: dict[ProblemKind, Urgency] = {
    "outage": "high",
    "link-down": "high",
    "congested": "high",
    "loss": "low",
    "busy": "low",
    "nodata": "low",
}


class DirectoryError(Exception):
    """An on-call directory cannot be read, or does not fit the topology."""


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Person(_Record):
    """Someone who can be on call."""

    id: Id
    name: Text
    phone: Text | None = None


class Rotation(_Record):
    """People taking turns on call, handing over at a local time."""

    people: list[Id] = Field(min_length=1)
    """In turn; whoever is next after the primary is secondary."""
    every_days: int = Field(7, ge=1, le=28)
    handoff: Clock = "09:00"
    timezone: str = "UTC"
    starts: date
    """The local date the first person took over."""

    @field_validator("timezone")
    @classmethod
    def _known_zone(cls, value: str) -> str:
        try:
            zoneinfo.ZoneInfo(value)
        except (zoneinfo.ZoneInfoNotFoundError, ValueError) as e:
            raise ValueError(f"Unknown time zone {value!r}") from e
        return value


class Step(_Record):
    """One step of escalation: whom to page, so many minutes after the page."""

    after_min: int = Field(ge=0, le=24 * 60)
    to: Duty


DEFAULT_ESCALATION = (
    Step(after_min=0, to="primary"),
    Step(after_min=15, to="secondary"),
    Step(after_min=30, to="manager"),
)


class Team(_Record):
    """A team that owns part of the network."""

    id: Id
    name: Text
    rotation: Rotation
    manager: Id | None = None
    escalation: list[Step] = Field(
        default_factory=lambda: list(DEFAULT_ESCALATION), min_length=1
    )
    """Steps with no one to page (no manager, or no secondary in a rotation
    of one) are skipped."""

    @model_validator(mode="after")
    def _in_order(self) -> Self:
        minutes = [s.after_min for s in self.escalation]
        if minutes[0] != 0 or minutes != sorted(minutes):
            raise ValueError("Escalation starts at 0 minutes and goes on in order")
        return self


class Match(_Record):
    """Conditions on an item; every one given must hold, and an empty match
    holds for everything."""

    sites: list[str] = []
    regions: list[str] = []
    roles: list[Role] = []
    kinds: list[LinkKind] = []
    providers: list[str] = []


class Route(_Record):
    """Items matching this belong to this team, unless an earlier route matched."""

    match: Match = Match()
    team: Id


class Carrier(_Record):
    """How to reach a carrier's NOC about its circuits."""

    provider: Text
    phone: Text
    portal: Annotated[str, StringConstraints(pattern=r"^https?://\S+$")] | None = None


class Directory(_Record):
    """Teams, their people and rotations, what they own, and carrier contacts."""

    people: list[Person]
    teams: list[Team] = Field(min_length=1)
    routes: list[Route] = Field(min_length=1)
    carriers: list[Carrier] = []
    urgency: dict[ProblemKind, Urgency] = {}
    """Which kinds of problem page someone at once (high) or wait for
    working hours (low); kinds left out are as ``DEFAULT_URGENCY`` says."""

    @model_validator(mode="after")
    def _references(self) -> Self:
        people = {p.id for p in self.people}
        teams = {t.id for t in self.teams}
        problems = [
            f"{what} {name!r} is listed twice"
            for what, names in (
                ("person", [p.id for p in self.people]),
                ("team", [t.id for t in self.teams]),
                ("carrier", [c.provider for c in self.carriers]),
            )
            for name in sorted({n for n in names if names.count(n) > 1})
        ]
        for team in self.teams:
            problems += [
                f"team {team.id!r}: no person {p!r}"
                for p in [*team.rotation.people, team.manager]
                if p is not None and p not in people
            ]
        problems += [
            f"route {i + 1}: no team {r.team!r}"
            for i, r in enumerate(self.routes)
            if r.team not in teams
        ]
        if problems:
            raise ValueError("; ".join(problems))
        return self

    def urgency_of(self, kind: ProblemKind) -> Urgency:
        """How urgent a kind of problem is.

        Args:
            kind: The kind.

        Returns:
            High to page at once, low to wait for working hours.

        Raises:
            None
        """
        return self.urgency.get(kind, DEFAULT_URGENCY[kind])

    def team(self, team_id: str) -> Team | None:
        """A team by id.

        Args:
            team_id: Its id.

        Returns:
            The team, or None if there is none.

        Raises:
            None
        """
        return next((t for t in self.teams if t.id == team_id), None)


def load_directory(path: Path, topology: Topology) -> Directory:
    """Read an on-call directory and check it against the topology.

    Args:
        path: YAML file with ``people``, ``teams``, ``routes``, and
            optionally ``carriers`` and ``urgency``.
        topology: The topology its routes refer to.

    Returns:
        The directory.

    Raises:
        DirectoryError: If the file cannot be read, is not YAML, is not a
            valid directory, or names sites, regions, or carriers the
            topology does not have. The message names every problem found.
    """
    try:
        with path.open(encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as e:
        raise DirectoryError(f"{path}: {e}") from e
    try:
        directory = Directory.model_validate(raw)
    except ValidationError as e:
        raise DirectoryError(f"{path}: {e}") from e
    unknown = _unknown(directory, topology)
    if unknown:
        raise DirectoryError(f"{path}: {'; '.join(unknown)}")
    return directory


def _unknown(directory: Directory, topology: Topology) -> list[str]:
    known = {
        "site": {s.code for s in topology.sites},
        "region": {s.region for s in topology.sites if s.region},
        "carrier": {ln.circuit.provider for ln in topology.links if ln.circuit},
    }
    named: list[tuple[str, str, Iterable[str]]] = []
    for i, route in enumerate(directory.routes):
        where = f"route {i + 1}"
        named += [
            (where, "site", route.match.sites),
            (where, "region", route.match.regions),
            (where, "carrier", route.match.providers),
        ]
    named.append(("carriers", "carrier", [c.provider for c in directory.carriers]))
    return [
        f"{where}: no {what} {name!r} in the topology"
        for where, what, names in named
        for name in names
        if name not in known[what]
    ]


class CoverIn(_Record):
    """Someone taking a team's primary turn for a while."""

    team: Id
    person: Id
    start: AwareDatetime
    end: AwareDatetime
    note: Note = ""
    by: PersonName

    @model_validator(mode="after")
    def _sensible(self) -> Self:
        if not self.start < self.end:
            raise ValueError("Cover must end after it starts")
        if self.end - self.start > LONGEST_COVER:
            raise ValueError(f"Cover can be at most {LONGEST_COVER.days} days long")
        return self


class Cover(CoverIn):
    """A saved cover."""

    id: str
    saved_at: datetime


class Shift(_Record):
    """Who is on call for a team over a stretch of time."""

    team: str
    primary: str
    secondary: str | None
    since: datetime
    until: datetime
    cover: str | None = None
    """The cover that puts the primary on, if one does."""


def _turn(rotation: Rotation, at: datetime) -> tuple[int, datetime, datetime]:
    """Which turn of a rotation holds a moment, and when it starts and ends.

    Handovers are at the same local time on each day they fall on, so a
    turn is an hour shorter or longer across a change to or from summer time.
    """
    zone = zoneinfo.ZoneInfo(rotation.timezone)
    hours, minutes = (int(n) for n in rotation.handoff.split(":"))
    handoff = time(hours, minutes)
    local = at.astimezone(zone)
    days = (local.date() - rotation.starts).days - (local.time() < handoff)
    turn = days // rotation.every_days
    first = rotation.starts + timedelta(days=turn * rotation.every_days)
    since = datetime.combine(first, handoff, tzinfo=zone)
    until = datetime.combine(
        first + timedelta(days=rotation.every_days), handoff, tzinfo=zone
    )
    # In UTC, so differences are real time, not wall-clock time.
    return turn, since.astimezone(UTC), until.astimezone(UTC)


def shift(team: Team, at: datetime, covers: list[Cover]) -> Shift:
    """Who is on call for a team at a moment.

    Args:
        team: The team.
        at: The moment.
        covers: Every cover; only the team's count.

    Returns:
        The primary and secondary, and from when until when they are on
        together. When someone covers, they are primary and the primary
        they cover for becomes secondary.

    Raises:
        None
    """
    turn, since, until = _turn(team.rotation, at)
    people = team.rotation.people
    primary = people[turn % len(people)]
    secondary = people[(turn + 1) % len(people)] if len(people) > 1 else None
    mine = sorted(
        (c for c in covers if c.team == team.id), key=lambda c: (c.start, c.saved_at)
    )
    standing = [c for c in mine if c.start <= at < c.end]
    if standing:
        cover = standing[-1]
        if cover.person != primary:
            primary, secondary = cover.person, primary
        since, until = max(since, cover.start), min(until, cover.end)
        return Shift(
            team=team.id,
            primary=primary,
            secondary=secondary,
            since=since,
            until=until,
            cover=cover.id,
        )
    # A cover starting before the turn ends ends this shift early.
    until = min([until, *(c.start for c in mine if at < c.start < until)])
    return Shift(
        team=team.id, primary=primary, secondary=secondary, since=since, until=until
    )


def _who(team: Team, to: Duty, at: datetime, covers: list[Cover]) -> str | None:
    if to == "manager":
        return team.manager
    on = shift(team, at, covers)
    return on.primary if to == "primary" else on.secondary


class PageIn(_Record):
    """Someone paging a problem's team."""

    problem: str = Field(min_length=1, max_length=300)
    note: Note = ""
    by: PersonName
    link: str = Field("", max_length=2000)
    """Where in Sunstone to look, sent with the page."""


class Page(PageIn):
    """A page, as recorded. Nothing is sent."""

    id: str
    team: str
    at: datetime
    cleared_at: datetime | None = None
    """When the problem cleared, ending the page."""
    title: str | None = None
    """The problem's title when it was paged, to say what it was about once
    it has cleared."""

    def active(self, at: datetime) -> bool:
        """Whether it stands at a moment.

        Args:
            at: The moment.

        Returns:
            True from when it was made until its problem cleared.

        Raises:
            None
        """
        return self.at <= at and (self.cleared_at is None or at < self.cleared_at)


class Notice(_Record):
    """One person told, or to be told, about a page."""

    to: Duty
    person: str
    at: datetime


class Paging(_Record):
    """Where a page stands at a moment."""

    page: Page
    notified: list[Notice]
    """Everyone told so far, in order."""
    next: Notice | None
    """Who is told next if no one acknowledges, and when."""
    stopped: Literal["acknowledged", "cleared"] | None
    """Why escalation stopped, if it has."""


def escalation(
    page: Page, team: Team, ack: Ack | None, covers: list[Cover], at: datetime
) -> Paging:
    """Where a page stands at a moment, following the team's escalation policy.

    Each step tells whoever holds its role at the time it comes due.
    Escalation stops once the problem is acknowledged or clears; the first
    step always happens, since that is the page itself.

    Args:
        page: The page.
        team: The team paged.
        ack: The problem's acknowledgement, if any.
        covers: Every cover.
        at: The moment.

    Returns:
        Who has been told by then, who is next, and why it stopped, if it has.

    Raises:
        None
    """
    # Only what has happened by the moment counts, so replaying an earlier
    # moment shows escalation as it stood then.
    ends = [page.cleared_at, ack.at if ack and ack.at >= page.at else None]
    end = min((t for t in ends if t is not None and t <= at), default=None)
    notified: list[Notice] = []
    upcoming: Notice | None = None
    for step in team.escalation:
        when = page.at + timedelta(minutes=step.after_min)
        if notified and end is not None and when >= end:
            break
        person = _who(team, step.to, when, covers)
        if person is None:
            continue
        notice = Notice(to=step.to, person=person, at=when)
        if when > at:
            upcoming = notice
            break
        notified.append(notice)
    stopped: Literal["acknowledged", "cleared"] | None = None
    if ack and page.at <= ack.at <= at:
        stopped = "acknowledged"
    elif page.cleared_at and page.cleared_at <= at:
        stopped = "cleared"
    return Paging(
        page=page,
        notified=notified,
        next=None if stopped else upcoming,
        stopped=stopped,
    )


class Ownership(_Record):
    """The team that owns each site, device, and link, by code, name, and
    id; anything no route matches is left out."""

    sites: dict[str, str]
    devices: dict[str, str]
    links: dict[str, str]

    def owner(self, target: Center) -> str | None:
        """The team that owns a site, device, or links.

        Args:
            target: What to look up.

        Returns:
            The team's id; for several links, the owner of the first one
            owned. None if no route matches.

        Raises:
            None
        """
        if target.kind == "site":
            return self.sites.get(target.id)
        if target.kind == "device":
            return self.devices.get(target.id)
        return next((self.links[i] for i in target.ids if i in self.links), None)


# A route as (team, conditions): each condition a label and the values it accepts.
_Compiled = list[tuple[str, list[tuple[str, frozenset[str]]]]]


def _compile(routes: list[Route]) -> _Compiled:
    return [
        (r.team, [(k, frozenset(v)) for k, v in r.match.model_dump().items() if v])
        for r in routes
    ]


def _first(routes: _Compiled, labels: Mapping[str, Set[str]]) -> str | None:
    """The team of the first route whose every condition the labels meet."""
    for team, conditions in routes:
        if all(not wanted.isdisjoint(labels.get(k, ())) for k, wanted in conditions):
            return team
    return None


def ownership(directory: Directory, topology: Topology) -> Ownership:
    """Work out who owns everything.

    Args:
        directory: Routes to try in order.
        topology: The network.

    Returns:
        The owner of every site, device, and link a route matches.

    Raises:
        None
    """
    region = {s.code: s.region for s in topology.sites}
    devices = {d.name: d for d in topology.devices}

    def place(site: str) -> dict[str, Set[str]]:
        found = region.get(site)
        return {"sites": {site}, "regions": {found} if found else set()}

    def link_labels(link: Link) -> dict[str, Set[str]]:
        ends = [devices[e.device] for e in (link.a, link.b)]
        a, b = (place(d.site) for d in ends)
        return {
            "sites": a["sites"] | b["sites"],
            "regions": a["regions"] | b["regions"],
            "roles": {d.role for d in ends},
            "kinds": {link.kind},
            "providers": {link.circuit.provider} if link.circuit else set(),
        }

    routes = _compile(directory.routes)

    def owned(labelled: Iterable[tuple[str, Mapping[str, Set[str]]]]) -> dict[str, str]:
        found = ((key, _first(routes, labels)) for key, labels in labelled)
        return {key: team for key, team in found if team is not None}

    return Ownership(
        sites=owned((s.code, place(s.code)) for s in topology.sites),
        devices=owned(
            (d.name, place(d.site) | {"roles": {d.role}}) for d in topology.devices
        ),
        links=owned((ln.id, link_labels(ln)) for ln in topology.links),
    )


def describe(match: Match) -> str:
    """What a route covers, in words.

    Args:
        match: The route's conditions.

    Returns:
        For example "WAN links", "Core devices at DAL, IAD", "Everything in
        South, Midwest", or "Everything else" for an empty match.

    Raises:
        None
    """
    what = []
    if match.kinds:
        what.append(" and ".join(k.upper() for k in match.kinds) + " links")
    if match.providers:
        what.append("circuits from " + ", ".join(match.providers))
    if match.roles:
        what.append(", ".join(match.roles) + " devices")
    where = []
    if match.sites:
        where.append("at " + ", ".join(match.sites))
    if match.regions:
        where.append("in " + ", ".join(match.regions))
    if not what and not where:
        return "Everything else"
    text = " ".join([", ".join(what) or "Everything", *where])
    return text[0].upper() + text[1:]


class RoutedProblem(Problem):
    """A problem, with who owns it and whom it has paged."""

    team: str | None = None
    """The team that owns what it is about."""
    urgency: Urgency = "high"
    paging: Paging | None = None
    """Its page as it stands, if it has been paged."""


class RoutedProblemList(_Record):
    """The problems in one snapshot, most urgent first, routed."""

    at: datetime
    problems: list[RoutedProblem]


class TeamNow(_Record):
    """A team, who is on call for it, and who is on next."""

    id: str
    name: str
    owns: list[str]
    """What its routes cover, in words."""
    rotation: list[str]
    """Everyone who takes turns, in turn."""
    now: Shift
    next: Shift
    manager: str | None
    escalation: list[Step]


class OnCall(_Record):
    """Who is on call for every team at a moment, and how to reach them."""

    at: datetime
    teams: list[TeamNow]
    people: list[Person]
    carriers: list[Carrier]
    covers: list[Cover]
    """Covers standing at the moment or still to come."""
    urgency: dict[ProblemKind, Urgency]


def _start(cover: Cover) -> datetime:
    return cover.start


def on_call(directory: Directory, at: datetime, covers: list[Cover]) -> OnCall:
    """Who is on call for every team at a moment.

    Args:
        directory: The directory.
        at: The moment.
        covers: Every cover.

    Returns:
        Each team's shift then and the one after it, with everything needed
        to reach the people on them.

    Raises:
        None
    """
    teams = []
    for team in directory.teams:
        now = shift(team, at, covers)
        teams.append(
            TeamNow(
                id=team.id,
                name=team.name,
                owns=[describe(r.match) for r in directory.routes if r.team == team.id],
                rotation=team.rotation.people,
                now=now,
                next=shift(team, now.until, covers),
                manager=team.manager,
                escalation=team.escalation,
            )
        )
    return OnCall(
        at=at,
        teams=teams,
        people=directory.people,
        carriers=directory.carriers,
        covers=sorted([c for c in covers if c.end > at], key=_start),
        urgency={k: directory.urgency_of(k) for k in DEFAULT_URGENCY},
    )
