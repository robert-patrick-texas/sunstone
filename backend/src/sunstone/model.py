"""Topology data model: sites, devices, and interface-to-interface links, and
the named networks, tunnels, and fabrics layered over them.

Each link end is a device name plus an interface name. NetBox cables, LLDP/CDP
neighbor tables, and NMS exports all reduce to that shape, and it is the key
that other tools' interface references (vakr's, for one) will be matched on.
A link's B end can instead be a transport (the Internet, a carrier's private
WAN) or an external node beyond what Sunstone manages; its A end is always
one of the network's own devices.

Each connection also says what carries it and what it is for. ``medium`` is
what carries the bits at our port (fiber, copper, radio). A link with a
``circuit`` crosses a provider's path: a carrier's service, or a provider's
cable such as a co-location cross-connect; one without is our own cable,
fiber, or radio. ``edges`` are its roles at the edge of the enterprise
(access, transit, interconnect, ingress, egress, peering, open), set by
routing policy at each site and so documented, never worked out from the
transport; Sunstone implies them only where the far end leaves no doubt
(``link_roles``). ``neighbors`` says what LLDP and CDP should show on our
port. Links, tunnels, and fabrics carry the IDs operations staff quote: the
enterprise's own CID (a cable ID on our own cables) and the carrier's, each
the same at the A and Z sides unless the Z side has its own or none.

A named network is a slice of the whole: the links that carry it, the
tunnels and fabrics in it, and the transports whose circuits are in it.
Tunnels and fabrics each say which network they ride, so networks stack.
Names follow NetBox and Nautobot where they have the object: tenants,
provider networks (transports here), and tunnels with hub, spoke, and peer
terminations.
"""

from collections import Counter
from collections.abc import Iterable, Iterator, Mapping
from functools import cached_property
from typing import Any, Literal, NamedTuple, Self, get_args

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

