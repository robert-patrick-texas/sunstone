"""Topology data model: sites, devices, and interface-to-interface links, and
the named networks, tunnels, and fabrics layered over them.

Each link end is a device name plus an interface name. NetBox cables, LLDP/CDP
neighbor tables, and NMS exports all reduce to that shape, and it is the key
that other tools' interface references (vakr's, for one) will be matched on.
A link's B end can instead be a transport (the Internet, a carrier's private
WAN) or an external node beyond what Sunstone manages; its A end is always
one of the network's own devices.

A named network is a slice of the whole: the links that carry it, the
tunnels and fabrics in it, and the transports whose circuits are in it.
Tunnels and fabrics each say which network they ride, so networks stack.
Names follow NetBox and Nautobot where they have the object: tenants,
provider networks (transports here), and tunnels with hub, spoke, and peer
terminations.
"""

from collections import Counter
from collections.abc import Iterable, Iterator
from functools import cached_property
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

Role = Literal["wan-edge", "core", "distribution", "access"]
LinkKind = Literal["lan", "wan"]
Boundary = Literal["inside", "outside"]
TransportKind = Literal["internet", "private-wan"]
ExternalKind = Literal["service", "partner", "tenant"]
FabricShape = Literal["hub-spoke", "hub-spoke-dynamic", "full-mesh", "group"]
MemberRole = Literal["hub", "spoke", "peer"]
Term = Literal[
    "network",
    "transport",
    "external",
    "service",
    "partner",
    "tenant",
    "tunnel",
    "fabric",
]


class _Record(BaseModel):
    # Unknown keys are rejected so a typo in a hand-edited file is an error,
    # not a silently missing value.
    model_config = ConfigDict(extra="forbid", frozen=True)


class Site(_Record):
    """A physical location with map coordinates."""

    code: str
    name: str
    region: str | None = None
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class Region(_Record):
    """A region sites are in, inside another region or at the top."""

    name: str
    parent: str | None = None


class Location(_Record):
    """A part of a site, such as a building, floor, or data hall, inside
    another location of the site or at the top (a location, in NetBox)."""

    site: str
    name: str
    parent: str | None = None


class Device(_Record):
    """A network device at one site."""

    name: str
    site: str
    role: Role
    platform: str | None = None
    mgmt_ip: str | None = None
    location: str | None = None
    """The location at its site it is in, if the site has locations."""


class Endpoint(_Record):
    """One end of a link: a device's interface, optionally a LAG member."""

    device: str
    interface: str
    lag: str | None = None


class TransportEnd(_Record):
    """The far end of a circuit into a transport."""

    transport: str


class ExternalEnd(_Record):
    """The far end of a link to something someone else runs."""

    external: str
    interface: str | None = None
    """Its port, if known."""


class Circuit(_Record):
    """A carrier circuit carrying a WAN link."""

    provider: str
    circuit_id: str


class SegmentIds(_Record):
    """What one end calls a network: its VLAN, VXLAN VNI, MPLS label, or VRF."""

    vlan: int | None = Field(None, ge=1, le=4094)
    vni: int | None = Field(None, ge=1, le=16_777_215)
    label: int | None = Field(None, ge=16, le=1_048_575)
    vrf: str | None = None


class Carried(_Record):
    """A network a link carries.

    Its numbers are the same at both ends unless ``a`` or ``b`` gives an end
    its own: VLAN 30 at one end can be VLAN 400 at the other.
    """

    network: str
    vlan: int | None = Field(None, ge=1, le=4094)
    vni: int | None = Field(None, ge=1, le=16_777_215)
    label: int | None = Field(None, ge=16, le=1_048_575)
    vrf: str | None = None
    a: SegmentIds | None = None
    b: SegmentIds | None = None


class Link(_Record):
    """A physical connection between two interfaces, or from an interface
    into a transport or to an external node."""

    a: Endpoint
    b: Endpoint | TransportEnd | ExternalEnd
    speed_mbps: int = Field(gt=0)
    kind: LinkKind = "lan"
    circuit: Circuit | None = None
    carries: list[Carried] = []
    """The named networks it carries; a circuit into a transport carries the
    transport's network whether or not it says so."""

    # Worked out once: links are frozen, and ids are looked up all the time.
    @computed_field
    @cached_property
    def id(self) -> str:
        """Stable identifier that does not depend on which end is listed first.

        Returns:
            The two ends, sorted and joined with ``--``: ``device:interface``
            for a device's, ``transport:NAME`` or ``external:NAME`` otherwise.
        """
        ends = sorted(end_key(e) for e in (self.a, self.b))
        return "--".join(ends)


