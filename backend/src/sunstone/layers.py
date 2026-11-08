"""Named networks over the links, and which of their tunnels are up.

A network's slice is everything that carries it: the links that say so
(and circuits into a transport whose network it is), its own tunnels and
fabrics, and the devices these touch. A device joins its points in one
network, and nothing more: a switch carrying grey and black keeps them
apart, and only a tunnel crosses from one network to another.

A tunnel is up when its two ends reach each other through the network it
rides, with what has failed left out; its own fault (an IKE negotiation
that fails, say) takes it down too. Networks are worked out from the bottom
up, so a tunnel riding blue uses blue's tunnels as they are.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from sunstone.model import (
    Endpoint,
    ExternalEnd,
    Fabric,
    FabricMember,
    Link,
    Topology,
    TransportEnd,
    Tunnel,
    TunnelEnd,
    device_ends,
    end_key,
    leaf_key,
    macsec_links,
    ports,
    transport_hops,
)


@dataclass(frozen=True)
class Edge:
    """A way between two nodes of a network: a link, or a tunnel."""

    id: str
    a: str
    """A device, or a transport by its ``transport:`` key."""
    b: str
    """A device, a transport, or an external node, by its key."""
    tunnel: bool = False
    dynamic: bool = False
    """A tunnel built on demand, spoke to spoke."""


@dataclass
class Slice:
    """One named network: its links, tunnels, and devices."""

    name: str
    links: list[Link] = field(default_factory=list)
    tunnels: list[Tunnel] = field(default_factory=list)
    fabrics: list[Fabric] = field(default_factory=list)
    devices: set[str] = field(default_factory=set)
    rides: set[str] = field(default_factory=set)
    depth: int = 0


def fabric_tunnel_id(fabric: Fabric, a: FabricMember, b: FabricMember) -> str:
    """How a tunnel a fabric is made of is named.

    Args:
        fabric: The fabric.
        a: One member, a spoke where there are hubs.
        b: The other, a hub where there are hubs.

    Returns:
        ``FABRIC:a~b``, with the members' devices.
    """
    return f"{fabric.name}:{a.device}~{b.device}"


def fabric_tunnels(fabric: Fabric) -> list[tuple[FabricMember, FabricMember]]:
    """The tunnels a fabric is made of, apart from any built on demand.

    Args:
        fabric: The fabric.

    Returns:
        Each spoke with each hub, or every pair for a full mesh; none for a
        group, whose members reach each other directly.
    """
    members = fabric.members
    if fabric.shape == "group":
        return []
    if fabric.shape == "full-mesh":
        return [(a, b) for i, a in enumerate(members) for b in members[i + 1 :]]
    hubs = [m for m in members if m.role == "hub"]
    return [(s, h) for s in members if s.role == "spoke" for h in hubs]


def spoke_pairs(fabric: Fabric) -> list[tuple[FabricMember, FabricMember]]:
    """Spokes that can build tunnels to each other on demand.

    Args:
        fabric: The fabric.

    Returns:
        Every pair of spokes, for a hub-spoke-dynamic fabric; else none.
    """
    if fabric.shape != "hub-spoke-dynamic":
        return []
    spokes = [m for m in fabric.members if m.role == "spoke"]
    return [(a, b) for i, a in enumerate(spokes) for b in spokes[i + 1 :]]


class Layers:
    """A topology's named networks, indexed to work out their tunnels."""

    def __init__(self, topology: Topology) -> None:
        """Index a topology's networks.

        Args:
            topology: The network.

        Raises:
            None
        """
        self.topology = topology
        own = {t.name: t.network for t in topology.transports}
        self.slices: dict[str, Slice] = {
            n.name: Slice(n.name, rides=set(n.rides)) for n in topology.networks
        }
        for link in topology.links:
            names = {c.network for c in link.carries}
            if isinstance(link.b, TransportEnd) and own.get(link.b.transport):
                names.add(own[link.b.transport] or "")
            for name in names:
                if name in self.slices:
                    self.slices[name].links.append(link)
                    self.slices[name].devices.update(
                        e.device for e in device_ends(link)
                    )
        # A link to a tenant's node is part of the tenant's network too: its
        # points are where its nodes are handed off.
        owner = {e.name: e.network for e in topology.externals if e.network}
        for link in topology.links:
            b = link.b
            name = owner.get(b.external) if isinstance(b, ExternalEnd) else None
            if name and link not in self.slices[name].links:
                self.slices[name].links.append(link)
                self.slices[name].devices.add(link.a.device)
        for t in topology.tunnels:
            s = self.slices[t.network]
            s.tunnels.append(t)
            s.rides.add(t.rides)
            s.devices.add(t.a.device)
            if isinstance(t.b, TunnelEnd):
                s.devices.add(t.b.device)
        for f in topology.fabrics:
            s = self.slices[f.network]
            s.fabrics.append(f)
            s.rides.add(f.rides)
            s.devices.update(m.device for m in f.members)
        for s in self.slices.values():
            s.depth = self._depth(s.name, frozenset())
        self.order = sorted(self.slices, key=lambda n: (self.slices[n].depth, n))
        self.hops = transport_hops(topology.links, topology.transports)
        """How each circuit into a transport joins nodes (an E-Tree's leaves
        only to its roots)."""
        at_port = ports(topology)
        self.secured: dict[str, tuple[str, ...]] = {
            t.name: tuple(ln.id for ln in macsec_links(t, at_port))
            for t in topology.tunnels
            if t.kind == "macsec"
        }
        """The links each MACsec connection is carried on, by id."""

    def _depth(self, name: str, seen: frozenset[str]) -> int:
        s = self.slices.get(name)
        if s is None or name in seen:
            return 0
        under = [self._depth(r, seen | {name}) + 1 for r in s.rides]
        return max(under, default=0)

    def beneath(self, names: Iterable[str]) -> set[str]:
        """Every network some networks ride, at any depth.

        Args:
            names: The networks.

        Returns:
            The networks under them, not counting any of them.
        """
        chosen = set(names)
        found: set[str] = set()
        stack = list(chosen)
        while stack:
            for r in self.slices.get(stack.pop(), Slice("")).rides:
                if r not in found:
                    found.add(r)
                    stack.append(r)
        return found - chosen

    def tunnel_edges(self, name: str) -> list[Edge]:
        """A network's tunnels as edges: its own, and those its fabrics are
        made of, apart from any built on demand.

        Args:
            name: The network.

        Returns:
            One edge per tunnel, between its ends' devices, or to an
            external node's key.
        """
        s = self.slices[name]
        edges = [
            Edge(
                t.name,
                t.a.device,
                t.b.device
                if isinstance(t.b, TunnelEnd)
                else f"external:{t.b.external}",
                tunnel=True,
            )
            for t in s.tunnels
        ]
        edges += [
            Edge(fabric_tunnel_id(f, a, b), a.device, b.device, tunnel=True)
            for f in s.fabrics
            for a, b in fabric_tunnels(f)
        ]
        return edges

    def all_tunnels(self) -> list[tuple[str, str]]:
        """Every tunnel that is always there, with its network.

        Returns:
            Each point-to-point tunnel by name, and each tunnel a fabric is
            made of by :func:`fabric_tunnel_id`, in network order.
        """
        found = []
        for name in self.order:
            s = self.slices[name]
            found += [(t.name, name) for t in s.tunnels]
            found += [
                (fabric_tunnel_id(f, a, b), name)
                for f in s.fabrics
                for a, b in fabric_tunnels(f)
            ]
        return found

    def link_edges(self, name: str) -> list[Edge]:
        """A network's links as edges.

        Args:
            name: The network.

        Returns:
            An edge per link, as :func:`reach_edges` gives them.
        """
        return reach_edges(self.slices[name].links, self.hops)

    def tunnels_up(
        self,
        down: set[str],
        cut: set[str],
        failing: Iterable[str] = (),
        dynamic: Iterable[str] = (),
    ) -> dict[str, bool]:
        """Which tunnels are up, around what has failed.

        Args:
            down: Devices down.
            cut: Links down, by id.
            failing: Tunnels down of their own accord, by id.
            dynamic: Spoke-to-spoke tunnels built on demand now, by
                :func:`fabric_tunnel_id`.

        Returns:
            Every tunnel by id, and whether it is up: point-to-point tunnels,
            those fabrics are made of, and those built on demand.
        """
        built, failed = set(dynamic), set(failing)
        up: dict[str, bool] = {}
        reach: dict[str, _Components] = {}
        for name in self.order:
            s = self.slices[name]
            edges = [
                e
                for e in self.link_edges(name)
                if e.id not in cut and e.a not in down and e.b not in down
            ]
            for t in s.tunnels:
                far = t.b.device if isinstance(t.b, TunnelEnd) else None
                if t.kind == "macsec":
                    # Up while the links it is carried on are, end to end.
                    ok = not ({t.a.device, far} & down) and not (
                        set(self.secured[t.name]) & cut
                    )
                else:
                    ok = self._through(reach, t.rides, t.a.device, far, down)
                up[t.name] = ok and t.name not in failed
                if up[t.name]:
                    target = (
                        t.b.device
                        if isinstance(t.b, TunnelEnd)
                        else f"external:{t.b.external}"
                    )
                    edges.append(Edge(t.name, t.a.device, target, tunnel=True))
            for f in s.fabrics:
                pairs = fabric_tunnels(f) + [
                    p for p in spoke_pairs(f) if fabric_tunnel_id(f, *p) in built
                ]
                for a, b in pairs:
                    tid = fabric_tunnel_id(f, a, b)
                    ok = self._through(reach, f.rides, a.device, b.device, down)
                    up[tid] = ok and tid not in failed
                    if up[tid]:
                        edges.append(Edge(tid, a.device, b.device, tunnel=True))
            reach[name] = _Components(edges)
        return up

    def _through(
        self,
        reach: dict[str, _Components],
        rides: str,
        a: str,
        b: str | None,
        down: set[str],
    ) -> bool:
        """Whether two devices reach each other through a network; with no
        far device, whether the first reaches any transport through it."""
        if a in down or (b is not None and b in down):
            return False
        under = reach.get(rides)
        if under is None:
            return False
        if b is not None:
            return under.joined(a, b)
        clouds = [n for n in under.nodes if n.startswith("transport:")]
        return any(under.joined(a, c) for c in clouds) if clouds else True


