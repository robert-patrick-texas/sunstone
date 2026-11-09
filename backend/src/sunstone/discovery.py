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

Circuits, and links to someone else's device, are compared by what each
says LLDP and CDP show on our port (``model.shows``): the far end, the
provider's equipment, or nothing. Where they show otherwise, or a circuit
into a transport does not say, the finding offers to document what is seen.
One of our own devices seen across a link whose roles at the edge are not
transit means the boundary is not where it is documented, the most
misleading finding of all. A phone or a host on a port no link documents is
an endpoint on an access port, counted but not a finding; a switch or
router there is one.

Only what discovery can check counts. A device that does not answer (not
polled, down, or unreachable) reports nothing, though its neighbors still
see it; and a link that is down is not seen, whatever is documented, so
neither is a finding. A real discovery source would be a collector reading
LLDP-MIB and CDP-MIB, or an NMS's neighbor tables; the only one so far is
simulated, reporting the simulated network as really cabled (``cabling.py``).
"""

import functools
import re
from collections.abc import Iterable, Mapping, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from sunstone.cabling import NTU_PLATFORM, Beyond, Cabling, Shown
from sunstone.live import NetworkState, StateSource
from sunstone.model import (
    Device,
    Endpoint,
    ExternalEnd,
    Link,
    Neighbors,
    Roles,
    Topology,
    Transport,
    TransportEnd,
    Tunnel,
    TunnelEnd,
    TunnelPeer,
    device_b,
    device_ends,
    end_name,
    link_roles,
    ports,
    sees_across,
    shows,
)
from sunstone.problems import ABBREVIATIONS, link_name, natural, short_interface

LinkCheck = Literal[
    "confirmed",
    "provider",
    "nothing",
    "mismatch",
    "not-seen",
    "expected",
    "down",
    "unchecked",
    "unstated",
    "differs",
]
"""``provider``: the provider's equipment seen, and ``nothing`` nothing, as
documented; ``unstated``: a link beyond our devices that does not say what
it shows, with nothing seen on it; ``differs``: one showing something other
than it says, or saying nothing."""
TunnelCheck = Literal[
    "confirmed", "mismatch", "quiet", "not-seen", "not-inside", "down", "unchecked"
]
"""A tunnel's check: ``confirmed`` over CDP (for MACsec, inside it, on its
port), ``mismatch`` where CDP shows another far end, ``quiet`` where CDP is
not seen over it, which is never a finding, ``not-seen`` for MACsec that
LLDP and CDP run inside, up, yet its far end not seen, ``not-inside`` for
MACsec they run beside or not at all, which discovery cannot vouch for,
``down``, and ``unchecked`` where neither end answers."""
FindingKind = Literal[
    "boundary",
    "leaf",
    "wrong-neighbor",
    "wrong-port",
    "not-seen",
    "undocumented",
    "shows",
    "unknown-device",
    "no-neighbors",
]
FixKind = Literal["move", "add", "retire", "document", "expect"]
Capability = Literal["router", "switch", "access-point", "phone", "host"]
# What an endpoint says it is: anything else is network equipment.
ENDPOINT: frozenset[Capability] = frozenset({"phone", "host"})
# A device that reports no neighbors: its finding's id, before its name.
SILENT = "no-neighbors:"
KINDS: list[FindingKind] = [
    "boundary",
    "leaf",
    "wrong-neighbor",
    "wrong-port",
    "not-seen",
    "undocumented",
    "shows",
    "unknown-device",
    "no-neighbors",
]
# What a circuit or link beyond our devices shows, in a sentence.
SHOWING: dict[Neighbors, str] = {
    "far-end": "the far end",
    "provider": "the provider's equipment",
    "nothing": "nothing",
}
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
    """The name the neighbor gives itself, often with a domain (over CDP
    from NX-OS, with the chassis serial after it); over LLDP from one that
    sends no system name, its chassis ID."""
    remote_port: str
    protocol: Literal["lldp", "cdp"]
    platform: str | None = None
    capabilities: list[Capability] = []
    """What the neighbor says it is, as LLDP and CDP report it."""
    mgmt_address: str | None = None
    """The management address it gives, if any."""
    chassis_id: str | None = None
    """Its LLDP chassis ID, usually a MAC address."""


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
    tunnels_down: frozenset[str] = frozenset()
    """Tunnels down, by id."""

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
            tunnels_down=frozenset(
                t.tunnel for t in state.tunnels if t.status == "down"
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
    """The documented link it moves, retires, or documents."""
    after: Link | None = None
    """The link as it would then be documented: moved, added, or saying
    what it shows (``document``)."""


class Finding(_Record):
    """One place where the documentation and the network disagree."""

    id: str
    kind: FindingKind
    title: str
    detail: str
    link: str | None = None
    """The documented link it is about, if any."""
    tunnel: str | None = None
    """The documented tunnel it is about, if any."""
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
    one no one documented, one to a device not in the topology, the real
    cable of a documented link seen on another port or device, or what a
    circuit shows other than as documented."""

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
    tunnels: dict[str, TunnelCheck] = {}
    """Every point-to-point tunnel between our devices, and MACsec, by name."""
    findings: list[Finding]
    """Most misleading first: our own devices across the boundary, wrong
    neighbors and ports, then links not seen, undocumented links, circuits
    showing other than documented, unknown neighbors, and silent devices."""
    seen: list[SeenLink]
    """Every cable seen that is not documented as it is, for drawing."""
    endpoints: dict[str, int] = {}
    """Devices with endpoints (phones, hosts) seen on ports no link
    documents, and how many: access, not findings."""
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