def end_key(end: Endpoint | TransportEnd | ExternalEnd) -> str:
    """How a link end is written in a link's id.

    Args:
        end: A link end.

    Returns:
        ``device:interface``, ``transport:NAME``, or ``external:NAME``, with
        ``:interface`` after an external's name when its port is known.
    """
    if isinstance(end, Endpoint):
        return f"{end.device}:{end.interface}"
    if isinstance(end, TransportEnd):
        return f"transport:{end.transport}"
    port = f":{end.interface}" if end.interface else ""
    return f"external:{end.external}{port}"


def device_ends(link: Link) -> list[Endpoint]:
    """The ends of a link that are the network's own devices.

    Args:
        link: A link.

    Returns:
        Both ends, or only the A end for a link into a transport or to an
        external node.
    """
    return [link.a, link.b] if isinstance(link.b, Endpoint) else [link.a]


class Tenant(_Record):
    """An organization a network or node belongs to, as NetBox has them."""

    name: str
    description: str | None = None


class NamedNetwork(_Record):
    """A named slice of the network: black, blue, grey, a tenant's."""

    name: str
    boundary: Boundary = "inside"
    """Outside for networks that cross what others run, such as circuits
    and transports; traffic in a tunnel is inside."""
    tenant: str | None = None
    rides: list[str] = []
    """Networks it rides that are not said by tunnels or fabrics of its own,
    as for a tenant's network over one of ours."""
    anchors: list[str] = []
    """Sites it is reached from, such as its hubs; without any, its sites
    with core devices, or else the largest group of its sites that reach
    each other."""
    regions: dict[str, list[str]] = {}
    """Its own regions, each with its sites, when they are not the sites'
    own regions."""
    description: str | None = None
    tags: list[str] = []


class Transport(_Record):
    """A shared network someone else runs that circuits connect into: the
    Internet, or a carrier's private WAN (a provider network, in NetBox)."""

    name: str
    kind: TransportKind
    network: str | None = None
    """The named network its circuits are in."""
    provider: str | None = None
    description: str | None = None
    tags: list[str] = []


class External(_Record):
    """A node beyond what Sunstone manages: a service, a partner's device,
    or a tenant's."""

    name: str
    kind: ExternalKind
    tenant: str | None = None
    network: str | None = None
    """The named network it is part of, such as a tenant's network."""
    reached_over: list[str] = []
    """Transports it is reached across, as a cloud service is over the Internet."""
    platform: str | None = None
    description: str | None = None
    tags: list[str] = []


class TunnelEnd(_Record):
    """One of the network's own ends of a tunnel."""

    device: str
    interface: str
    source: str | None = None
    """The interface its packets leave from, physical or a loopback."""


class TunnelPeer(_Record):
    """A tunnel's far end that someone else runs: known by name, and its
    address if known."""

    external: str
    peer: str | None = None


class Tunnel(_Record):
    """A point-to-point tunnel: a link in one network that rides another."""

    name: str
    network: str
    rides: str
    technology: str | None = None
    """A label, such as ``GRE+IPsec`` or ``WireGuard``."""
    a: TunnelEnd
    b: TunnelEnd | TunnelPeer
    tags: list[str] = []


class FabricMember(_Record):
    """A device's tunnel interface in a fabric."""

    device: str
    interface: str
    role: MemberRole
    source: str | None = None


class Fabric(_Record):
    """Tunnels of one network made from members rather than listed: a DMVPN
    cloud, FlexVPN, AutoVPN, SD-WAN, or a GETVPN group."""

    name: str
    network: str
    rides: str
    shape: FabricShape
    """``hub-spoke``: each spoke to each hub. ``hub-spoke-dynamic``: the same,
    and spokes build tunnels to each other on demand. ``full-mesh``: every
    pair. ``group``: no tunnels; members reach each other directly."""
    technology: str | None = None
    members: list[FabricMember]
    tags: list[str] = []


