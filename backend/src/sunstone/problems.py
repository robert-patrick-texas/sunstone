"""The problems live state shows, ranked the way a NOC works through them.

Worked out once per snapshot on the server, so every viewer shares the work.

Devices that the core cannot reach are grouped into one outage per
connected group, so a branch that loses its circuits is one problem, not
one per device. The devices where reach stops are its edge: they are
reported down, or sit behind links that are. Monitoring cannot tell a dead
router from one behind a dead circuit, so the outage names both. Links down
between devices the core still reaches come next, then congestion, packet
loss, busy links, and devices without a recent reading.

Device and link health follow the same rules as the web UI's ``live.ts``:
a stale reading is no data, whatever it said; any loss of 1% or more from a
position is degraded; a link takes its state from whichever end reports.
"""

import math
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from sunstone.impact import FailedSet, Failures, Impact, Network
from sunstone.layouts import Center, DeviceCenter, LinksCenter, SiteCenter
from sunstone.live import DeviceState, InterfaceState, NetworkState
from sunstone.model import Endpoint, Link

DEGRADED_LOSS_PCT = 1
HIGH_PCT = 80
CRITICAL_PCT = 95
# Most names spelled out in a detail line.
NAMED = 3

Health = Literal["up", "degraded", "down", "nodata", "unmonitored"]
LinkHealth = Literal["ok", "down", "nodata", "unmonitored"]
ProblemKind = Literal["outage", "link-down", "congested", "loss", "busy", "nodata"]
KINDS: list[ProblemKind] = [
    "outage",
    "link-down",
    "congested",
    "loss",
    "busy",
    "nodata",
]


PersonName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)
]
Note = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AckIn(_Record):
    """Someone taking on a problem."""

    problem: str = Field(min_length=1, max_length=300)
    note: Note = ""
    by: PersonName


class Ack(AckIn):
    """An acknowledged problem."""

    at: datetime
    cleared_at: datetime | None = None
    """When the problem cleared, ending the acknowledgement."""
    title: str | None = None
    """The problem's title when it was acknowledged, to say what it was about
    once it has cleared."""

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


class Problem(_Record):
    """One thing wrong, with what it does to the network."""

    id: str
    """The same from one snapshot to the next while the problem lasts."""
    kind: ProblemKind
    title: str
    detail: str
    target: Center
    """What to select to look at it."""
    impact: Impact | None
    """What it does to the network (outages and links down only)."""
    lost: int
    """Devices it leaves unreachable."""
    exposed: int
    """Devices it leaves without redundancy."""
    planned: list[str] = []
    """Ids of the open maintenance windows that account for it, if they do."""
    ack: Ack | None = None
    """Who is on it, if anyone."""


class ProblemList(_Record):
    """The problems in one snapshot, most urgent first."""

    at: datetime
    problems: list[Problem]


@dataclass(frozen=True)
class LinkState:
    """A link's state, from whichever of its ends report it."""

    health: LinkHealth
    a_to_b: float | None = None
    b_to_a: float | None = None
    util: float | None = None
    """Percent load in the busier direction."""


class LiveView:
    """Lookups over one snapshot."""

    def __init__(self, state: NetworkState) -> None:
        """Index a snapshot.

        Args:
            state: The snapshot.

        Raises:
            None
        """
        self.state = state
        self.devices = {d.device: d for d in state.devices}
        self.interfaces = {(i.device, i.interface): i for i in state.interfaces}

    def health(self, device: str) -> Health:
        """A device's health.

        Args:
            device: Device name.

        Returns:
            ``nodata`` for a stale reading, whatever it said; else down,
            degraded (loss from some position), or up; ``unmonitored`` if
            the source has no record.

        Raises:
            None
        """
        d = self.devices.get(device)
        if d is None:
            return "unmonitored"
        if d.stale:
            return "nodata"
        if d.status == "down":
            return "down"
        lossy = any((r.loss_pct or 0) >= DEGRADED_LOSS_PCT for r in d.reachability)
        return "degraded" if lossy else "up"

    def link(self, link: Link) -> LinkState:
        """A link's state.

        Args:
            link: The link.

        Returns:
            Its health and load each way, read from either end.

        Raises:
            None
        """
        a, b = self.devices.get(link.a.device), self.devices.get(link.b.device)
        if a is None and b is None:
            return LinkState("unmonitored")
        ra = _fresh(self.interfaces.get((link.a.device, link.a.interface)))
        rb = _fresh(self.interfaces.get((link.b.device, link.b.interface)))
        if any(_down(d) for d in (a, b)) or any(
            r and r.oper == "down" for r in (ra, rb)
        ):
            return LinkState("down")
        a_to_b = _first(ra.out_pct if ra else None, rb.in_pct if rb else None)
        b_to_a = _first(ra.in_pct if ra else None, rb.out_pct if rb else None)
        if a_to_b is None and b_to_a is None:
            return LinkState("nodata")
        return LinkState("ok", a_to_b, b_to_a, max(a_to_b or 0, b_to_a or 0))


