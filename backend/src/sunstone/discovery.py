"""What devices say is connected to them, against what the topology documents.

Devices report their neighbors over LLDP or CDP: for each port, the name
the device at the other end gives itself, and the port it is on. Comparing
those tables with the documented links finds where the documentation and
the network disagree: a documented link no one sees, a cable on another
port or to another device than documented, a link no one documented, a
neighbor that is not in the topology at all, or a device that reports no
neighbors, as when LLDP and CDP are off on it.

Where the documentation can be fixed to match, a finding offers the fix: a
link on another port or device moved to where its cable is seen, a cable no
one documented added, a link no one sees retired. A neighbor not in the
topology and a device that sees nothing are left to people: the first needs
the device documented, or unplugged; the second, LLDP or CDP turned on.

What discovery cannot see, or is not meant to be documented, can instead
be marked expected: a link across a media converter that hides LLDP, a
lab port, a switch with LLDP off on purpose. ``expecting`` sets those
findings aside, so they are no longer listed, drawn, or offered a fix.

Only what discovery can check counts. A device that does not answer (not
polled, down, or unreachable) reports nothing, though its neighbors still
see it; and a link that is down is not seen, whatever is documented, so
neither is a finding. A real discovery source would be a collector reading
LLDP-MIB and CDP-MIB, or an NMS's neighbor tables; the only one so far is
simulated, reporting the simulated network as really cabled (``cabling.py``).
"""

import functools
from collections.abc import Set
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from sunstone.cabling import Cabling
from sunstone.live import NetworkState, StateSource
from sunstone.model import Device, Endpoint, Link, Topology
from sunstone.problems import ABBREVIATIONS, natural, short_interface

LinkCheck = Literal[
    "confirmed", "mismatch", "not-seen", "expected", "down", "unchecked"
]
FindingKind = Literal[
    "wrong-neighbor",
    "wrong-port",
    "not-seen",
    "undocumented",
    "unknown-device",
    "no-neighbors",
]
FixKind = Literal["move", "add", "retire", "expect"]
# A device that reports no neighbors: its finding's id, before its name.
SILENT = "no-neighbors:"
KINDS: list[FindingKind] = [
    "wrong-neighbor",
    "wrong-port",
    "not-seen",
    "undocumented",
    "unknown-device",
    "no-neighbors",
]
# Kinds that may be what discovery cannot see, or what is not meant to be
# documented; a link on another port or device is fixed instead.
EXPECTABLE: frozenset[FindingKind] = frozenset(
    {"not-seen", "unknown-device", "no-neighbors"}
)


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Neighbor(_Record):
    """One row of a device's neighbor table."""

    interface: str
    """The local port, as the device names it."""
    remote: str
    """The name the neighbor gives itself, often with a domain."""
    remote_port: str
    protocol: Literal["lldp", "cdp"]
    platform: str | None = None


class NeighborTable(_Record):
    """Everything one device reports as connected to it."""

    device: str
    neighbors: list[Neighbor]


class Discovery(_Record):
    """Neighbor tables from one discovery run: one per device that answered."""

    source: str
    at: datetime
    tables: list[NeighborTable]


@dataclass(frozen=True)
class Visibility:
    """What live state says, at a run, about what discovery can see."""

    up: frozenset[str]
    """Devices up and reporting, which answer discovery."""
    down_devices: frozenset[str]
    down_ports: frozenset[tuple[str, str]]
    """(device, interface) pairs whose port is down."""

    @classmethod
    def of(cls, state: NetworkState) -> Visibility:
        """Read it from a snapshot.

        Args:
            state: Live state as of the run.

        Returns:
            Who is up, who is down, and which ports are down.

        Raises:
            None
        """
        return cls(
            up=frozenset(
                d.device for d in state.devices if d.status == "up" and not d.stale
            ),
            down_devices=frozenset(
                d.device for d in state.devices if d.status == "down"
            ),
            down_ports=frozenset(
                (i.device, i.interface) for i in state.interfaces if i.oper == "down"
            ),
        )