class Topology(_Record):
    """A whole network: every site, device, and link, and what is layered
    over them."""

    name: str | None = None
    """The whole network's name, such as Enterprise, Global, or Nationwide."""
    sites: list[Site]
    devices: list[Device]
    links: list[Link]
    regions: list[Region] = []
    """Regions with their parents; without any, regions are just the names
    sites give."""
    locations: list[Location] = []
    networks: list[NamedNetwork] = []
    transports: list[Transport] = []
    externals: list[External] = []
    tenants: list[Tenant] = []
    tunnels: list[Tunnel] = []
    fabrics: list[Fabric] = []
    terms: dict[Term, str] = {}
    """The organization's own words for Sunstone's, such as ``tenant: Customer``."""

    @model_validator(mode="after")
    def _check_references(self) -> Self:
        """Reject duplicates and references to things that do not exist.

        Returns:
            The topology, unchanged.

        Raises:
            ValueError: Listing every problem found, one per line.
        """
        problems = [
            f"duplicate site code {code!r}"
            for code, n in Counter(s.code for s in self.sites).items()
            if n > 1
        ]
        problems += [
            f"duplicate device name {name!r}"
            for name, n in Counter(d.name for d in self.devices).items()
            if n > 1
        ]
        site_codes = {s.code for s in self.sites}
        problems += [
            f"device {d.name!r} is at unknown site {d.site!r}"
            for d in self.devices
            if d.site not in site_codes
        ]
        device_names = {d.name for d in self.devices}
        transports = {t.name: t for t in self.transports}
        externals = {e.name for e in self.externals}
        used: Counter[tuple[str, str]] = Counter()
        for link in self.links:
            b = link.b
            if isinstance(b, Endpoint) and link.a.device == b.device:
                problems.append(f"link {link.id} connects a device to itself")
            if isinstance(b, TransportEnd):
                if b.transport not in transports:
                    problems.append(
                        f"link {link.id} goes into unknown transport {b.transport!r}"
                    )
                if link.kind != "wan":
                    problems.append(f"link {link.id} into a transport is not kind wan")
            if isinstance(b, ExternalEnd) and b.external not in externals:
                problems.append(
                    f"link {link.id} goes to unknown external {b.external!r}"
                )
            for end in device_ends(link):
                used[(end.device, end.interface)] += 1
                if end.device not in device_names:
                    problems.append(
                        f"link {link.id} references unknown device {end.device!r}"
                    )
        problems += [
            f"interface {dev}:{ifname} is used by {n} links"
            for (dev, ifname), n in used.items()
            if n > 1
        ]
        problems += self._layer_problems(device_names, set(used))
        problems += self._group_problems()
        if problems:
            raise ValueError("\n".join(problems))
        return self

    def _layer_problems(
        self, device_names: set[str], cabled: set[tuple[str, str]]
    ) -> list[str]:
        """Problems with the named networks and what is layered over the links.

        Args:
            device_names: Every device.
            cabled: Every device interface a link uses.

        Returns:
            One message per problem found.
        """
        problems = [
            f"duplicate {kind} name {name!r}"
            for kind, names in (
                ("network", [n.name for n in self.networks]),
                ("transport", [t.name for t in self.transports]),
                ("external", [e.name for e in self.externals]),
                ("tenant", [t.name for t in self.tenants]),
                ("tunnel", [t.name for t in self.tunnels]),
                ("fabric", [f.name for f in self.fabrics]),
            )
            for name, n in Counter(names).items()
            if n > 1
        ]
        networks = {n.name for n in self.networks}
        tenants = {t.name for t in self.tenants}
        transports = {t.name: t for t in self.transports}
        externals = {e.name for e in self.externals}

        def unknown(
            what: str, kind: str, names: Iterable[str | None], known: set[str]
        ) -> list[str]:
            return [
                f"{what} names unknown {kind} {name!r}"
                for name in names
                if name is not None and name not in known
            ]

        for n in self.networks:
            what = f"network {n.name!r}"
            problems += unknown(what, "tenant", [n.tenant], tenants)
            problems += unknown(what, "network", n.rides, networks)
        for t in self.transports:
            problems += unknown(
                f"transport {t.name!r}", "network", [t.network], networks
            )
        for e in self.externals:
            what = f"external {e.name!r}"
            problems += unknown(what, "tenant", [e.tenant], tenants)
            problems += unknown(what, "network", [e.network], networks)
            problems += unknown(what, "transport", e.reached_over, set(transports))
            if e.kind == "tenant" and e.tenant is None:
                problems.append(f"{what} is a tenant's but names no tenant")
        for link in self.links:
            problems += unknown(
                f"link {link.id}",
                "network",
                [c.network for c in link.carries],
                networks,
            )
            if isinstance(link.b, TransportEnd) and link.b.transport in transports:
                own = transports[link.b.transport].network
                problems += [
                    f"link {link.id} into {link.b.transport!r} carries {c.network!r}, "
                    f"not the transport's network"
                    for c in link.carries
                    if c.network != own
                ]
        carried = _carried_at(self.links, transports)
        tunnel_ends: Counter[tuple[str, str]] = Counter()
        for what, net, rides, ends in self._tunnel_ends():
            problems += unknown(what, "network", [net, rides], networks)
            if net == rides:
                problems.append(f"{what} rides its own network {net!r}")
            for end in ends:
                if isinstance(end, TunnelPeer):
                    problems += unknown(what, "external", [end.external], externals)
                    continue
                if end.device not in device_names:
                    problems.append(f"{what} references unknown device {end.device!r}")
                tunnel_ends[(end.device, end.interface)] += 1
                if (end.device, end.interface) in cabled:
                    problems.append(
                        f"{what} uses {end.device}:{end.interface}, which is cabled"
                    )
                source = (end.device, end.source or "")
                if source in carried and rides not in carried[source]:
                    problems.append(
                        f"{what} leaves {end.device}:{end.source}, which does not "
                        f"carry {rides!r}"
                    )
        problems += [
            f"tunnel interface {dev}:{ifname} is used {n} times"
            for (dev, ifname), n in tunnel_ends.items()
            if n > 1
        ]
        problems += self._fabric_problems()
        problems += _cycles(self._rides())
        return problems

    def _group_problems(self) -> list[str]:
        """Problems with regions, locations, and networks' own groups.

        Returns:
            One message per problem found.
        """
        problems = [
            f"duplicate region name {name!r}"
            for name, n in Counter(r.name for r in self.regions).items()
            if n > 1
        ]
        regions = {r.name: r.parent for r in self.regions}
        problems += [
            f"region {name!r} is in unknown region {parent!r}"
            for name, parent in regions.items()
            if parent is not None and parent not in regions
        ]
        problems += [
            f"region {name!r} is inside itself" for name in _inside_themselves(regions)
        ]
        if regions:
            problems += [
                f"site {s.code!r} is in unknown region {s.region!r}"
                for s in self.sites
                if s.region is not None and s.region not in regions
            ]
        problems += [
            f"duplicate location {name!r} at {site!r}"
            for (site, name), n in Counter(
                (x.site, x.name) for x in self.locations
            ).items()
            if n > 1
        ]
        site_codes = {s.code for s in self.sites}
        located = {(x.site, x.name): x.parent for x in self.locations}
        for x in self.locations:
            if x.site not in site_codes:
                problems.append(f"location {x.name!r} is at unknown site {x.site!r}")
            if x.parent is not None and (x.site, x.parent) not in located:
                problems.append(
                    f"location {x.name!r} at {x.site} is in unknown location "
                    f"{x.parent!r}"
                )
        for site in sorted({x.site for x in self.locations}):
            tree = {n: p for (s, n), p in located.items() if s == site}
            problems += [
                f"location {name!r} at {site} is inside itself"
                for name in _inside_themselves(tree)
            ]
        problems += [
            f"device {d.name!r} is in unknown location {d.location!r} at {d.site}"
            for d in self.devices
            if d.location is not None and (d.site, d.location) not in located
        ]
        for n in self.networks:
            problems += [
                f"network {n.name!r} names unknown anchor site {code!r}"
                for code in n.anchors
                if code not in site_codes
            ]
            listed = [code for sites in n.regions.values() for code in sites]
            problems += [
                f"network {n.name!r} puts unknown site {code!r} in a region"
                for code in sorted(set(listed) - site_codes)
            ]
            problems += [
                f"network {n.name!r} puts site {code!r} in {k} regions"
                for code, k in Counter(listed).items()
                if k > 1
            ]
        return problems

    def _tunnel_ends(
        self,
    ) -> Iterator[tuple[str, str, str, list[TunnelEnd | TunnelPeer]]]:
        """Each tunnel and fabric, with its network, what it rides, and its ends."""
        for t in self.tunnels:
            yield f"tunnel {t.name!r}", t.network, t.rides, [t.a, t.b]
        for f in self.fabrics:
            ends: list[TunnelEnd | TunnelPeer] = [
                TunnelEnd(device=m.device, interface=m.interface, source=m.source)
                for m in f.members
            ]
            yield f"fabric {f.name!r}", f.network, f.rides, ends

    def _fabric_problems(self) -> list[str]:
        """Fabrics whose members do not fit their shape."""
        problems = []
        for f in self.fabrics:
            roles = Counter(m.role for m in f.members)
            if f.shape in ("hub-spoke", "hub-spoke-dynamic"):
                if roles["peer"] or not roles["hub"]:
                    problems.append(
                        f"fabric {f.name!r} is {f.shape}: its members must be hubs "
                        f"and spokes, with at least one hub"
                    )
            elif roles["hub"] or roles["spoke"]:
                problems.append(
                    f"fabric {f.name!r} is {f.shape}: its members are peers"
                )
            problems += [
                f"fabric {f.name!r} has {device!r} {n} times"
                for device, n in Counter(m.device for m in f.members).items()
                if n > 1
            ]
        return problems

    def _rides(self) -> dict[str, set[str]]:
        """Which networks each network rides, from every place that says so."""
        rides: dict[str, set[str]] = {n.name: set(n.rides) for n in self.networks}
        for t in [*self.tunnels, *self.fabrics]:
            rides.setdefault(t.network, set()).add(t.rides)
        return rides


