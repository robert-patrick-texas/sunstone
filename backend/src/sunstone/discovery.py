"""What devices say is connected to them, against what the topology documents.

Devices report their neighbors over LLDP or CDP: for each port, the name
the device at the other end gives itself, and the port it is on. Comparing
those tables with the documented links finds where the documentation and
the network disagree: a documented link no one sees, a cable on another
port or to another device than documented, a link no one documented, a
neighbor that is not in the topology at all, or a device that reports no
neighbors, as when LLDP and CDP are off on it.

Only what discovery can check counts. A device that does not answer (not
polled, down, or unreachable) reports nothing, though its neighbors still
see it; and a link that is down is not seen, whatever is documented, so
neither is a finding. A real discovery source would be a collector reading
LLDP-MIB and CDP-MIB, or an NMS's neighbor tables; the only one so far is
simulated, from the topology with a few disagreements of each kind seeded in.
"""

import random
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

from sunstone.live import NetworkState, StateSource
from sunstone.model import Device, Link, Topology
from sunstone.problems import natural, short_interface

LinkCheck = Literal["confirmed", "mismatch", "not-seen", "down", "unchecked"]
FindingKind = Literal[
    "wrong-neighbor",
    "wrong-port",
    "not-seen",
    "undocumented",
    "unknown-device",
    "no-neighbors",
]
KINDS: list[FindingKind] = [
    "wrong-neighbor",
    "wrong-port",
    "not-seen",
    "undocumented",
    "unknown-device",
    "no-neighbors",
]


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


class DiscoverySource(Protocol):
    """Where neighbor tables come from."""

    interval: timedelta
    """How often it runs."""

    def discover(self, at: datetime) -> Discovery:
        """Neighbor tables as of a run.

        Args:
            at: When the run happened.

        Returns:
            The tables of the devices that answered.
        """
        ...


class Port(_Record):
    """A device's port, as documented or as seen."""

    device: str
    """A device in the topology, or the name an unknown neighbor gives."""
    interface: str


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
            local = Port(device=table.device, interface=n.interface)
            other = Port(device=remote or n.remote, interface=n.remote_port)
            key = frozenset(
                {
                    (local.device, _key(local.interface)),
                    (other.device, _key(other.interface)),
                }
            )
            if key not in found:
                found[key] = _Seen((local, other), remote is not None, n.platform)
    return sorted(
        found.values(),
        key=lambda s: (natural(s.ends[0].device), natural(s.ends[0].interface)),
    )


def compare(
    topology: Topology, discovery: Discovery, state: NetworkState | None = None
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
    checks: dict[str, LinkCheck] = {}
    findings: dict[str, Finding] = {}

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
        if on_v is not None:
            contradicted(on_v, v, u, seen.platform)
        if on_u is None and on_v is None:
            between = f"{_name(u.device, u.interface)} – {_name(v.device, v.interface)}"
            if seen.known:
                ends = sorted(f"{e.device}:{e.interface}" for e in (u, v))
                found = f"undocumented:{'--'.join(ends)}"
                findings[found] = Finding(
                    id=found,
                    kind="undocumented",
                    title=f"Undocumented link {u.device} – {v.device}",
                    detail=between,
                    seen=[u, v],
                    devices=[u.device, v.device],
                )
            else:
                found = f"unknown-device:{u.device}:{u.interface}"
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
            id=f"no-neighbors:{device}",
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
    )


def _not_seen(link: Link, polled: set[str]) -> Finding:
    asking = [d for d in (link.a.device, link.b.device) if d in polled]
    who = (
        "neither end reports it"
        if len(asking) == 2
        else f"{asking[0]} does not report it"
    )
    return Finding(
        id=f"not-seen:{link.id}",
        kind="not-seen",
        title=f"{link.a.device} – {link.b.device} not seen",
        detail=f"Documented {_name(link.a.device, link.a.interface)} – "
        f"{_name(link.b.device, link.b.interface)}; {who}",
        link=link.id,
        documented=[
            Port(device=link.a.device, interface=link.a.interface),
            Port(device=link.b.device, interface=link.b.interface),
        ],
        devices=[link.a.device, link.b.device],
    )