def current_failures(network: Network, view: LiveView) -> Failures:
    """What live state shows has failed: devices down, and links down.

    Args:
        network: The topology.
        view: The snapshot.

    Returns:
        The failed devices and links.

    Raises:
        None
    """
    devices = frozenset(n for n in network.names if view.health(n) == "down")
    links = frozenset(
        i for i, link in network.links.items() if view.link(link).health == "down"
    )
    return Failures(devices, links)


def find_problems(network: Network, view: LiveView) -> list[Problem]:
    """Every problem in a snapshot, most urgent first.

    Args:
        network: The topology.
        view: The snapshot.

    Returns:
        Problems by kind, then by devices unreachable, devices without
        redundancy, and name.

    Raises:
        None
    """
    failures = current_failures(network, view)
    reached = network.reach(failures).reached
    unreached = network.reach(Failures()).reached - reached
    problems = [
        *_outages(network, view, unreached, reached),
        *_links_down(network, failures, reached),
        *_loads(network, view),
        *_device_problems(network, view, unreached),
    ]
    return sorted(
        problems,
        key=lambda p: (KINDS.index(p.kind), -p.lost, -p.exposed, natural(p.title)),
    )


def _outages(
    network: Network, view: LiveView, unreached: frozenset[str], reached: frozenset[str]
) -> list[Problem]:
    problems: list[Problem] = []
    seen: set[str] = set()
    for start in sorted(unreached, key=natural):
        if start in seen:
            continue
        # One outage per connected group of unreached devices.
        group = {start}
        boundary: list[Link] = []
        frontier = [start]
        while frontier:
            following: list[str] = []
            for device in frontier:
                for link in network.links_of.get(device, []):
                    other = link.b.device if link.a.device == device else link.a.device
                    if other in reached:
                        boundary.append(link)
                    elif other in unreached and other not in group:
                        group.add(other)
                        following.append(other)
            frontier = following
        seen |= group

        edge = {
            link.a.device if link.a.device in group else link.b.device
            for link in boundary
        }
        down = sorted((d for d in edge if view.health(d) == "down"), key=natural)
        lost = Failures(frozenset(group), frozenset(link.id for link in boundary))
        exposed = network.impact(lost).exposed
        impact = Impact(
            failed=FailedSet(devices=down, links=sorted(lost.links)),
            cut_off=sorted(group - set(down), key=natural),
            exposed=exposed,
        )
        devices = sorted(group, key=natural)
        sites = sorted({network.site_of[d] for d in devices}, key=natural)
        whole = all(d in group for s in sites for d in network.devices_of[s])
        circuits = [link.circuit.circuit_id for link in boundary if link.circuit]
        if len(group) == 1:
            title = f"{start} {'down' if down else 'unreachable'}"
        elif whole:
            title = f"{', '.join(sites)} cut off"
        else:
            title = f"{len(group)} devices unreachable at {', '.join(sites)}"
        if len(group) == 1:
            where = ""
        elif len(circuits) == len(boundary):
            where = f"{_plural(len(circuits), 'circuit')} {_names(circuits)} down"
        else:
            where = f"reach stops at {_names(sorted(edge, key=natural))}"
        target: Center = (
            SiteCenter(kind="site", id=sites[0])
            if len(sites) == 1 and whole
            else DeviceCenter(kind="device", id=devices[0])
        )
        problems.append(
            Problem(
                id=f"outage:{devices[0]}",
                kind="outage",
                title=title,
                detail=_join(
                    _plural(len(group), "device") if len(group) > 1 else "",
                    where,
                    _exposure(len(exposed)),
                ),
                target=target,
                impact=impact,
                lost=len(group),
                exposed=len(exposed),
            )
        )
    return problems


def _links_down(
    network: Network, failures: Failures, reached: frozenset[str]
) -> list[Problem]:
    problems: list[Problem] = []
    for link_id in failures.links:
        link = network.links.get(link_id)
        if not link or link.a.device not in reached or link.b.device not in reached:
            continue
        impact = network.impact(Failures(links=frozenset([link_id])))
        problems.append(
            Problem(
                id=f"down:{link_id}",
                kind="link-down",
                title=f"{link_name(link)} down",
                detail=_join(
                    _ends(link), _exposure(len(impact.exposed)) or "redundancy holds"
                ),
                target=LinksCenter(kind="links", ids=[link_id]),
                impact=impact,
                lost=0,
                exposed=len(impact.exposed),
            )
        )
    return problems