def _carried_at(
    links: list[Link], transports: dict[str, Transport]
) -> dict[tuple[str, str], set[str]]:
    """The networks each cabled device interface carries.

    Args:
        links: Every link.
        transports: Transports by name.

    Returns:
        For each device end of a link, by device and interface, the networks
        its link carries.
    """
    carried: dict[tuple[str, str], set[str]] = {}
    for link in links:
        nets = {c.network for c in link.carries}
        if isinstance(link.b, TransportEnd) and link.b.transport in transports:
            own = transports[link.b.transport].network
            if own:
                nets.add(own)
        for end in device_ends(link):
            carried[(end.device, end.interface)] = nets
    return carried


def _inside_themselves(parents: dict[str, str | None]) -> list[str]:
    """Names whose chain of parents comes back to them.

    Args:
        parents: Each name's parent, or None at the top.

    Returns:
        The names in a loop, sorted.
    """
    looped = []
    for start in sorted(parents):
        seen = {start}
        at = parents.get(start)
        while at is not None and at in parents:
            if at == start:
                looped.append(start)
                break
            if at in seen:
                break
            seen.add(at)
            at = parents.get(at)
    return looped


def _cycles(rides: dict[str, set[str]]) -> list[str]:
    """Networks that ride themselves, through any number of others.

    Args:
        rides: The networks each network rides.

    Returns:
        One message per network found riding itself.
    """
    problems = []
    for start in sorted(rides):
        seen: set[str] = set()
        stack = list(rides[start])
        while stack:
            n = stack.pop()
            if n == start:
                problems.append(f"network {start!r} rides itself")
                break
            if n not in seen:
                seen.add(n)
                stack.extend(rides.get(n, ()))
    return problems