def port_key(interface: str) -> str:
    """A port's interface in one form, however a device or person writes it.

    Args:
        interface: The interface: "GigabitEthernet1/0/1", "Gi1/0/1".

    Returns:
        The short form, without case or spaces: "gi1/0/1".

    Raises:
        None
    """
    return _key(interface)


@dataclass(frozen=True)
class NeighborRules:
    """What discovery takes from overrides (``overrides.py``)."""

    names: Mapping[str, str] = field(default_factory=dict)
    """Other names devices go by, their aliases and new names, to the
    device's own."""
    one_device: Mapping[tuple[str, str], str] = field(default_factory=dict)
    """Ports, by device and port key, whose rows are all one neighbor, to
    the name it goes by."""
    ignored: Mapping[tuple[str, str], frozenset[str]] = field(default_factory=dict)
    """Ports, by device and port key, to the neighbors whose rows there
    are dropped."""


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
    """One neighbor discovery saw on a port, over CDP, LLDP, or both, from
    either or both ends."""

    def __init__(
        self,
        ends: tuple[Port, Port],
        known: bool,
        platform: str | None,
        capabilities: list[Capability],
        protocols: frozenset[str] = frozenset(),
    ) -> None:
        self.ends = ends
        self.known = known
        """Both ends are devices in the topology."""
        self.platform = platform
        self.capabilities = capabilities
        self.protocols = protocols

    @property
    def endpoint(self) -> bool:
        """The far end says it is a phone or a host, and nothing else."""
        return bool(self.capabilities) and set(self.capabilities) <= ENDPOINT


# The chassis serial NX-OS puts after its name over CDP: dal-core-01(FDO2112X).
_SERIAL = re.compile(r"\([^)]*\)$")


def _plain(remote: str) -> str:
    """A neighbor's name in one form, however the protocol gives it: without
    case, domain, or the serial NX-OS adds over CDP."""
    return _SERIAL.sub("", remote.strip()).lower().split(".")[0]


def _named(row: Neighbor) -> bool:
    """Whether a row names its neighbor, rather than giving only the LLDP
    chassis ID of one that sends no system name."""
    return bool(row.remote) and row.remote != row.chassis_id


def _adjacencies(
    topology: Topology,
    discovery: Discovery,
    apart: Set[tuple[str, str]],
    rules: NeighborRules,
) -> list[_Seen]:
    """Every distinct neighbor in the tables, one per device on each port,
    merging what both ends report.

    CDP and LLDP describe one device differently: a short name over one and
    the name with its domain over the other, or a name with the chassis
    serial after it. Rows on one port that name the same device, or give
    its management address, are one neighbor. A row that names no one (an
    LLDP chassis ID alone) beside one device seen over the other protocol is
    that device too, unless the port is documented to show two (``apart``),
    as an NTU over LLDP and our far end over CDP are.

    Overrides can say more (``rules``): a device's other names are its own;
    every row on some ports is one neighbor, under the name given; and the
    rows naming some neighbors on a port are dropped, with the rows that
    neighbor gives about the port, if it answers.

    Args:
        topology: What is documented.
        discovery: What devices report.
        apart: Ports, by device and port key, documented to show more than
            one kind of neighbor.
        rules: What overrides say about names and ports.

    Returns:
        The neighbors, in a fixed order.
    """
    names = {d.name.lower(): d.name for d in topology.devices}
    for other, device in rules.names.items():
        if device.lower() in names:
            names.setdefault(other.lower(), device)
            names.setdefault(_plain(other), device)
    by_address = {d.mgmt_ip: d.name for d in topology.devices if d.mgmt_ip}

    def named(name: str) -> str | None:
        return names.get(name.lower()) or names.get(_plain(name))

    def resolve(row: Neighbor) -> str | None:
        if _named(row):
            found = named(row.remote)
            if found:
                return found
        return by_address.get(row.mgmt_address or "")

    # The rows to drop: on a port, those naming a neighbor ignored there;
    # and that neighbor's own about the port, if it is one of ours.
    dropped = {
        (port, named(n) or _plain(n)) for port, ns in rules.ignored.items() for n in ns
    }
    ours = set(names.values())
    facing = {(far, port) for port, far in dropped if far in ours}

    def kept(device: str, n: Neighbor, remote: str | None) -> bool:
        here = (device, _key(n.interface))
        if (here, remote or _plain(n.remote)) in dropped:
            return False
        return remote is None or (device, (remote, _key(n.remote_port))) not in facing

    found: dict[frozenset[tuple[str, str]], _Seen] = {}
    for table in discovery.tables:
        on_port: dict[str, list[tuple[Neighbor, str | None]]] = {}
        for n in table.neighbors:
            remote = resolve(n)
            if kept(table.device, n, remote):
                on_port.setdefault(_key(n.interface), []).append((n, remote))
        for port, rows in on_port.items():
            one = rules.one_device.get((table.device, port))
            groups = (
                [rows]
                if len(rows) == 1 or one
                else _one_per_device(rows, (table.device, port) in apart)
            )
            for group in groups:
                first = group[0][0]
                remote = next((r for _, r in group if r), None)
                if one:
                    # One neighbor, by the name given; its port from its own
                    # row, if it is one of ours.
                    remote = named(one)
                    first = next((n for n, r in group if remote and r == remote), first)
                far = remote or one or first.remote
                key = frozenset({(table.device, port), (far, _key(first.remote_port))})
                # Most cables are reported from both ends: keep the first report.
                if key in found:
                    continue
                said = {c for n, _ in group for c in n.capabilities}
                found[key] = _Seen(
                    (
                        Port(device=table.device, interface=first.interface),
                        Port(device=far, interface=first.remote_port),
                    ),
                    remote is not None,
                    next((n.platform for n, _ in group if n.platform), None),
                    [c for c in CAPABILITIES_ALL if c in said],
                    frozenset(n.protocol for n, _ in group),
                )
    # In a fixed order, so the same tables always give the same findings.
    return sorted(found.values(), key=lambda s: (s.ends[0].device, s.ends[0].interface))