def _down_links(topology: Topology, state: NetworkState) -> set[str]:
    """Links live state shows down, or that end at a device that is down."""
    down_ports = {(i.device, i.interface) for i in state.interfaces if i.oper == "down"}
    down_devices = {d.device for d in state.devices if d.status == "down"}
    return {
        ln.id
        for ln in topology.links
        if {(ln.a.device, ln.a.interface), (ln.b.device, ln.b.interface)} & down_ports
        or {ln.a.device, ln.b.device} & down_devices
    }


DOMAIN = ".net.example"
UNKNOWN_PLATFORM = "WS-C2960X-24TS"


class SimulatedDiscovery:
    """Neighbor tables made up from the topology, with disagreements seeded in.

    Each device the state source watches and finds up answers, every 15
    minutes. It reports each documented link that is up as live state says,
    except where the seeded disagreements say otherwise: a few links are
    not there, a few are on another port or to another device than
    documented, a few cables no one documented join two switches, a few
    ports lead to switches not in the topology, and one switch has LLDP and
    CDP off, so it neither reports nor is seen. The disagreements stay the
    same for a topology, as documentation drift does.
    """

    interval = timedelta(minutes=15)
    source = "simulated"

    def __init__(self, topology: Topology, state: StateSource, seed: int = 1) -> None:
        """Seed the disagreements.

        Args:
            topology: The documented network.
            state: Live state, for who answers and which links are up.
            seed: Random seed; the same seed gives the same disagreements.

        Raises:
            None
        """
        self.topology = topology
        self.state = state
        # Seeded where discovery can see it: on switches the source watches.
        watched = {d.device for d in state.snapshot(datetime.now(UTC)).devices}
        self._drift = _Drift(topology, watched, random.Random(seed))

    def discover(self, at: datetime) -> Discovery:
        """Neighbor tables as of a run.

        Args:
            at: When the run happened.

        Returns:
            A table for each watched device that is up, and not silent.

        Raises:
            None
        """
        snapshot = self.state.snapshot(at)
        up = {d.device for d in snapshot.devices if d.status == "up" and not d.stale}
        down = {d.device for d in snapshot.devices if d.status == "down"}
        down_ports = {
            (i.device, i.interface) for i in snapshot.interfaces if i.oper == "down"
        }
        devices = {d.name: d for d in self.topology.devices}
        rows: dict[str, list[Neighbor]] = {d: [] for d in up}
        # A switch with LLDP and CDP off still answers, but neither sees nor is seen.
        deaf = self._drift.silent

        def add(here: tuple[str, str], there: tuple[str, str]) -> None:
            if here[0] not in rows or here[0] in deaf or there[0] in deaf:
                return
            if there[0] in down:
                return
            if here in down_ports or there in down_ports:
                return
            remote = devices.get(there[0])
            rows[here[0]].append(_row(here[1], there, remote))

        for a, b in self._drift.cables():
            add(a, b)
            add(b, a)
        for device, port, name in self._drift.unknown:
            if device in rows:
                rows[device].append(
                    Neighbor(
                        interface=port,
                        remote=name,
                        remote_port="GigabitEthernet0/1",
                        protocol="cdp",
                        platform=UNKNOWN_PLATFORM,
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


def _row(port: str, there: tuple[str, str], remote: Device | None) -> Neighbor:
    """A row as a device would report it: CDP from some, LLDP from others."""
    device, remote_port = there
    if _hash(device) % 3 == 0:
        return Neighbor(
            interface=port,
            remote=device + DOMAIN,
            remote_port=short_interface(remote_port),
            protocol="lldp",
        )
    return Neighbor(
        interface=port,
        remote=device,
        remote_port=remote_port,
        protocol="cdp",
        platform=remote.platform if remote else None,
    )


def _hash(text: str) -> int:
    """A small hash that is the same in every process, unlike ``hash``."""
    return sum((i + 1) * ord(c) for i, c in enumerate(text))


class _Drift:
    """Where the simulated network differs from its documentation."""

    def __init__(
        self, topology: Topology, watched: set[str], rng: random.Random
    ) -> None:
        devices = {d.name: d for d in topology.devices}
        used: dict[str, set[str]] = {}
        for ln in topology.links:
            for end in (ln.a, ln.b):
                used.setdefault(end.device, set()).add(end.interface)
        self._used = used
        # Uplinks from access switches, where cabling changes most.
        uplinks = sorted(
            (
                ln
                for ln in topology.links
                if ln.kind == "lan"
                and {devices[ln.a.device].role, devices[ln.b.device].role}
                == {"access", "distribution"}
            ),
            key=lambda ln: ln.id,
        )
        rng.shuffle(uplinks)
        many = max(1, len(topology.links) // 1000)
        taken: set[str] = set()

        def pick(count: int) -> list[Link]:
            chosen = []
            for ln in uplinks:
                if len(chosen) == count:
                    break
                if {ln.a.device, ln.b.device} & taken:
                    continue
                taken.update({ln.a.device, ln.b.device})
                chosen.append(ln)
            return chosen

        def access(ln: Link) -> tuple[str, str]:
            a = devices[ln.a.device].role == "access"
            end = ln.a if a else ln.b
            return end.device, end.interface

        self.missing = {ln.id for ln in pick(many)}
        # Moved to a spare port on the access switch.
        self.moved: dict[str, tuple[str, str]] = {}
        for ln in pick(many):
            device, port = access(ln)
            self.moved[ln.id] = (device, self._spare(device, port))
        # Plugged into the other switch of the distribution pair: (the switch
        # documented, the one it is really on, and the port there).
        self.rewired: dict[str, tuple[str, str, str]] = {}
        for ln in pick(many):
            device, _ = access(ln)
            dist = ln.b.device if ln.a.device == device else ln.a.device
            pair = [
                d.name
                for d in topology.devices
                if d.site == devices[dist].site
                and d.role == "distribution"
                and d.name != dist
            ]
            if pair:
                taken.add(pair[0])
                port = ln.b.interface if ln.a.device == device else ln.a.interface
                self.rewired[ln.id] = (dist, pair[0], self._spare(pair[0], port))
        # Cables between two access switches at a site, and unknown switches.
        switches = sorted(
            (
                d
                for d in topology.devices
                if d.role == "access" and d.name in watched and d.name not in taken
            ),
            key=lambda d: (d.site, natural(d.name)),
        )
        self.extra: list[tuple[tuple[str, str], tuple[str, str]]] = []
        self.unknown: list[tuple[str, str, str]] = []
        for i in range(many):
            pairs = [
                (x, y)
                for x, y in zip(switches, switches[1:], strict=False)
                if x.site == y.site and not {x.name, y.name} & taken
            ]
            if pairs:
                x, y = pairs[rng.randrange(len(pairs))]
                taken.update({x.name, y.name})
                self.extra.append(
                    (
                        (x.name, self._spare(x.name, "GigabitEthernet1/0/1")),
                        (y.name, self._spare(y.name, "GigabitEthernet1/0/1")),
                    )
                )
            spare = [d for d in switches if d.name not in taken]
            if spare:
                lone = spare[rng.randrange(len(spare))]
                taken.add(lone.name)
                port = self._spare(lone.name, "GigabitEthernet1/0/1")
                self.unknown.append((lone.name, port, f"lab-sw-{i + 1:02d}"))
        spare = [d for d in switches if d.name not in taken]
        self.silent = {spare[rng.randrange(len(spare))].name} if spare else set()
        self._links = topology.links

    def _spare(self, device: str, like: str) -> str:
        """A port on a device that no documented link uses, named like another."""
        prefix = like.rstrip("0123456789")
        used = self._used.setdefault(device, set())
        n = 48
        while f"{prefix}{n}" in used:
            n += 1
        used.add(f"{prefix}{n}")
        return f"{prefix}{n}"

    def cables(self) -> Iterable[tuple[tuple[str, str], tuple[str, str]]]:
        """Every cable as it really is, as (device, port) pairs."""
        for ln in self._links:
            if ln.id in self.missing:
                continue
            a, b = (ln.a.device, ln.a.interface), (ln.b.device, ln.b.interface)
            if ln.id in self.moved:
                device, port = self.moved[ln.id]
                a, b = ((device, port), b) if a[0] == device else (a, (device, port))
            elif ln.id in self.rewired:
                documented, really, port = self.rewired[ln.id]
                a, b = (
                    ((really, port), b) if a[0] == documented else (a, (really, port))
                )
            yield a, b
        yield from self.extra