def _loads(network: Network, view: LiveView) -> list[Problem]:
    problems: list[Problem] = []
    for link in network.topology.links:
        state = view.link(link)
        if state.health != "ok" or state.util is None or state.util < HIGH_PCT:
            continue
        forward = (state.a_to_b or 0) >= (state.b_to_a or 0)
        start, end = (link.a, link.b) if forward else (link.b, link.a)
        problems.append(
            Problem(
                id=f"load:{link.id}",
                kind="congested" if state.util >= CRITICAL_PCT else "busy",
                title=f"{link_name(link)} at {_round(state.util)}%",
                detail=_join(
                    f"{start.device} {short_interface(start.interface)} → {end.device}",
                    f"{format_speed(link.speed_mbps)} link",
                ),
                target=LinksCenter(kind="links", ids=[link.id]),
                impact=None,
                lost=0,
                exposed=0,
            )
        )
    return problems


def _device_problems(
    network: Network, view: LiveView, unreached: frozenset[str]
) -> list[Problem]:
    problems: list[Problem] = []
    at = view.state.generated_at
    for name in network.names:
        record = view.devices.get(name)
        health = view.health(name)
        if name in unreached or record is None or health not in ("degraded", "nodata"):
            continue
        target = DeviceCenter(kind="device", id=name)
        if health == "nodata":
            minutes = _round((at - record.observed_at).total_seconds() / 60)
            detail = f"last reading {minutes} min before this snapshot"
            kind: ProblemKind = "nodata"
        else:
            detail = _join(
                *(
                    f"{r.loss_pct:g}% from {r.position}"
                    for r in record.reachability
                    if (r.loss_pct or 0) > 0
                )
            )
            kind = "loss"
        problems.append(
            Problem(
                id=f"{kind}:{name}",
                kind=kind,
                title=name,
                detail=detail,
                target=target,
                impact=None,
                lost=0,
                exposed=0,
            )
        )
    return problems


ABBREVIATIONS = [
    ("HundredGigE", "Hu"),
    ("FortyGigabitEthernet", "Fo"),
    ("TwentyFiveGigE", "Twe"),
    ("TenGigabitEthernet", "Te"),
    ("GigabitEthernet", "Gi"),
    ("FastEthernet", "Fa"),
    ("Port-channel", "Po"),
    ("Ethernet", "Eth"),
]


def short_interface(name: str) -> str:
    """Abbreviate an interface name the way IOS does.

    Args:
        name: Full interface name, such as ``TenGigabitEthernet1/0/1``, in
            any case.

    Returns:
        The short form, such as ``Te1/0/1``, or the name unchanged.

    Raises:
        None
    """
    for long, short in ABBREVIATIONS:
        if name[: len(long)].lower() == long.lower():
            return short + name[len(long) :]
    return name


def format_speed(mbps: int) -> str:
    """Format a speed, such as ``100M``, ``1G``, ``2.5G``, or ``1.2T``.

    Args:
        mbps: Megabits per second.

    Returns:
        The speed with its unit.

    Raises:
        None
    """
    if mbps >= 1_000_000:
        return f"{round(mbps / 1_000_000, 1):g}T"
    if mbps >= 1_000:
        return f"{round(mbps / 1_000, 1):g}G"
    return f"{mbps}M"


def link_name(link: Link) -> str:
    """A short name for a link: a circuit by its ID, any other by its devices.

    Args:
        link: The link.

    Returns:
        The name.

    Raises:
        None
    """
    if link.circuit:
        return f"Circuit {link.circuit.circuit_id}"
    return f"{link.a.device} – {link.b.device}"


def natural(text: str) -> list[int | str]:
    """Sort key putting embedded numbers in numeric order: ``a2`` before ``a10``.

    Args:
        text: The text to sort.

    Returns:
        The key.

    Raises:
        None
    """
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", text)]


def _fresh(reading: InterfaceState | None) -> InterfaceState | None:
    return reading if reading and not reading.stale else None


def _down(device: DeviceState | None) -> bool:
    return device is not None and not device.stale and device.status == "down"


def _first(*values: float | None) -> float | None:
    return next((v for v in values if v is not None), None)


def _round(value: float) -> int:
    """Round half up, as the web UI does."""
    return math.floor(value + 0.5)


def _ends(link: Link) -> str:
    def end(e: Endpoint) -> str:
        return f"{e.device} {short_interface(e.interface)}"

    return f"{end(link.a)} ↔ {end(link.b)}"


def _exposure(count: int) -> str:
    return f"{_plural(count, 'device')} left without redundancy" if count else ""


def _names(names: list[str]) -> str:
    shown = ", ".join(names[:NAMED])
    return f"{shown} and {len(names) - NAMED} more" if len(names) > NAMED else shown


def _plural(n: int, noun: str) -> str:
    return f"{n} {noun}{'' if n == 1 else 's'}"


def _join(*parts: str) -> str:
    return " · ".join(p for p in parts if p)