def _one_per_device(
    rows: list[tuple[Neighbor, str | None]], apart: bool
) -> list[list[tuple[Neighbor, str | None]]]:
    """A port's rows, one group per device they describe.

    Args:
        rows: The rows on one port, each with the device in the topology it
            names, if any.
        apart: The port is documented to show more than one kind of
            neighbor, so a row that names no one is not taken for another.

    Returns:
        The groups, CDP's row first in each: its port is always the
        interface's name.
    """
    rows = sorted(rows, key=lambda r: r[0].protocol != "cdp")
    devices: dict[str, list[tuple[Neighbor, str | None]]] = {}
    unnamed = []
    for n, remote in rows:
        who = remote or (_plain(n.remote) if _named(n) else None)
        if who is None:
            unnamed.append((n, remote))
        else:
            devices.setdefault(who, []).append((n, remote))
    for n, remote in unnamed:
        # One device unless they differ: beside the one device seen over
        # the other protocol, a row that names no one is that device.
        only = next(iter(devices.values())) if len(devices) == 1 else []
        if only and not apart and all(r.protocol != n.protocol for r, _ in only):
            only.append((n, remote))
        else:
            devices[f"?{n.remote}"] = [(n, remote)]
    return list(devices.values())


# What a port shows, in the order a sentence gives them.
_SAID: tuple[Neighbors, ...] = ("provider", "far-end", "nothing")


def _showing(kinds: Iterable[Neighbors]) -> str:
    """What a port shows, in words: "the provider's equipment and the far end"."""
    said = [SHOWING[k] for k in _SAID if k in set(kinds)] or [SHOWING["nothing"]]
    return " and ".join(said)