@runtime_checkable
class SeesWhoIsUp(Protocol):
    """A state source that can say who is up more cheaply than a snapshot."""

    def visibility(self, at: datetime) -> Visibility:
        """What discovery can see at a moment.

        Args:
            at: The moment.

        Returns:
            Who is up, who is down, and which ports are down.
        """
        ...


def visibility(state: StateSource, at: datetime) -> Visibility:
    """What discovery can see at a moment, as cheaply as the source allows.

    Args:
        state: Live state.
        at: The moment.

    Returns:
        Who is up, who is down, and which ports are down.

    Raises:
        None
    """
    if isinstance(state, SeesWhoIsUp):
        return state.visibility(at)
    return Visibility.of(state.snapshot(at))


class DiscoverySource(Protocol):
    """Where neighbor tables come from."""

    interval: timedelta
    """How often it runs."""

    def discover(self, at: datetime, seen: Visibility | None = None) -> Discovery:
        """Neighbor tables as of a run.

        Args:
            at: When the run happened.
            seen: What live state says about who is up then, if the caller
                has it, so the source need not ask again.

        Returns:
            The tables of the devices that answered.
        """
        ...


class Port(_Record):
    """A device's port, as documented or as seen."""

    device: str
    """A device in the topology, or the name an unknown neighbor gives."""
    interface: str


class Fix(_Record):
    """A change to the documentation that makes it say what discovery sees,
    or for ``expect``, that records a finding as expected."""

    kind: FixKind
    summary: str
    before: Link | None = None
    """The documented link it moves or retires."""
    after: Link | None = None
    """The link as it would then be documented: moved, or added."""


class Finding(_Record):
    """One place where the documentation and the network disagree."""

    id: str
    kind: FindingKind
    title: str
    detail: str
    link: str | None = None
    """The documented link it is about, if any."""
    documented: list[Port] = []
    seen: list[Port] = []
    """The ends as discovery saw them."""
    devices: list[str]
    """Devices in the topology it involves, the first the one to look at."""
    first_seen: datetime | None = None
    """The first run of the unbroken stretch that shows it; None if that
    reaches back as far as the history goes."""
    last_seen: datetime | None = None
    """The last run of that stretch; None if it is the latest run."""
    fix: Fix | None = None
    """How to make the documentation match, where it can be made to."""
    covered_by: str | None = None
    """For a finding set aside because another is expected: that one's id.
    A switch expected to report no neighbors covers its links not seen
    while it does not answer."""


class SeenLink(_Record):
    """A cable discovery sees that the documentation does not have as it is:
    one no one documented, one to a device not in the topology, or the real
    cable of a documented link seen on another port or device."""

    id: str
    a: Port
    """A device in the topology."""
    b: Port
    known: bool
    """``b`` is a device in the topology too."""
    finding: str
    """The finding it belongs to."""
    platform: str | None = None


class Comparison(_Record):
    """Discovery against the documented topology, as of one run."""

    source: str
    at: datetime
    polled: list[str]
    """Devices that answered."""
    links: dict[str, LinkCheck]
    """Every documented link not confirmed, by id; the rest are confirmed."""
    confirmed: int
    findings: list[Finding]
    """Most misleading first: wrong neighbors and ports, then links not
    seen, undocumented links, unknown neighbors, and silent devices."""
    seen: list[SeenLink]
    """Every cable seen that is not documented as it is, for drawing."""
    gone: list[Finding] = []
    """Findings of earlier runs not in this one, most recently seen first."""
    expected: list[Finding] = []
    """Findings of this run marked expected, left out of ``findings``."""
    history_from: datetime | None = None
    """The earliest run history has, unbroken back from this one."""


@functools.cache
def _key(interface: str) -> str:
    """A port name in one form, however a device spells it."""
    return short_interface(interface.replace(" ", "")).lower()


def _ports(link: Link) -> tuple[tuple[str, str], tuple[str, str]]:
    return (link.a.device, _key(link.a.interface)), (
        link.b.device,
        _key(link.b.interface),
    )


def _name(device: str, interface: str) -> str:
    return f"{device} {short_interface(interface)}"