Role = Literal["wan-edge", "core", "distribution", "access"]
LinkKind = Literal["lan", "wan"]
Boundary = Literal["inside", "outside"]
TransportKind = Literal["internet", "private-wan", "research"]
ExternalKind = Literal["application", "partner", "tenant"]
Medium = Literal[
    "fiber", "copper", "twinax", "radio", "microwave", "cellular", "satellite"
]
CircuitType = Literal["carrier", "cross-connect"]
Edge = Literal[
    "access", "transit", "interconnect", "ingress", "egress", "peering", "open"
]
EDGES: tuple[Edge, ...] = get_args(Edge)
Neighbors = Literal["far-end", "provider", "nothing"]
"""What LLDP and CDP show on our port: the device at the far end (ours or
someone else's; across a layer-2 transport, our devices on the same
service), the provider's own equipment (an NTU or PE), or nothing."""
Service = Literal["e-lan", "e-tree"]
"""A layer-2 transport's service: many to many (E-LAN: VPLS, EVPN), or one
to many (E-Tree: EVPN with root and leaf policies)."""
CircuitService = Literal["e-line", "e-access"]
"""A point-to-point layer-2 circuit's service: E-Line (VPWS, a pseudowire),
or E-Access (from a UNI to another operator's NNI)."""
TreeRole = Literal["root", "leaf"]
Secured = Literal["inside", "alongside", "none"]
"""How LLDP and CDP relate to a MACsec connection: they run ``inside`` it,
so its far end seen proves the encryption works; ``alongside`` it, in clear,
so its far end seen proves only the circuit; or they do not reach its far
end at all (``none``)."""
TunnelKind = Literal["ip", "macsec"]
"""``ip``: packets in packets (GRE, IPsec, WireGuard), on a tunnel interface
of its own. ``macsec``: frames encrypted on the physical port itself."""
FabricShape = Literal["hub-spoke", "hub-spoke-dynamic", "full-mesh", "group"]
MemberRole = Literal["hub", "spoke", "peer"]
Term = Literal[
    "network",
    "transport",
    "external",
    "application",
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
    role: TreeRole | None = None
    """Into an E-Tree: a root, or a leaf (the default), which reaches only
    the roots."""


class ExternalEnd(_Record):
    """The far end of a link to something someone else runs."""

    external: str
    interface: str | None = None
    """Its port, if known."""


class Sides(_Record):
    """An ID as each side of a connection knows it: the same at both sides
    unless the Z side has its own, or none.

    Written as a plain value for both sides, or as ``{a: ..., z: ...}``;
    ``z`` left out is the same as ``a``, and ``z: ''`` (or null) leaves the
    Z side blank. Into a shared transport, a plain value is the A side's
    only, since the Z side is the provider's network.
    """

    a: str = Field(min_length=1)
    z: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _same_unless_said(cls, data: Any) -> Any:
        """Read a plain value as both sides', and a missing Z side as the A side's.

        Args:
            data: What was written.

        Returns:
            The sides, with Z worked out.
        """
        return _sides(data, shared=False)


def _sides(data: Any, shared: bool) -> Any:
    """An ID as written, with its Z side worked out.

    Args:
        data: A plain value, ``{a, z}``, or anything else (left to validation).
        shared: It is for a circuit into a shared transport, whose Z side
            is the provider's network: a plain value is the A side's only.

    Returns:
        ``{a, z}`` for a value or a mapping; anything else as it was.
    """
    if isinstance(data, str):
        return {"a": data, "z": None if shared else data}
    if isinstance(data, Mapping) and "a" in data:
        if "z" not in data:
            return {**data, "z": None if shared else data["a"]}
        return {**data, "z": data["z"] or None}
    return data


class Circuit(_Record):
    """What a provider supplies for a connection: a carrier's circuit, or a
    provider's cable such as a co-location cross-connect."""

    provider: str
    circuit_id: Sides
    """The carrier's CID, as the carrier writes it: free-form, and it may
    hold several, such as the local exchange carrier's and the carrier's."""
    type: CircuitType = "carrier"
    """``carrier``: a communications service, whose path the provider runs.
    ``cross-connect``: the provider's cable, as between co-location cages."""
    service: CircuitService | None = None
    """For a point-to-point layer-2 circuit, its service; into a transport,
    the transport's service is the circuit's."""
    technology: str | None = None
    """A label, such as ``VPWS``, ``pseudowire``, or ``802.1Q-in-Q``."""


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
    medium: Medium | None = None
    """What carries the bits at our port."""
    enterprise_cid: Sides | None = None
    """The enterprise's own ID for it: a circuit ID, or on our own cable,
    its cable ID."""
    edges: list[Edge] = []
    """Its roles at the edge of the enterprise, as routing policy sets them;
    without any, ``link_roles`` implies them where the far end leaves no doubt."""
    neighbors: list[Neighbors] = []
    """What LLDP and CDP show on our port, one or more (the provider's NTU
    over LLDP while CDP passes through to the far end); without it, the far
    end between two of our devices, and not said otherwise."""

    @field_validator("neighbors", mode="before")
    @classmethod
    def _one_or_more(cls, value: Any) -> Any:
        """Read a single value as a list of one, and none as not said.

        Args:
            value: What was written.

        Returns:
            A list, or the value as it was for validation to judge.
        """
        if value is None:
            return []
        return [value] if isinstance(value, str) else value

    @model_validator(mode="before")
    @classmethod
    def _ids_into_transport(cls, data: Any) -> Any:
        """Leave the Z side of a circuit into a shared transport blank
        unless it is written out.

        Args:
            data: The link as written.

        Returns:
            The link, with its IDs' sides worked out.
        """
        if not isinstance(data, Mapping):
            return data
        b = data.get("b")
        shared = isinstance(b, TransportEnd) or (
            isinstance(b, Mapping) and "transport" in b
        )
        if not shared:
            return data
        fixed = dict(data)
        if "enterprise_cid" in fixed:
            fixed["enterprise_cid"] = _sides(fixed["enterprise_cid"], shared=True)
        circuit = fixed.get("circuit")
        if isinstance(circuit, Mapping) and "circuit_id" in circuit:
            fixed["circuit"] = {
                **circuit,
                "circuit_id": _sides(circuit["circuit_id"], shared=True),
            }
        return fixed

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
    service: Service | None = None
    """A layer-2 service, E-LAN or E-Tree; without one, it is routed."""
    technology: str | None = None
    """A label, such as ``VPLS``, ``MPLS EVPN``, or ``VXLAN EVPN``."""
    description: str | None = None
    tags: list[str] = []


class External(_Record):
    """A node beyond what Sunstone manages: an application someone else
    provides (a cloud, a SaaS), a partner's device, or a tenant's."""

    name: str
    kind: ExternalKind
    tenant: str | None = None
    network: str | None = None
    """The named network it is part of, such as a tenant's network."""
    reached_over: list[str] = []
    """Transports it is reached across, as a cloud is over the Internet."""
    platform: str | None = None
    description: str | None = None
    tags: list[str] = []


class TunnelEnd(_Record):
    """One of the network's own ends of a tunnel."""

    device: str
    interface: str
    """Its tunnel interface; for MACsec, the physical port it is on."""
    source: str | None = None
    """The interface its packets leave from, physical or a loopback; none
    for MACsec."""


class TunnelPeer(_Record):
    """A tunnel's far end that someone else runs: known by name, and its
    address if known."""

    external: str
    peer: str | None = None


class Tunnel(_Record):
    """A point-to-point tunnel: a link in one network that rides another.

    MACsec (``kind: macsec``) is a connection of its own too, though it is
    configured on the physical port: its ends are the ports of the link it
    rides, or of two circuits into one layer-2 transport, and it is up
    while they are. What the port shows is its link's to say (``neighbors``
    on the link); the MACsec connection says only how LLDP and CDP relate
    to it.
    """

    name: str
    network: str
    rides: str
    kind: TunnelKind = "ip"
    technology: str | None = None
    """A label, such as ``GRE+IPsec``, ``WireGuard``, or ``GCM-AES-XPN-256``."""
    neighbors: Secured | None = None
    """For MACsec, how LLDP and CDP relate to it; not said, discovery cannot
    vouch for it."""
    a: TunnelEnd
    b: TunnelEnd | TunnelPeer
    tags: list[str] = []
    enterprise_cid: Sides | None = None
    circuit: Circuit | None = None
    """The provider whose service it is, and the provider's CID, if any."""
    edges: list[Edge] = []


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
    enterprise_cid: Sides | None = None
    circuit: Circuit | None = None
    """The provider whose service it is, and the provider's CID, if any."""
    edges: list[Edge] = []


class LagEnd(_Record):
    """A port channel on one of the network's devices."""

    device: str
    interface: str
    """The channel's own interface, such as ``Port-channel10``."""


class Lag(_Record):
    """A link aggregation between two of the network's devices: one or more
    member links, each with its own cable or circuit ID, bundled into one
    channel with a CID of its own. Members name it with ``lag`` on their
    ends."""

    a: LagEnd
    b: LagEnd
    enterprise_cid: Sides | None = None
    """The enterprise's own ID for the channel."""
    circuit: Circuit | None = None
    """The provider whose bundle it is, and the provider's CID, if any."""

    @computed_field
    @cached_property
    def id(self) -> str:
        """Stable identifier that does not depend on which end is listed first.

        Returns:
            Both ends' ``device:channel``, sorted and joined with ``--``.
        """
        ends = sorted(f"{e.device}:{e.interface}" for e in (self.a, self.b))
        return "--".join(ends)


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
    lags: list[Lag] = []
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
        at_port: dict[tuple[str, str], Link] = {}
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
                at_port[(end.device, end.interface)] = link
                if end.device not in device_names:
                    problems.append(
                        f"link {link.id} references unknown device {end.device!r}"
                    )
        problems += [
            f"interface {dev}:{ifname} is used by {n} links"
            for (dev, ifname), n in used.items()
            if n > 1
        ]
        problems += self._layer_problems(device_names, at_port)
        problems += self._lag_problems(device_names)
        problems += self._group_problems()
        if problems:
            raise ValueError("\n".join(problems))
        return self

    def _layer_problems(
        self, device_names: set[str], at_port: dict[tuple[str, str], Link]
    ) -> list[str]:
        """Problems with the named networks and what is layered over the links.

        Args:
            device_names: Every device.
            at_port: The link at each device interface a link uses.

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
        for link in self.links:
            problems += _connection_problems(link, transports)
        problems += _tree_problems(self.links, transports)
        for what, edges in (
            *((f"tunnel {t.name!r}", t.edges) for t in self.tunnels),
            *((f"fabric {f.name!r}", f.edges) for f in self.fabrics),
        ):
            problems += [
                f"{what} names edge {e!r} twice"
                for e, n in Counter(edges).items()
                if n > 1
            ]
        carried = _carried_at(self.links, transports)
        tunnel_ends: Counter[tuple[str, str]] = Counter()
        for what, net, rides, ends, macsec in self._tunnel_ends():
            problems += unknown(what, "network", [net, rides], networks)
            if net == rides:
                problems.append(f"{what} rides its own network {net!r}")
            for end in ends:
                if isinstance(end, TunnelPeer):
                    problems += unknown(what, "external", [end.external], externals)
                    continue
                if end.device not in device_names:
                    problems.append(f"{what} references unknown device {end.device!r}")
                port = (end.device, end.interface)
                if macsec:
                    # On the physical port itself, which its link leaves from.
                    if port not in at_port:
                        problems.append(
                            f"{what} is MACsec on {end.device}:{end.interface}, "
                            "which no link uses"
                        )
                    if end.source is not None:
                        problems.append(
                            f"{what} is MACsec, on the port itself: it has no source"
                        )
                    source = port
                else:
                    tunnel_ends[port] += 1
                    if port in at_port:
                        problems.append(
                            f"{what} uses {end.device}:{end.interface}, which is cabled"
                        )
                    source = (end.device, end.source or "")
                if source in carried and rides not in carried[source]:
                    problems.append(
                        f"{what} leaves {end.device}:{source[1]}, which does not "
                        f"carry {rides!r}"
                    )
        problems += [
            f"tunnel interface {dev}:{ifname} is used {n} times"
            for (dev, ifname), n in tunnel_ends.items()
            if n > 1
        ]
        problems += _macsec_problems(self.tunnels, at_port, transports)
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
    ) -> Iterator[tuple[str, str, str, list[TunnelEnd | TunnelPeer], bool]]:
        """Each tunnel and fabric, with its network, what it rides, its ends,
        and whether it is MACsec."""
        for t in self.tunnels:
            macsec = t.kind == "macsec"
            yield f"tunnel {t.name!r}", t.network, t.rides, [t.a, t.b], macsec
        for f in self.fabrics:
            ends: list[TunnelEnd | TunnelPeer] = [
                TunnelEnd(device=m.device, interface=m.interface, source=m.source)
                for m in f.members
            ]
            yield f"fabric {f.name!r}", f.network, f.rides, ends, False

    def _lag_problems(self, device_names: set[str]) -> list[str]:
        """Port channels that are listed twice, name unknown devices, have no
        members, or have members ending elsewhere than the channel's far end.

        Args:
            device_names: Every device.

        Returns:
            One message per problem found.
        """
        problems = []
        ends: Counter[tuple[str, str]] = Counter()
        for lag in self.lags:
            what = f"lag {lag.id}"
            for end in (lag.a, lag.b):
                ends[(end.device, end.interface)] += 1
                if end.device not in device_names:
                    problems.append(f"{what} references unknown device {end.device!r}")
            if lag.a.device == lag.b.device:
                problems.append(f"{what} joins a device to itself")
            members = lag_members(lag, self.links)
            if not members:
                problems.append(f"{what} has no member links")
            for link in members:
                if not isinstance(link.b, Endpoint):
                    problems.append(
                        f"{what} has {link.id}, which does not end at a device"
                    )
                    continue
                far = link.b if link.a.device == lag.a.device else link.a
                if (far.device, far.lag) != (lag.b.device, lag.b.interface):
                    problems.append(
                        f"{what} has {link.id}, whose far end is not in "
                        f"{lag.b.device}:{lag.b.interface}"
                    )
        problems += [
            f"port channel {dev}:{ifname} is listed {n} times"
            for (dev, ifname), n in ends.items()
            if n > 1
        ]
        return problems

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


def _connection_problems(link: Link, transports: Mapping[str, Transport]) -> list[str]:
    """Problems with what a link says carries it and what it shows.

    Args:
        link: A link.
        transports: Transports by name.

    Returns:
        One message per problem found.
    """
    problems = [
        f"link {link.id} names {what} {e!r} twice"
        for what, values in (("edge", link.edges), ("neighbors", link.neighbors))
        for e, n in Counter(values).items()
        if n > 1
    ]
    if "nothing" in link.neighbors and len(set(link.neighbors)) > 1:
        problems.append(f"link {link.id} shows nothing, and something besides")
    if "provider" in link.neighbors and link.circuit is None:
        problems.append(
            f"link {link.id} shows the provider's equipment, but has no circuit"
        )
    b = link.b
    if not isinstance(b, TransportEnd):
        return problems
    transport = transports.get(b.transport)
    if transport is None:
        return problems
    if "far-end" in link.neighbors and transport.service is None:
        problems.append(
            f"link {link.id} into {b.transport!r} shows the far end, but a "
            "routed transport's far end is the provider's network: say provider "
            "or nothing"
        )
    if b.role is not None and transport.service != "e-tree":
        problems.append(
            f"link {link.id} into {b.transport!r} is a {b.role}, but "
            f"{b.transport!r} is not an E-Tree"
        )
    if link.circuit is not None and link.circuit.service == "e-line":
        problems.append(
            f"link {link.id} into {b.transport!r} is an E-Line, which is point to point"
        )
    return problems


def _tree_problems(links: list[Link], transports: Mapping[str, Transport]) -> list[str]:
    """E-Trees without a root: their leaves would reach nothing.

    Args:
        links: Every link.
        transports: Transports by name.

    Returns:
        One message per E-Tree with circuits into it and no root.
    """
    rooted: dict[str, bool] = {}
    for ln in links:
        if isinstance(ln.b, TransportEnd):
            name = ln.b.transport
            rooted[name] = rooted.get(name, False) or ln.b.role == "root"
    return [
        f"transport {name!r} is an E-Tree with no root"
        for name, has in sorted(rooted.items())
        if not has and name in transports and transports[name].service == "e-tree"
    ]


def _macsec_problems(
    tunnels: list[Tunnel],
    at_port: Mapping[tuple[str, str], Link],
    transports: Mapping[str, Transport],
) -> list[str]:
    """MACsec connections whose ends no one link or layer-2 service joins,
    and ports with MACsec to one far end twice.

    Args:
        tunnels: Every tunnel.
        at_port: The link at each device interface a link uses.
        transports: Transports by name.

    Returns:
        One message per problem found.
    """
    problems = []
    pairs: Counter[frozenset[str]] = Counter()
    for t in tunnels:
        what = f"tunnel {t.name!r}"
        if t.kind != "macsec":
            if t.neighbors is not None:
                problems.append(
                    f"{what} says how LLDP and CDP relate to it, which only MACsec does"
                )
            continue
        here = at_port.get((t.a.device, t.a.interface))
        if here is None:
            continue
        b = t.b
        far = (
            f"{b.device}:{b.interface}"
            if isinstance(b, TunnelEnd)
            else f"external:{b.external}"
        )
        pairs[frozenset({f"{t.a.device}:{t.a.interface}", far})] += 1
        if isinstance(b, TunnelPeer):
            if not (isinstance(here.b, ExternalEnd) and here.b.external == b.external):
                problems.append(
                    f"{what} is MACsec to {b.external!r}, but {here.id} does not "
                    "go there"
                )
            continue
        there = at_port.get((b.device, b.interface))
        if there is None or there is here:
            continue
        if not (
            isinstance(here.b, TransportEnd)
            and isinstance(there.b, TransportEnd)
            and here.b.transport == there.b.transport
            and here.b.transport in transports
            and transports[here.b.transport].service is not None
        ):
            problems.append(
                f"{what} is MACsec, but neither one link nor one layer-2 "
                "transport joins its ends"
            )
        elif "root" not in (here.b.role, there.b.role) and (
            transports[here.b.transport].service == "e-tree"
        ):
            problems.append(
                f"{what} is MACsec between two leaves of {here.b.transport!r}, "
                "which reach only the roots"
            )
    problems += [
        f"MACsec between {' and '.join(sorted(pair))} is listed {n} times"
        for pair, n in pairs.items()
        if n > 1
    ]
    return problems


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


RoleSource = Literal["declared", "implied", "tbd"]


class Roles(NamedTuple):
    """A connection's roles at the edge of the enterprise, and where they come from."""

    edges: tuple[Edge, ...]
    """Empty and implied for a link between two of our devices: internal."""
    source: RoleSource
    """``declared`` in the topology; ``implied`` by what is at the far end;
    ``tbd`` where only routing policy could say, as for a circuit into a
    transport no one has given roles yet."""


_BY_KIND: dict[ExternalKind, Edge] = {
    "tenant": "access",
    "partner": "interconnect",
    "application": "egress",
}


def link_roles(link: Link, externals: Mapping[str, External]) -> Roles:
    """A link's roles at the edge: as documented, or implied by its far end.

    A link between two of our devices is internal, with no role, unless a
    provider's circuit or cable joins them, which makes it transit. A tenant's
    device is let in (access), a partner's network is joined (interconnect),
    and an application is used (egress). What a circuit into a transport is
    for depends on routing policy at its site, so it is TBD until documented.

    Args:
        link: The link.
        externals: External nodes by name, for what kind each is.

    Returns:
        Its roles, and where they come from.

    Raises:
        None
    """
    if link.edges:
        return Roles(tuple(link.edges), "declared")
    b = link.b
    if isinstance(b, Endpoint):
        return Roles(("transit",) if link.circuit else (), "implied")
    if isinstance(b, ExternalEnd) and b.external in externals:
        return Roles((_BY_KIND[externals[b.external].kind],), "implied")
    return Roles((), "tbd")


def tunnel_roles(tunnel: Tunnel, externals: Mapping[str, External]) -> Roles:
    """A tunnel's roles at the edge: as documented, or implied by its far end.

    Args:
        tunnel: The tunnel.
        externals: External nodes by name.

    Returns:
        Transit between two of our devices; to an external node, by its kind.

    Raises:
        None
    """
    if tunnel.edges:
        return Roles(tuple(tunnel.edges), "declared")
    b = tunnel.b
    if isinstance(b, TunnelEnd):
        return Roles(("transit",), "implied")
    if b.external in externals:
        return Roles((_BY_KIND[externals[b.external].kind],), "implied")
    return Roles((), "tbd")


def fabric_roles(fabric: Fabric) -> Roles:
    """A fabric's roles at the edge: as documented, else transit, since its
    members are all ours.

    Args:
        fabric: The fabric.

    Returns:
        Its roles.

    Raises:
        None
    """
    if fabric.edges:
        return Roles(tuple(fabric.edges), "declared")
    return Roles(("transit",), "implied")


def joins(link: Link) -> bool:
    """Whether a link joins its far end to the rest of the network, for
    reach, paths, and the tunnels riding it.

    A circuit into a transport carries our traffic to our other sites
    across it only when it is for transit, or its roles are still to be
    documented: routing policy keeps it off one only for peering, open,
    ingress, or egress. Every other link joins its ends.

    Args:
        link: The link.

    Returns:
        False for a circuit into a transport whose documented roles leave
        out transit; else True.

    Raises:
        None
    """
    return not (
        isinstance(link.b, TransportEnd) and link.edges and "transit" not in link.edges
    )


def shows(link: Link) -> tuple[Neighbors, ...]:
    """What LLDP and CDP should show on a link's port at our end.

    Args:
        link: The link.

    Returns:
        As documented, one or more; else the far end between two of our
        devices, which is how they have always been compared; else nothing
        at all: not said.

    Raises:
        None
    """
    if link.neighbors:
        return tuple(link.neighbors)
    return ("far-end",) if isinstance(link.b, Endpoint) else ()


def lag_members(lag: Lag, links: Iterable[Link]) -> list[Link]:
    """A port channel's member links.

    Args:
        lag: The channel.
        links: Every link.

    Returns:
        The links with an end in the channel at its A end, in order.

    Raises:
        None
    """
    return [
        ln
        for ln in links
        if any(
            (e.device, e.lag) == (lag.a.device, lag.a.interface)
            for e in device_ends(ln)
        )
    ]


def layer2(transport: Transport | None) -> bool:
    """Whether a transport is a layer-2 service, across which our devices
    see each other.

    Args:
        transport: The transport, or None if there is none.

    Returns:
        True for an E-LAN or an E-Tree.

    Raises:
        None
    """
    return transport is not None and transport.service is not None


def sees_across(here: Link, there: Link, transports: Mapping[str, Transport]) -> bool:
    """Whether two circuits into one layer-2 transport reach each other
    across it: on an E-LAN every pair does, and on an E-Tree every pair but
    two leaves.

    Args:
        here: A circuit.
        there: Another circuit.
        transports: Transports by name.

    Returns:
        True if both go into the same layer-2 transport and its service lets
        them reach each other.

    Raises:
        None
    """
    a, b = here.b, there.b
    if here is there:
        return False
    if not (isinstance(a, TransportEnd) and isinstance(b, TransportEnd)):
        return False
    transport = transports.get(a.transport)
    if a.transport != b.transport or not layer2(transport):
        return False
    return transport is not None and (
        transport.service != "e-tree" or "root" in (a.role, b.role)
    )


def macsec_links(
    tunnel: Tunnel, at_port: Mapping[tuple[str, str], Link]
) -> tuple[Link, ...]:
    """The links a MACsec connection is carried on.

    Args:
        tunnel: A MACsec connection.
        at_port: The link at each device interface.

    Returns:
        The link at its A end, and at its B end when that is another
        circuit into the same layer-2 transport.

    Raises:
        None
    """
    here = at_port.get((tunnel.a.device, tunnel.a.interface))
    b = tunnel.b
    there = at_port.get((b.device, b.interface)) if isinstance(b, TunnelEnd) else None
    if here is None:
        return ()
    return (here,) if there is None or there is here else (here, there)


def ports(topology: Topology) -> dict[tuple[str, str], Link]:
    """The link at each device interface a link uses.

    Args:
        topology: A topology.

    Returns:
        Each link by its device ends' (device, interface).

    Raises:
        None
    """
    return {
        (e.device, e.interface): ln for ln in topology.links for e in device_ends(ln)
    }


def leaf_key(link: Link) -> str:
    """The node an E-Tree leaf's circuit leads to: its own corner of the
    transport, which only the roots' circuits reach.

    Args:
        link: A circuit into a transport.

    Returns:
        ``transport:NAME~`` and the circuit's id.

    Raises:
        None
    """
    return f"{end_key(link.b)}~{link.id}"


def transport_hops(
    links: Iterable[Link], transports: Iterable[Transport]
) -> dict[str, list[tuple[str, str]]]:
    """How each circuit into a transport joins nodes, for reach and paths.

    A circuit for transit (or still TBD) leads to its transport's node, as
    to a device. Into an E-Tree, a leaf's circuit leads to a node of its
    own, which each root's circuit reaches too: so leaves reach the roots,
    and each other only through a root's router, and are cut off from the
    E-Tree when no root is reached. Circuits for something else join nothing.

    Args:
        links: Every link.
        transports: Every transport.

    Returns:
        The node pairs each joining circuit into a transport makes, by link
        id, each from its device.

    Raises:
        None
    """
    trees = {t.name for t in transports if t.service == "e-tree"}
    into = [ln for ln in links if isinstance(ln.b, TransportEnd) and joins(ln)]
    leaves: dict[str, list[Link]] = {}
    for ln in into:
        b = ln.b
        if isinstance(b, TransportEnd) and b.transport in trees and b.role != "root":
            leaves.setdefault(b.transport, []).append(ln)
    found: dict[str, list[tuple[str, str]]] = {}
    for ln in into:
        b = ln.b
        if not isinstance(b, TransportEnd):
            continue
        device, cloud = ln.a.device, end_key(b)
        if b.transport not in trees:
            found[ln.id] = [(device, cloud)]
        elif b.role == "root":
            found[ln.id] = [(device, cloud)] + [
                (device, leaf_key(leaf)) for leaf in leaves.get(b.transport, [])
            ]
        else:
            found[ln.id] = [(device, leaf_key(ln))]
    return found


def cid(link: Link) -> str | None:
    """The ID a connection is named by: the enterprise's own CID, else the
    carrier's, at the A side.

    Args:
        link: The link.

    Returns:
        The ID, or None if it has neither.

    Raises:
        None
    """
    if link.enterprise_cid is not None:
        return link.enterprise_cid.a
    return link.circuit.circuit_id.a if link.circuit else None