def compare(
    topology: Topology,
    discovery: Discovery,
    state: Visibility | None = None,
    rules: NeighborRules | None = None,
) -> Comparison:
    """Compare neighbor tables with the documented links and tunnels.

    Args:
        topology: What is documented.
        discovery: What devices report.
        state: Live state as of the run, to tell links and tunnels that are
            down (not a finding) from those that are missing; None if there
            is none.
        rules: What overrides say about devices' names and some ports; None
            for nothing.

    Returns:
        Each documented link's and tunnel's check, and every finding.

    Raises:
        None
    """
    documented: dict[tuple[str, str], Link] = {}
    for link in topology.links:
        for end in device_ends(link):
            documented[(end.device, _key(end.interface))] = link
    externals = {e.name: e for e in topology.externals}
    transports = {t.name: t for t in topology.transports}
    polled = {t.device for t in discovery.tables}
    down = _down_links(topology, state) if state else set()
    tunnels_down = state.tunnels_down if state else frozenset()
    # Answering, with links up that should show something, yet seeing nothing.
    silent = {
        t.device
        for t in discovery.tables
        if not t.neighbors
        and any(
            t.device in _devices(ln)
            and ln.id not in down
            and {"far-end", "provider"} & set(shows(ln))
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
    # MACsec on each port: the far ends it is to, by port key or external name.
    secured: dict[tuple[str, str], set[tuple[str, str] | str]] = {}
    # The far end of each point-to-point tunnel interface CDP may run over.
    tunnel_at: dict[tuple[str, str], tuple[Tunnel, TunnelEnd]] = {}
    for t in topology.tunnels:
        a, b = t.a, t.b
        here = (a.device, _key(a.interface))
        if t.kind == "macsec":
            if isinstance(b, TunnelEnd):
                there = (b.device, _key(b.interface))
                secured.setdefault(here, set()).add(there)
                secured.setdefault(there, set()).add(here)
            else:
                secured.setdefault(here, set()).add(b.external)
        elif isinstance(b, TunnelEnd):
            tunnel_at[here] = (t, b)
            tunnel_at[(b.device, _key(b.interface))] = (t, a)
    # Ports documented to show two kinds of neighbor: an NTU and the far end.
    apart = {
        (e.device, _key(e.interface))
        for ln in topology.links
        if len(set(shows(ln)) - {"nothing"}) > 1
        for e in device_ends(ln)
    }

    def spelled(port: Port) -> str:
        return own.get((port.device, _key(port.interface))) or _long(port.interface)

    checks: dict[str, LinkCheck] = {}
    tunnel_checks: dict[str, TunnelCheck] = {}
    findings: dict[str, Finding] = {}
    seen_links: list[SeenLink] = []
    endpoints: dict[str, int] = {}
    # What each circuit, or link beyond our devices, shows: each kind with
    # the first sighting of it.
    observed: dict[str, dict[Neighbors, tuple[Port, Port, str | None]]] = {}
    # Every pair of ports seen joined, for MACsec.
    joined: set[frozenset[tuple[str, str]]] = set()

    def observe(
        link: Link, kind: Neighbors, here: Port, there: Port, seen: _Seen
    ) -> None:
        sighting = (here, there, None if seen.known else seen.platform)
        observed.setdefault(link.id, {}).setdefault(kind, sighting)

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
        end = device_b(link) if a else link.a
        return Port(device=end.device, interface=end.interface)

    def contradicted(
        link: Link, here: Port, there: Port, seen_platform: str | None
    ) -> None:
        """A documented link between two devices whose port here is seen
        connected elsewhere."""
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
        old = link.a if a else device_b(link)
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

    def ours_beyond(link: Link, here: Port, there: Port) -> None:
        """One of our devices seen on our end of a link beyond our devices,
        other than across a layer-2 service as documented: across the
        boundary, unless the link is for transit or its roles are still to
        be documented, when it is only on the wrong port."""
        if link.id in findings:
            return
        checks[link.id] = "mismatch"
        roles = link_roles(link, externals)
        across = end_name(link.b)
        if roles.source != "tbd" and "transit" not in roles.edges:
            kind: FindingKind = "boundary"
            title = f"{here.device} sees {there.device} across {across}"
            detail = (
                f"{link_name(link)} is {_roles(roles)}, yet "
                f"{_name(here.device, here.interface)} sees our own "
                f"{_name(there.device, there.interface)} on the far side: the "
                "boundary is not where it is documented"
            )
        else:
            kind = "wrong-neighbor"
            title = f"Another device on {_name(here.device, here.interface)}"
            detail = (
                f"Documented: {link_name(link)} into {across}; seen: "
                f"{_name(there.device, there.interface)}"
            )
        findings[link.id] = Finding(
            id=f"{kind}:{link.id}",
            kind=kind,
            title=title,
            detail=detail,
            link=link.id,
            documented=[Port(device=here.device, interface=here.interface)],
            seen=[here, there],
            devices=[here.device, there.device],
        )

    def leaked(link: Link, other: Link, here: Port, there: Port) -> str:
        """Two leaves of an E-Tree that see each other, which its leaves
        cannot: one finding for the pair."""
        found = "leaf:" + "--".join(sorted([link.id, other.id]))
        checks[link.id] = checks[other.id] = "mismatch"
        if found not in findings:
            across = end_name(link.b)
            findings[found] = Finding(
                id=found,
                kind="leaf",
                title=f"{here.device} sees {there.device} across {across}",
                detail=(
                    f"{link_name(link)} and {link_name(other)} are both leaves of "
                    f"{across}, an E-Tree, whose leaves reach only its roots, yet "
                    f"{_name(here.device, here.interface)} sees "
                    f"{_name(there.device, there.interface)}"
                ),
                link=link.id,
                documented=[
                    Port(device=e.device, interface=e.interface)
                    for e in (link.a, other.a)
                ],
                seen=[here, there],
                devices=[here.device, there.device],
            )
        return found

    def showing(link: Link, now: tuple[Neighbors, ...]) -> None:
        """A circuit, or a link beyond our devices, showing other than it says."""
        if link.id in findings:
            return
        said = shows(link)
        name = link_name(link)
        what = _showing(now)
        got = observed.get(link.id, {})
        if got:
            sightings = [got[k] for k in _SAID if k in got]
            saw = " and ".join(
                _name(there.device, there.interface)
                + (f" ({platform})" if platform else "")
                for _, there, platform in sightings
            )
            here = sightings[0][0]
            saw = f"{_name(here.device, here.interface)} sees {saw}"
            seen = [p for here_, there, _ in sightings for p in (here_, there)]
        else:
            end = next(e for e in device_ends(link) if e.device in polled)
            here = Port(device=end.device, interface=end.interface)
            saw = f"{_name(here.device, here.interface)} sees nothing"
            seen = []
        detail = saw + (
            f"; documented as showing {_showing(said)}"
            if said
            else "; it does not say what it shows"
        )
        findings[link.id] = Finding(
            id=f"shows:{link.id}",
            kind="shows",
            title=f"{name} shows {what}",
            detail=detail,
            link=link.id,
            documented=[
                Port(device=e.device, interface=e.interface) for e in device_ends(link)
            ],
            seen=list(dict.fromkeys(seen)),
            devices=_devices(link),
            fix=Fix(
                kind="document",
                summary=f"Document that {name} shows {what}",
                before=link,
                after=link.model_copy(update={"neighbors": list(now)}),
            ),
        )

    def across(link: Link, there: Port, there_link: Link | None) -> bool:
        """Whether a device of ours seen on a link beyond our devices is one
        it is documented to reach as a neighbor: its MACsec far end, or a
        device on the same layer-2 service, on a circuit for transit."""
        here = [(e.device, _key(e.interface)) for e in device_ends(link)]
        far = (there.device, _key(there.interface))
        if any(far in secured.get(p, set()) for p in here):
            return True
        roles = link_roles(link, externals)
        return (
            there_link is not None
            and sees_across(link, there_link, transports)
            and (roles.source == "tbd" or "transit" in roles.edges)
        )

    def at_port(
        link: Link, here: Port, there: Port, seen: _Seen, there_link: Link | None
    ) -> str | None:
        """What is seen on our end of a documented link, other than its far
        end; the id of the finding it makes, or that the link has already."""
        b = link.b
        if not seen.known:
            if isinstance(b, Endpoint) and not _carrier(link):
                # Our own cable, or a cross-connect: another device on the port.
                contradicted(link, here, there, seen.platform)
            elif isinstance(b, ExternalEnd):
                said = shows(link)
                theirs: Neighbors = (
                    "provider"
                    if "provider" in said and "far-end" not in said
                    else "far-end"
                )
                observe(link, theirs, here, there, seen)
            else:
                # Beyond a carrier's circuit: the provider's equipment.
                observe(link, "provider", here, there, seen)
        elif across(link, there, there_link):
            observe(link, "far-end", here, there, seen)
        elif isinstance(b, Endpoint):
            contradicted(link, here, there, seen.platform)
        elif _leaves(link, there_link, transports):
            assert there_link is not None
            return leaked(link, there_link, here, there)
        else:
            ours_beyond(link, here, there)
        found = findings.get(link.id)
        return found.id if found else None

    def on_tunnel(seen: _Seen) -> bool:
        """A neighbor seen over a tunnel's own interface, as CDP shows one:
        checked against the tunnel's far end."""
        for here, there in (seen.ends, seen.ends[::-1]):
            at = tunnel_at.get((here.device, _key(here.interface)))
            if at is None:
                continue
            tunnel, far = at
            if (there.device, _key(there.interface)) == (
                far.device,
                _key(far.interface),
            ):
                tunnel_checks.setdefault(tunnel.name, "confirmed")
                return True
            tunnel_checks[tunnel.name] = "mismatch"
            found = f"tunnel:{tunnel.name}"
            if found in findings:
                return True
            same = there.device == far.device
            documented_at = _name(far.device, far.interface)
            findings[found] = Finding(
                id=found,
                kind="wrong-port" if same else "wrong-neighbor",
                title=(
                    f"{tunnel.name} on another tunnel interface"
                    if same
                    else f"{tunnel.name} sees {there.device}"
                ),
                detail=(
                    f"Documented to {documented_at}; "
                    f"{_name(here.device, here.interface)} sees "
                    f"{_name(there.device, there.interface)} over CDP"
                ),
                tunnel=tunnel.name,
                documented=[
                    Port(device=here.device, interface=here.interface),
                    Port(device=far.device, interface=far.interface),
                ],
                seen=[here, there],
                devices=list(
                    dict.fromkeys(
                        [here.device, far.device]
                        + ([there.device] if there.device in known else [])
                    )
                ),
            )
            return True
        return False

    for seen in _adjacencies(topology, discovery, apart, rules or NeighborRules()):
        u, v = seen.ends
        joined.add(
            frozenset({(u.device, _key(u.interface)), (v.device, _key(v.interface))})
        )
        if on_tunnel(seen):
            continue
        on_u = documented.get((u.device, _key(u.interface)))
        on_v = documented.get((v.device, _key(v.interface))) if seen.known else None
        if on_u is not None and on_u is on_v:
            if _beyond(on_u):
                observe(on_u, "far-end", u, v, seen)
            else:
                checks.setdefault(on_u.id, "confirmed")
            continue
        raised = [
            at_port(on, here, there, seen, other)
            for on, here, there, other in ((on_u, u, v, on_v), (on_v, v, u, on_u))
            if on is not None
        ]
        # Drawn once, with the first finding it belongs to.
        first = next((r for r in raised if r), None)
        if first:
            drawn(seen, first)
        if on_u is None and on_v is None:
            between = f"{_name(u.device, u.interface)} – {_name(v.device, v.interface)}"
            tunnel = any(_key(p.interface).startswith("tu") for p in (u, v))
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
                    title=(
                        f"Undocumented tunnel {u.device} – {v.device}"
                        if tunnel
                        else f"Undocumented link {u.device} – {v.device}"
                    ),
                    detail=between,
                    seen=[u, v],
                    devices=[u.device, v.device],
                    # A tunnel is not a cable to add: it needs its network,
                    # and what it rides.
                    fix=None
                    if tunnel
                    else Fix(
                        kind="add", summary=f"Add the link {between}", after=added
                    ),
                )
            elif seen.endpoint:
                # A phone or a host on a port no link documents: access.
                endpoints[u.device] = endpoints.get(u.device, 0) + 1
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

    def settle(link: Link) -> None:
        """A circuit's, or a link's beyond our devices, check from what was
        seen on it, against what it says it shows."""
        # With MACsec on its port or not: the link says what the port shows.
        said = set(shows(link))
        got = observed.get(link.id, {})
        ends = _devices(link)
        if got:
            kinds = tuple(k for k in _SAID if k in got)
            # Seen only from the far end, as when our device did not answer,
            # what only its own table shows (the NTU on its port) is not
            # missing: what was seen is checked, and the rest left.
            answered = any(d in polled for d in ends)
            if set(kinds) == said or (not answered and set(kinds) <= said):
                checks[link.id] = "confirmed" if "far-end" in kinds else "provider"
            else:
                checks[link.id] = "differs"
                showing(link, kinds)
        elif not any(d in polled for d in ends):
            checks[link.id] = "unchecked"
        elif link.id in down:
            checks[link.id] = "down"
        elif not said:
            checks[link.id] = "unstated"
        elif said == {"nothing"}:
            checks[link.id] = "nothing"
        else:
            checks[link.id] = "not-seen"
            # A silent device explains its own links: one finding for it, not one each.
            if not any(d in silent for d in ends):
                # Up yet showing nothing: its provider passes nothing.
                showing(link, ("nothing",))

    for link in topology.links:
        if link.id in findings or checks.get(link.id) == "mismatch":
            continue
        if _beyond(link):
            settle(link)
            continue
        if link.id in checks:
            continue
        ends = _devices(link)
        said = set(shows(link))
        if not any(d in polled for d in ends):
            checks[link.id] = "unchecked"
        elif link.id in down:
            checks[link.id] = "down"
        elif said == {"nothing"}:
            checks[link.id] = "nothing"
        else:
            checks[link.id] = "not-seen"
            # A silent device explains its own links: one finding for it, not one each.
            if any(d in silent for d in ends):
                continue
            findings[link.id] = _not_seen(link, polled)
    at_port_of = ports(topology)
    for t in topology.tunnels:
        b = t.b
        if t.name in tunnel_checks or (t.kind == "ip" and isinstance(b, TunnelPeer)):
            continue
        a = (t.a.device, _key(t.a.interface))
        if isinstance(b, TunnelEnd):
            ends = [t.a.device, b.device]
            seen_inside = frozenset({a, (b.device, _key(b.interface))}) in joined
        else:
            # To someone else's device: as its circuit shows it.
            ends = [t.a.device]
            under = at_port_of.get((t.a.device, t.a.interface))
            seen_inside = under is not None and "far-end" in observed.get(under.id, {})
        if t.kind == "macsec" and t.neighbors != "inside":
            # Its far end seen beside it proves the circuit, not the encryption.
            tunnel_checks[t.name] = "not-inside"
        elif t.kind == "macsec" and seen_inside:
            tunnel_checks[t.name] = "confirmed"
        elif not any(d in polled for d in ends):
            tunnel_checks[t.name] = "unchecked"
        elif t.name in tunnels_down or (state and set(ends) & state.down_devices):
            tunnel_checks[t.name] = "down"
        else:
            # A tunnel CDP does not run over is no finding; MACsec not seen
            # inside is its circuit's.
            tunnel_checks[t.name] = "not-seen" if t.kind == "macsec" else "quiet"
    for device in sorted(silent, key=natural):
        count = sum(device in _devices(ln) for ln in topology.links)
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
        tunnels=dict(sorted(tunnel_checks.items())),
        findings=ordered,
        seen=seen_links,
        endpoints=dict(sorted(endpoints.items(), key=lambda kv: natural(kv[0]))),
    )