def _long(interface: str) -> str:
    """A port name spelled out, as documentation has it: ``Te1/0/1`` as
    ``TenGigabitEthernet1/0/1``."""
    for long, short in ABBREVIATIONS:
        if interface.startswith(short) and interface[len(short) :][:1].isdigit():
            return long + interface[len(short) :]
    return interface


# Speeds by port type, fastest first, for documenting a cable discovery found.
_SPEEDS = [
    ("HundredGigE", 100_000),
    ("FortyGigabitEthernet", 40_000),
    ("TwentyFiveGigE", 25_000),
    ("TenGigabitEthernet", 10_000),
    ("GigabitEthernet", 1_000),
    ("FastEthernet", 100),
]


def _speed(interface: str) -> int:
    """A port's speed, in Mbps, from its type; 1 Gbps if its name does not say."""
    return next((mbps for name, mbps in _SPEEDS if interface.startswith(name)), 1_000)


class _Seen:
    """One adjacency discovery saw, from either or both ends."""

    def __init__(
        self, ends: tuple[Port, Port], known: bool, platform: str | None
    ) -> None:
        self.ends = ends
        self.known = known
        """Both ends are devices in the topology."""
        self.platform = platform


def _adjacencies(topology: Topology, discovery: Discovery) -> list[_Seen]:
    """Every distinct adjacency in the tables, merging what both ends report."""
    names = {d.name.lower(): d.name for d in topology.devices}

    def resolve(remote: str) -> str | None:
        lowered = remote.lower()
        return names.get(lowered) or names.get(lowered.split(".")[0])

    found: dict[frozenset[tuple[str, str]], _Seen] = {}
    for table in discovery.tables:
        for n in table.neighbors:
            remote = resolve(n.remote)
            far = remote or n.remote
            key = frozenset(
                {(table.device, _key(n.interface)), (far, _key(n.remote_port))}
            )
            # Most cables are reported from both ends: keep the first report.
            if key not in found:
                local = Port(device=table.device, interface=n.interface)
                other = Port(device=far, interface=n.remote_port)
                found[key] = _Seen((local, other), remote is not None, n.platform)
    # In a fixed order, so the same tables always give the same findings.
    return sorted(found.values(), key=lambda s: (s.ends[0].device, s.ends[0].interface))