class _Components:
    """Which nodes of a network reach each other, by union-find."""

    def __init__(self, edges: list[Edge]) -> None:
        self.parent: dict[str, str] = {}
        for e in edges:
            self._union(e.a, e.b)

    @property
    def nodes(self) -> list[str]:
        return list(self.parent)

    def _find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def _union(self, a: str, b: str) -> None:
        ra, rb = self._find(a), self._find(b)
        if ra != rb:
            self.parent[ra] = rb

    def joined(self, a: str, b: str) -> bool:
        if a not in self.parent or b not in self.parent:
            return False
        return self._find(a) == self._find(b)


def reach_edges(
    links: Iterable[Link], hops: Mapping[str, list[tuple[str, str]]]
) -> list[Edge]:
    """Links as the edges reach goes by.

    Args:
        links: The links.
        hops: How each circuit into a transport joins nodes, from
            :func:`transport_hops`.

    Returns:
        An edge per link, from its device to its far end's key; a circuit
        into a transport that is not for transit leads to a cloud of its
        own, joining it to nothing else; and into an E-Tree, a leaf's
        circuit leads to a corner of its own, which each root's circuit
        reaches too.
    """
    edges = []
    for link in links:
        pairs = hops.get(link.id)
        if pairs is not None:
            edges += [Edge(link.id, a, b) for a, b in pairs]
        elif isinstance(link.b, TransportEnd):
            edges.append(Edge(link.id, link.a.device, leaf_key(link)))
        else:
            edges.append(Edge(link.id, link.a.device, far_key(link)))
    return edges


def far_key(link: Link) -> str:
    """A link's B end as a node: its device, or its transport's or external
    node's key.

    Args:
        link: The link.

    Returns:
        The device's name, or ``transport:NAME`` or ``external:NAME``.
    """
    return link.b.device if isinstance(link.b, Endpoint) else end_key(link.b)