def device_b(link: Link) -> Endpoint:
    """The B end of a link between two devices.

    For code that works on cables between devices only, such as simulated
    cabling and discovery, given links from :func:`cabled`.

    Args:
        link: A link between two devices.

    Returns:
        Its B end.

    Raises:
        TypeError: If the link goes into a transport or to an external node.
    """
    if not isinstance(link.b, Endpoint):
        raise TypeError(f"link {link.id} does not end at a device")
    return link.b


def cabled(topology: Topology) -> Topology:
    """A topology with only its links between two of its devices.

    They are the only links discovery compares so far (what LLDP and CDP
    show across a circuit into a transport depends on the service, and is not
    documented yet), and the only cables simulated cabling moves.

    Args:
        topology: A topology.

    Returns:
        The same topology without its links into transports or to
        external nodes; the topology itself if it has none.
    """
    cables = [ln for ln in topology.links if isinstance(ln.b, Endpoint)]
    if len(cables) == len(topology.links):
        return topology
    return topology.model_copy(update={"links": cables})


def end_name(end: Endpoint | TransportEnd | ExternalEnd) -> str:
    """What a link end is called: its device, transport, or external node.

    Args:
        end: A link end.

    Returns:
        The name, without any interface.
    """
    if isinstance(end, Endpoint):
        return end.device
    if isinstance(end, TransportEnd):
        return end.transport
    return end.external