def compare(
    topology: Topology, discovery: Discovery, state: Visibility | None = None
) -> Comparison:
    """Compare neighbor tables with the documented links.

    Args:
        topology: What is documented.
        discovery: What devices report.
        state: Live state as of the run, to tell links that are down (not a
            finding) from links that are missing; None if there is none.

    Returns:
        Each documented link's check and every finding.

    Raises:
        None
    """
    documented: dict[tuple[str, str], Link] = {}
    for link in topology.links:
        for port in _ports(link):
            documented[port] = link
    polled = {t.device for t in discovery.tables}
    down = _down_links(topology, state) if state else set()
    # Answering, with links that are up, yet seeing nothing at all.
    silent = {
        t.device
        for t in discovery.tables
        if not t.neighbors
        and any(
            t.device in (ln.a.device, ln.b.device) and ln.id not in down
            for ln in topology.links
        )
    }
    known = {d.name for d in topology.devices}
    site = {d.name: d.site for d in topology.devices}
    # Ports as their own devices name them, for documenting them.
    own = {
        (t.device, _key(n.interface)): n.interface
        for t in discovery.tables
        for n in t.neighbors
    }

    def spelled(port: Port) -> str:
        return own.get((port.device, _key(port.interface))) or _long(port.interface)

    checks: dict[str, LinkCheck] = {}
    findings: dict[str, Finding] = {}
    seen_links: list[SeenLink] = []

    def drawn(seen: _Seen, finding: str) -> None:
        u, v = seen.ends
        seen_links.append(
            SeenLink(
                id=f"seen:{u.device}:{u.interface}--{v.device}:{v.interface}",
                a=u,
                b=v,
                known=seen.known,
                finding=finding,
                platform=None if seen.known else seen.platform,
            )
        )

    def other_end(link: Link, device: str, interface: str) -> Port:
        a = (link.a.device, _key(link.a.interface)) == (device, _key(interface))
        end = link.b if a else link.a
        return Port(device=end.device, interface=end.interface)

    def contradicted(
        link: Link, here: Port, there: Port, seen_platform: str | None
    ) -> None:
        """A documented link whose port here is seen connected elsewhere."""
        if link.id in findings:
            return
        checks[link.id] = "mismatch"
        expected = other_end(link, here.device, here.interface)
        same = expected.device == there.device
        where = _name(here.device, here.interface)
        if same:
            kind: FindingKind = "wrong-port"
            title = f"{here.device} – {there.device} on another port"
            detail = (
                f"Documented at {_name(expected.device, expected.interface)}, "
                f"seen at {short_interface(there.interface)}"
            )
        else:
            kind = "wrong-neighbor"
            title = f"Another device on {where}"
            unknown = there.device not in known
            detail = (
                f"Documented: {_name(expected.device, expected.interface)}; seen: "
                f"{_name(there.device, there.interface)}"
                + (
                    f" ({seen_platform}, not in the topology)"
                    if unknown and seen_platform
                    else ""
                )
                + (" (not in the topology)" if unknown and not seen_platform else "")
            )
        involved = [here.device, expected.device]
        if there.device in known:
            involved.append(there.device)
        findings[link.id] = Finding(
            id=f"{kind}:{link.id}",
            kind=kind,
            title=title,
            detail=detail,
            link=link.id,
            documented=[here, expected],
            seen=[here, there],
            devices=list(dict.fromkeys(involved)),
            fix=moved(link, expected, there),
        )

    def moved(link: Link, end: Port, there: Port) -> Fix | None:
        """Move a link's end to where its cable is seen, unless the port seen
        is not in the topology or another link is documented on it."""
        if there.device not in known or (there.device, _key(there.interface)) in (
            documented
        ):
            return None
        a = (link.a.device, link.a.interface) == (end.device, end.interface)
        old = link.a if a else link.b
        new = Endpoint(
            device=there.device,
            interface=spelled(there),
            lag=old.lag if old.device == there.device else None,
        )
        to = (
            short_interface(new.interface)
            if new.device == old.device
            else _name(new.device, new.interface)
        )
        return Fix(
            kind="move",
            summary=f"Move the end at {_name(old.device, old.interface)} to {to}",
            before=link,
            after=_with_end(link, a, new),
        )

    for seen in _adjacencies(topology, discovery):
        u, v = seen.ends
        on_u = documented.get((u.device, _key(u.interface)))
        on_v = documented.get((v.device, _key(v.interface))) if seen.known else None
        if on_u is not None and on_u is on_v:
            checks.setdefault(on_u.id, "confirmed")
            continue
        if on_u is not None:
            contradicted(on_u, u, v, seen.platform)
            drawn(seen, findings[on_u.id].id)
        if on_v is not None:
            contradicted(on_v, v, u, seen.platform)
            if on_u is None:
                drawn(seen, findings[on_v.id].id)
        if on_u is None and on_v is None:
            between = f"{_name(u.device, u.interface)} – {_name(v.device, v.interface)}"
            if seen.known:
                ends = sorted(f"{e.device}:{e.interface}" for e in (u, v))
                found = f"undocumented:{'--'.join(ends)}"
                drawn(seen, found)
                a = Endpoint(device=u.device, interface=spelled(u))
                b = Endpoint(device=v.device, interface=spelled(v))
                added = Link(
                    a=a,
                    b=b,
                    speed_mbps=min(_speed(a.interface), _speed(b.interface)),
                    kind="lan" if site[u.device] == site[v.device] else "wan",
                )
                findings[found] = Finding(
                    id=found,
                    kind="undocumented",
                    title=f"Undocumented link {u.device} – {v.device}",
                    detail=between,
                    seen=[u, v],
                    devices=[u.device, v.device],
                    fix=Fix(kind="add", summary=f"Add the link {between}", after=added),
                )
            else:
                found = f"unknown-device:{u.device}:{u.interface}"
                drawn(seen, found)
                findings[found] = Finding(
                    id=found,
                    kind="unknown-device",
                    title=f"Unknown neighbor {v.device} on {u.device}",
                    detail=between
                    + (f" · {seen.platform}" if seen.platform else "")
                    + " · not in the topology",
                    seen=[u, v],
                    devices=[u.device],
                )

    for link in topology.links:
        if link.id in checks:
            continue
        ends = [link.a.device, link.b.device]
        if not any(d in polled for d in ends):
            checks[link.id] = "unchecked"
        elif link.id in down:
            checks[link.id] = "down"
        else:
            checks[link.id] = "not-seen"
            # A silent device explains its own links: one finding for it, not one each.
            if not any(d in silent for d in ends):
                findings[link.id] = _not_seen(link, polled)
    for device in sorted(silent, key=natural):
        count = sum(device in (ln.a.device, ln.b.device) for ln in topology.links)
        findings[f"silent:{device}"] = Finding(
            id=SILENT + device,
            kind="no-neighbors",
            title=f"{device} reports no neighbors",
            detail=f"None of its {count} documented links is seen from either end: "
            "LLDP and CDP may be off on it",
            devices=[device],
        )
    ordered = sorted(
        findings.values(), key=lambda f: (KINDS.index(f.kind), natural(f.title))
    )
    return Comparison(
        source=discovery.source,
        at=discovery.at,
        polled=sorted(polled, key=natural),
        links={k: v for k, v in sorted(checks.items()) if v != "confirmed"},
        confirmed=sum(v == "confirmed" for v in checks.values()),
        findings=ordered,
        seen=seen_links,
    )