def _leaves(
    link: Link, other: Link | None, transports: Mapping[str, Transport]
) -> bool:
    """Whether two circuits are both leaves of one E-Tree."""
    a, b = link.b, other.b if other is not None else None
    return (
        isinstance(a, TransportEnd)
        and isinstance(b, TransportEnd)
        and a.transport == b.transport
        and a.transport in transports
        and transports[a.transport].service == "e-tree"
        and "root" not in (a.role, b.role)
    )


def _beyond(link: Link) -> bool:
    """Whether a link is a carrier's circuit or goes beyond our devices,
    so is checked by what it says it shows, not as a cable."""
    return not isinstance(link.b, Endpoint) or _carrier(link)


def _devices(link: Link) -> list[str]:
    """The devices of ours at a link's ends."""
    return [e.device for e in device_ends(link)]


def _carrier(link: Link) -> bool:
    """Whether a carrier's service, not a cable, joins a link's ends."""
    return link.circuit is not None and link.circuit.type == "carrier"


def _roles(roles: Roles) -> str:
    """A link's roles at the edge, in words: "a peering edge", "an egress and
    ingress edge"."""
    names = list(roles.edges)
    said = " and ".join([", ".join(names[:-1]), names[-1]] if len(names) > 1 else names)
    return f"{'an' if said[:1] in 'aeiou' else 'a'} {said} edge"


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
    explained |= {ln.id for ln in topology.links if set(_devices(ln)) & silent}
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
    asking = [d for d in (link.a.device, device_b(link).device) if d in polled]
    who = (
        "neither end reports it"
        if len(asking) == 2
        else f"{asking[0]} does not report it"
    )
    between = (
        f"{_name(link.a.device, link.a.interface)} – "
        f"{_name(device_b(link).device, device_b(link).interface)}"
    )
    return Finding(
        id=f"not-seen:{link.id}",
        kind="not-seen",
        title=f"{link.a.device} – {device_b(link).device} not seen",
        detail=f"Documented {between}; {who}",
        link=link.id,
        documented=[
            Port(device=link.a.device, interface=link.a.interface),
            Port(device=device_b(link).device, interface=device_b(link).interface),
        ],
        devices=[link.a.device, device_b(link).device],
        fix=Fix(kind="retire", summary=f"Retire the link {between}", before=link),
    )


