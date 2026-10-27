"""What the incoming shift needs to know: the last hours, and what is open now.

A handover covers a span ending now, 12 hours unless asked otherwise: the
problems there are now, who is on them and whom they have paged; the
outages that began or ended in the span, and how long they lasted; the
pages and acknowledgements made in it; maintenance done in it, open now,
or coming in as long again; fixes and expectations recorded in it;
discovery findings first seen in it; and who is on call now.

Outages come from the source's events: each device and link is down from
one event to the next. They are grouped as the events list groups them:
devices at one site that went down at the same step are one outage, with
the links at that site that went down then. As with problems, nothing is
guessed about why.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from sunstone.changes import Change
from sunstone.discovery import Finding
from sunstone.layouts import Center, DeviceCenter, LinksCenter, SiteCenter
from sunstone.live import StateEvent
from sunstone.model import Topology
from sunstone.oncall import OnCall, Page, RoutedProblem
from sunstone.operations import Window
from sunstone.problems import Ack, link_name, natural


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


class Handover(_Record):
    """What the incoming shift needs to know."""

    since: datetime
    until: datetime
    problems: list[RoutedProblem]
    """Everything wrong now, most urgent first, with who is on it."""
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