def expecting(
    comparison: Comparison, expected: Set[str], topology: Topology
) -> Comparison:
    """Set aside the findings people have marked expected.

    Args:
        comparison: A run's comparison.
        expected: Ids of the findings marked expected.
        topology: What is documented, for the links of a device expected
            to report no neighbors.

    Returns:
        The comparison with those findings moved from ``findings`` to
        ``expected``, their cables not drawn, those gone left out, and the
        links not seen that they explain checked ``expected``. A device
        expected to report no neighbors explains its links even while it
        does not answer, when each is a finding of its own.

    Raises:
        None
    """
    silent = {e.removeprefix(SILENT) for e in expected if e.startswith(SILENT)}

    def cover(f: Finding) -> str | None:
        """The expected finding that sets this one aside, if any."""
        if f.id in expected:
            return f.id
        quiet = sorted(set(f.devices) & silent) if f.kind == "not-seen" else []
        return SILENT + quiet[0] if quiet else None

    kept = [
        f if cover(f) == f.id else f.model_copy(update={"covered_by": cover(f)})
        for f in comparison.findings
        if cover(f)
    ]
    explained = {f.link for f in kept if f.link}
    explained |= {ln.id for ln in topology.links if {ln.a.device, ln.b.device} & silent}
    links: dict[str, LinkCheck] = {
        k: "expected" if k in explained and v == "not-seen" else v
        for k, v in comparison.links.items()
    }
    return comparison.model_copy(
        update={
            "findings": [f for f in comparison.findings if not cover(f)],
            "expected": kept,
            "seen": [s for s in comparison.seen if s.finding not in expected],
            "gone": [f for f in comparison.gone if not cover(f)],
            "links": links,
        }
    )


def _not_seen(link: Link, polled: set[str]) -> Finding:
    asking = [d for d in (link.a.device, link.b.device) if d in polled]
    who = (
        "neither end reports it"
        if len(asking) == 2
        else f"{asking[0]} does not report it"
    )
    between = (
        f"{_name(link.a.device, link.a.interface)} – "
        f"{_name(link.b.device, link.b.interface)}"
    )
    return Finding(
        id=f"not-seen:{link.id}",
        kind="not-seen",
        title=f"{link.a.device} – {link.b.device} not seen",
        detail=f"Documented {between}; {who}",
        link=link.id,
        documented=[
            Port(device=link.a.device, interface=link.a.interface),
            Port(device=link.b.device, interface=link.b.interface),
        ],
        devices=[link.a.device, link.b.device],
        fix=Fix(kind="retire", summary=f"Retire the link {between}", before=link),
    )