def _with_end(link: Link, a: bool, end: Endpoint) -> Link:
    """A link with another A end, or B end, and its id worked out afresh
    (a copy would keep the old one)."""
    return Link(
        a=end if a else link.a,
        b=device_b(link) if a else end,
        speed_mbps=link.speed_mbps,
        kind=link.kind,
        circuit=link.circuit,
    )


def _down_links(topology: Topology, state: Visibility) -> set[str]:
    """Links live state shows down, or that end at a device that is down."""
    return {
        ln.id
        for ln in topology.links
        if {(e.device, e.interface) for e in device_ends(ln)} & state.down_ports
        or set(_devices(ln)) & state.down_devices
    }


DOMAIN = ".net.example"


class SimulatedDiscovery:
    """Neighbor tables from the simulated network as it is really cabled.

    Each device the state source watches and finds up answers, every 15
    minutes, reporting each real cable whose ports are up, except where a
    media converter hides the far end, and except for switches with LLDP
    and CDP off, which neither report nor are seen. Across circuits and on
    links to someone else's device, it reports what ``Beyond`` says is
    really there: the provider's NTU, someone else's device, our router
    across a layer-2 path, or nothing; and the phones and printers on access
    ports. Some devices report over CDP with their platform and full port
    names, others over LLDP with a domain and short port names. A cable
    unplugged at the time is not seen.
    """

    interval = timedelta(minutes=15)
    source = "simulated"

    def __init__(
        self,
        topology: Topology,
        cabling: Cabling,
        state: StateSource,
        beyond: Beyond | None = None,
    ) -> None:
        """Discover a network.

        Args:
            topology: The documented network.
            cabling: How it is really cabled.
            state: Live state, for who answers and which ports are up.
            beyond: What circuits and links beyond our devices really show,
                and the endpoints; None for exactly as documented.

        Raises:
            None
        """
        self.topology = topology
        self.cabling = cabling
        self.state = state
        self.beyond = beyond or Beyond(topology)

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
        beyond = self.beyond

        def hears(device: str, interface: str) -> bool:
            return (
                device in rows
                and device not in deaf
                and (device, interface) not in down_ports
            )

        for cable in self.cabling.cables:
            if cable.hidden:
                continue
            if not self.cabling.in_place(cable.link.id, at):
                continue
            real = beyond.real.get(cable.link.id, ("far-end",))
            if "far-end" not in real:
                # A carrier's circuit that does not pass LLDP and CDP.
                continue
            # Where the provider's NTU shows, it takes LLDP's frames, as a
            # device inline does, passing CDP's on.
            inline = self.cabling.inline.get(
                frozenset(
                    {
                        (cable.a.device, cable.a.interface),
                        (cable.b.device, cable.b.interface),
                    }
                )
            )
            cdp_only = "provider" in real or inline is not None
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
                rows[here.device] += _rows(
                    here.interface,
                    there,
                    devices.get(there.device),
                    cable.platform,
                    cdp_only,
                    self.cabling.renamed.get(there.device),
                )
                if inline is not None:
                    name, platform = inline
                    rows[here.device].append(
                        Neighbor(
                            interface=here.interface,
                            remote=name,
                            remote_port="wan0" if here is cable.a else "lan0",
                            protocol="lldp",
                            platform=platform,
                            capabilities=["router"],
                            chassis_id=_mac(name),
                        )
                    )
        shown = [r for link in self.topology.links for r in beyond.rows(link)]
        for r in [*shown, *beyond.over_tunnels(), *beyond.endpoints]:
            if not hears(r.device, r.interface) or r.remote in down | deaf:
                continue
            if set(r.needs) & down_ports or r.tunnel in seen.tunnels_down:
                continue
            remote = devices.get(r.remote)
            if remote is not None:
                there = Endpoint(device=r.remote, interface=r.remote_port)
                rows[r.device] += _rows(r.interface, there, remote, None, r.cdp_only)
            else:
                rows[r.device].append(_beyond_row(r))
        return Discovery(
            source=self.source,
            at=at,
            tables=[
                NeighborTable(device=d, neighbors=n)
                for d, n in sorted(rows.items(), key=lambda kv: natural(kv[0]))
            ],
        )