def _with_end(link: Link, a: bool, end: Endpoint) -> Link:
    """A link with another A end, or B end, and its id worked out afresh
    (a copy would keep the old one)."""
    return Link(
        a=end if a else link.a,
        b=link.b if a else end,
        speed_mbps=link.speed_mbps,
        kind=link.kind,
        circuit=link.circuit,
    )


def _down_links(topology: Topology, state: Visibility) -> set[str]:
    """Links live state shows down, or that end at a device that is down."""
    return {
        ln.id
        for ln in topology.links
        if {(ln.a.device, ln.a.interface), (ln.b.device, ln.b.interface)}
        & state.down_ports
        or {ln.a.device, ln.b.device} & state.down_devices
    }


DOMAIN = ".net.example"


class SimulatedDiscovery:
    """Neighbor tables from the simulated network as it is really cabled.

    Each device the state source watches and finds up answers, every 15
    minutes, reporting each real cable whose ports are up, except where a
    media converter hides the far end, and except for switches with LLDP
    and CDP off, which neither report nor are seen. Some devices report
    over CDP with their platform and full port names, others over LLDP with
    a domain and short port names. A cable unplugged at the time is not seen.
    """

    interval = timedelta(minutes=15)
    source = "simulated"

    def __init__(
        self, topology: Topology, cabling: Cabling, state: StateSource
    ) -> None:
        """Discover a network.

        Args:
            topology: The documented network.
            cabling: How it is really cabled.
            state: Live state, for who answers and which ports are up.

        Raises:
            None
        """
        self.topology = topology
        self.cabling = cabling
        self.state = state

    def discover(self, at: datetime, seen: Visibility | None = None) -> Discovery:
        """Neighbor tables as of a run.

        Args:
            at: When the run happened.
            seen: Who is up then, or None to ask the state source.

        Returns:
            A table for each watched device that is up.

        Raises:
            None
        """
        seen = seen or visibility(self.state, at)
        up, down, down_ports = seen.up, seen.down_devices, seen.down_ports
        devices = {d.name: d for d in self.topology.devices}
        rows: dict[str, list[Neighbor]] = {d: [] for d in up}
        deaf = self.cabling.silent
        for cable in self.cabling.cables:
            if cable.hidden:
                continue
            if not self.cabling.in_place(cable.link.id, at):
                continue
            for here, there in ((cable.a, cable.b), (cable.b, cable.a)):
                if here.device not in rows or {here.device, there.device} & deaf:
                    continue
                if (
                    there.device in down
                    or {
                        (here.device, here.interface),
                        (there.device, there.interface),
                    }
                    & down_ports
                ):
                    continue
                rows[here.device].append(
                    _row(
                        here.interface, there, devices.get(there.device), cable.platform
                    )
                )
        return Discovery(
            source=self.source,
            at=at,
            tables=[
                NeighborTable(device=d, neighbors=n)
                for d, n in sorted(rows.items(), key=lambda kv: natural(kv[0]))
            ],
        )


def _row(
    port: str, there: Endpoint, remote: Device | None, platform: str | None
) -> Neighbor:
    """A row as a device would report it: CDP from some, LLDP from others."""
    if remote is None:
        # Not in the topology: a lab switch, reporting itself over CDP.
        return Neighbor(
            interface=port,
            remote=there.device,
            remote_port=there.interface,
            protocol="cdp",
            platform=platform,
        )
    if _hash(remote.name) % 3 == 0:
        return Neighbor(
            interface=port,
            remote=remote.name + DOMAIN,
            remote_port=short_interface(there.interface),
            protocol="lldp",
        )
    return Neighbor(
        interface=port,
        remote=remote.name,
        remote_port=there.interface,
        protocol="cdp",
        platform=remote.platform,
    )


@functools.cache
def _hash(text: str) -> int:
    """A small hash that is the same in every process, unlike ``hash``."""
    return sum((i + 1) * ord(c) for i, c in enumerate(text))