# What each role says it is, over LLDP and CDP.
CAPABILITIES: dict[str, list[Capability]] = {
    "wan-edge": ["router"],
    "core": ["router", "switch"],
    "distribution": ["switch"],
    "access": ["switch"],
}


def _beyond_row(shown: Shown) -> Neighbor:
    """A row for something not in the topology: an endpoint over LLDP-MED,
    a provider's NTU over LLDP, anything else over CDP."""
    capabilities: list[Capability] = [
        c for c in CAPABILITIES_ALL if c in shown.capabilities
    ]
    lldp = set(capabilities) <= ENDPOINT or shown.platform == NTU_PLATFORM
    return Neighbor(
        interface=shown.interface,
        remote=shown.remote,
        remote_port=shown.remote_port,
        protocol="lldp" if lldp else "cdp",
        platform=shown.platform,
        capabilities=capabilities,
    )


CAPABILITIES_ALL: tuple[Capability, ...] = (
    "router",
    "switch",
    "access-point",
    "phone",
    "host",
)


def _rows(
    port: str,
    there: Endpoint,
    remote: Device | None,
    platform: str | None,
    cdp_only: bool = False,
    old_name: str | None = None,
) -> list[Neighbor]:
    """The rows a device would report for one neighbor: over CDP from some,
    over LLDP from others, and over both from NX-OS, which describes itself
    differently over each: its name with the chassis serial after it over
    CDP, and over LLDP its name alone, or, from about one in four, no
    system name at all, only its chassis ID and management address. A
    switch renamed sends both, its old name over LLDP.

    Args:
        port: The reporting device's port.
        there: The neighbor's device and port.
        remote: The neighbor, if it is in the topology.
        platform: The platform of a neighbor not in the topology.
        cdp_only: Only CDP reaches the port, as across an NTU or a tunnel.
        old_name: The hostname the neighbor's LLDP still sends, without a
            management address, if it was renamed.

    Returns:
        One row, or one over each protocol.
    """
    if remote is None:
        # Not in the topology: a lab switch, reporting itself over CDP.
        return [
            Neighbor(
                interface=port,
                remote=there.device,
                remote_port=there.interface,
                protocol="cdp",
                platform=platform,
                capabilities=["switch"],
            )
        ]
    capabilities = CAPABILITIES[remote.role]
    chassis = _mac(remote.name)
    cdp = Neighbor(
        interface=port,
        remote=remote.name,
        remote_port=there.interface,
        protocol="cdp",
        platform=remote.platform,
        capabilities=capabilities,
        mgmt_address=remote.mgmt_ip,
    )
    nexus = (remote.platform or "").startswith("N9K")
    if cdp_only:
        return [cdp]
    if old_name:
        return [
            cdp,
            Neighbor(
                interface=port,
                remote=old_name,
                remote_port=short_interface(there.interface),
                protocol="lldp",
                capabilities=capabilities,
                chassis_id=chassis,
            ),
        ]
    if nexus:
        serial = f"FDO{_hash(remote.name) % 100_000_000:08d}"
        unnamed = _hash(remote.name + "|lldp") % 4 == 0
        return [
            cdp.model_copy(update={"remote": f"{remote.name}({serial})"}),
            Neighbor(
                interface=port,
                remote=chassis if unnamed else remote.name,
                remote_port=short_interface(there.interface),
                protocol="lldp",
                capabilities=capabilities,
                mgmt_address=remote.mgmt_ip,
                chassis_id=chassis,
            ),
        ]
    if _hash(remote.name) % 3 == 0:
        return [
            Neighbor(
                interface=port,
                remote=remote.name + DOMAIN,
                remote_port=short_interface(there.interface),
                protocol="lldp",
                capabilities=capabilities,
                mgmt_address=remote.mgmt_ip,
                chassis_id=chassis,
            )
        ]
    return [cdp]


@functools.cache
def _mac(name: str) -> str:
    """A device's chassis MAC address, as LLDP gives it."""
    digits = f"00a6{_hash(name + '|mac') % 16**8:08x}"
    return ".".join(digits[i : i + 4] for i in range(0, 12, 4))


@functools.cache
def _hash(text: str) -> int:
    """A small hash that is the same in every process, unlike ``hash``."""
    return sum((i + 1) * ord(c) for i, c in enumerate(text))
