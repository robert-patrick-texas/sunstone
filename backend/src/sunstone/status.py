"""Whether the network, each named network, and their groups are working.

Everything is a node or a link, and nodes and links are gathered into
groups: locations inside sites, sites inside regions, regions inside
regions, and the whole. A link belongs to the lowest group holding both its
ends; a circuit into a transport, or a link to an external node, to the
whole. A named network is a tree of the same groups over its own sites,
with its own regions if it has them.

A group is operational, degraded, or offline:

1. A device down degrades its own group. A link or tunnel down degrades the
   group it belongs to, and every group below that one holding one of its
   ends.
2. A group no anchor reaches is offline, and every group above it is
   degraded. A named network is offline when no two of its sites reach
   each other.
3. A degraded group does not degrade the one above it by itself.
4. A group whose parts reach each other less well inside it than they do
   when everything works is partitioned, which is degraded.

A named network whose own groups are all operational, but which rides one
that is degraded at its sites, reads operational with a caveat naming what
is degraded beneath it.

A cable's or circuit's priority limits rule 1: an ``ignored`` one down
degrades nothing, and a ``low`` one only its locations and sites. A device
rated ``ignored`` counts toward no group: its going down degrades nothing,
and a group of none but such devices is never offline or partitioned. Reach
goes through them all the same, so what one cuts off counts.

A resource is operational when all its members are: each circuit up with
its device reached from the core, each tunnel up with its device reached,
each fabric's tunnels all up, and each resource inside it operational. It
is offline when none of them can be used, and degraded otherwise.
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from sunstone.layers import Edge, Layers, fabric_tunnel_id, fabric_tunnels, reach_edges
from sunstone.live import TunnelState
from sunstone.model import (
    Resource,
    Topology,
    TunnelEnd,
    circuits_by_cid,
    device_ends,
    ratings,
)
from sunstone.problems import LiveView, link_name

Status = Literal["operational", "degraded", "offline"]
GroupKind = Literal["network", "region", "site", "location"]
MemberKind = Literal["circuit", "tunnel", "fabric", "resource"]
ROOT = "network"
MAX_REASONS = 6


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GroupStatus(_Record):
    """A region, site, or location that is not working as it should."""

    kind: GroupKind
    id: str
    """A region's name, a site's code, or ``SITE/location``."""
    name: str
    status: Status
    reasons: list[str]


class NetworkStatus(_Record):
    """The whole network, or one named network, and its groups."""

    network: str | None
    """The named network, or None for the whole."""
    name: str
    status: Status
    reasons: list[str]
    caveats: list[str]
    """What is degraded under it at its sites, while it works itself."""
    groups: list[GroupStatus]
    """Its groups that are not operational, regions first, then sites."""
    sites: int
    reached: int
    """Sites reached from its anchors."""
    tunnels_down: list[str]


class MemberStatus(_Record):
    """One of a resource's members, and whether it can be used."""

    kind: MemberKind
    name: str
    """A circuit's CID, or a tunnel's, fabric's, or resource's name."""
    status: Status
    reason: str | None = None
    """Why it is not operational: ``down``, ``cut off``, ``degraded``,
    ``offline``, or what is down (``iad-wan-01 down``, ``3 of 20 tunnels
    down``)."""
    link: str | None = None
    """For a circuit, its link's id."""


class ResourceStatus(_Record):
    """A resource's status, from its members'."""

    name: str
    status: Status
    reasons: list[str]
    members: list[MemberStatus]


class StatusReport(_Record):
    """Every network's status at a moment."""

    at: datetime
    whole: NetworkStatus
    networks: list[NetworkStatus]
    resources: list[ResourceStatus] = []


@dataclass
class _Tree:
    """Groups and their parents, and the leaf group each device is in."""

    parent: dict[str, str]
    leaf: dict[str, str]
    names: dict[str, str]
    # Each group's chain, worked out once: a status asks for them for every
    # device and link, tens of thousands of times on a large network.
    _chains: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def up(self, group: str) -> tuple[str, ...]:
        """A group and every group above it, to the whole."""
        found = self._chains.get(group)
        if found is None:
            chain = [group]
            while chain[-1] != ROOT:
                chain.append(self.parent.get(chain[-1], ROOT))
            found = self._chains[group] = tuple(chain)
        return found


class Statuses:
    """Works out status for a topology, from each snapshot."""

    def __init__(self, topology: Topology, layers: Layers | None = None) -> None:
        """Index a topology's groups.

        Args:
            topology: The network.
            layers: Its named networks, if already indexed.

        Raises:
            None
        """
        self.topology = topology
        self.layers = layers or Layers(topology)
        self.site_of = {d.name: d.site for d in topology.devices}
        self.cores = {d.name for d in topology.devices if d.role == "core"}
        core_sites = {self.site_of[d] for d in self.cores}
        self.links = {link.id: link for link in topology.links}
        self.priority = {i: r.priority for i, r in ratings(topology).items()}
        # Devices rated ignored count toward no group, though reach still
        # goes through them.
        self.quiet = {d.name for d in topology.devices if d.priority == "ignored"}
        self.whole_tree = self._tree(None)
        self.trees = {n.name: self._tree(n.name) for n in topology.networks}
        self.anchors: dict[str, set[str]] = {}
        for n in topology.networks:
            devices = self.layers.slices[n.name].devices
            sites = set(n.anchors) or core_sites
            self.anchors[n.name] = {d for d in devices if self.site_of[d] in sites}
        self.network_rides = {n.name: n.rides for n in topology.networks if n.rides}
        # How well each group's parts reach each other inside it when
        # everything works, to tell a partition from how it is built.
        self._healthy: dict[str | None, dict[str, int]] = {}

    def _tree(self, network: str | None) -> _Tree:
        """The groups of the whole, or of a named network over its sites."""
        t = self.topology
        parent: dict[str, str] = {}
        names = {ROOT: t.name or "Network"} if network is None else {ROOT: network}
        own = {}
        if network is not None:
            n = next(x for x in t.networks if x.name == network)
            own = {
                code: region for region, sites in n.regions.items() for code in sites
            }
        regions = {r.name: r.parent for r in t.regions}
        for site in t.sites:
            sid = f"site:{site.code}"
            names[sid] = site.code
            region = own.get(site.code) if own else site.region
            parent[sid] = f"region:{region}" if region else ROOT
            chain = region
            while chain:
                rid = f"region:{chain}"
                names[rid] = chain
                above = None if own else regions.get(chain)
                parent[rid] = f"region:{above}" if above else ROOT
                chain = above
        for x in t.locations:
            lid = f"location:{x.site}/{x.name}"
            names[lid] = x.name
            parent[lid] = (
                f"location:{x.site}/{x.parent}" if x.parent else f"site:{x.site}"
            )
        leaf = {
            d.name: f"location:{d.site}/{d.location}"
            if d.location
            else f"site:{d.site}"
            for d in t.devices
        }
        return _Tree(parent=parent, leaf=leaf, names=names)

    def report(self, at: datetime, view: LiveView) -> StatusReport:
        """Every network's status in a snapshot.

        Args:
            at: The snapshot's moment.
            view: The snapshot.

        Returns:
            The whole network's status, and each named network's, bottom up.

        Raises:
            None
        """
        down = {d for d in self.site_of if view.health(d) == "down"}
        cut = {i for i, link in self.links.items() if view.link(link).health == "down"}
        return self.of(at, down, cut, view.state.tunnels)

    def of(
        self,
        at: datetime,
        down: set[str],
        cut: set[str],
        tunnels: Iterable[TunnelState],
    ) -> StatusReport:
        """Every network's status, given what is down.

        Args:
            at: The moment it is for.
            down: Devices down.
            cut: Links down, by id.
            tunnels: The tunnels' states; a tunnel left out is taken to be up.

        Returns:
            The whole network's status, and each named network's, bottom up.

        Raises:
            None
        """
        states = list(tunnels)
        whole_edges = reach_edges(self.topology.links, self.layers.hops)
        whole = self._status(
            None, self.whole_tree, set(self.site_of), whole_edges, down, cut, self.cores
        )
        return StatusReport(
            at=at,
            whole=whole,
            networks=self.named(down, cut, states),
            resources=self.resources(down, cut, states),
        )

    def resources(
        self, down: set[str], cut: set[str], tunnels: Iterable[TunnelState]
    ) -> list[ResourceStatus]:
        """Each resource's status, given what is down.

        Args:
            down: Devices down.
            cut: Links down, by id.
            tunnels: The tunnels' states; a tunnel left out is taken to be up.

        Returns:
            Each resource's status, in the topology's order.

        Raises:
            None
        """
        if not self.topology.resources:
            return []
        gone = {t.tunnel for t in tunnels if t.status == "down"}
        edges = reach_edges(self.topology.links, self.layers.hops)
        live = [
            e for e in edges if e.id not in cut and e.a not in down and e.b not in down
        ]
        reached = _reach(live, self.cores - down, set(self.site_of) - down)
        judge = _Members(self.topology, down, cut, gone, reached)
        return [judge.resource(r.name) for r in self.topology.resources]

    def named(
        self, down: set[str], cut: set[str], tunnels: Iterable[TunnelState]
    ) -> list[NetworkStatus]:
        """Each named network's status, given what is down, without the
        whole network's, which takes most of the work on a large network.

        Args:
            down: Devices down.
            cut: Links down, by id.
            tunnels: The tunnels' states; a tunnel left out is taken to be up.

        Returns:
            Each named network's status, bottom up.

        Raises:
            None
        """
        states = list(tunnels)
        gone = {t.tunnel for t in states if t.status == "down"}
        found: dict[str, NetworkStatus] = {}
        joined: dict[str, dict[str, str]] = {}
        for name in self.layers.order:
            s = self.layers.slices[name]
            # Its links and tunnels, and the spoke-to-spoke tunnels up now.
            edges = self.layers.link_edges(name) + self.layers.tunnel_edges(name)
            for t in states:
                if t.network == name and t.dynamic and t.status == "up":
                    a, b = t.tunnel.split(":", 1)[1].split("~")
                    edges.append(Edge(t.tunnel, a, b, tunnel=True, dynamic=True))
            # A network riding another without tunnels of its own, as a
            # tenant's does, reaches across what it rides as that does now.
            for under in self.network_rides.get(name, ()):
                for d in s.devices:
                    part = joined.get(under, {}).get(d)
                    if part is not None:
                        edges.append(Edge(f"over {under}", d, f"{under}#{part}"))
            live = [
                e
                for e in edges
                if e.id not in cut | gone and e.a not in down and e.b not in down
            ]
            joined[name] = _components(live)
            found[name] = self._status(
                name,
                self.trees[name],
                s.devices,
                edges,
                down,
                cut | gone,
                self.anchors[name],
            )
        return [self._with_caveats(found[n], found) for n in self.layers.order]

    def reached(self, network: str, down: set[str], cut: set[str]) -> set[str]:
        """The sites of a named network its anchors reach around some
        failures, through its links and the tunnels that are always there.

        Args:
            network: The named network.
            down: Devices down.
            cut: Links and tunnels down, by id.

        Returns:
            Site codes.

        Raises:
            None
        """
        s = self.layers.slices[network]
        edges = self.layers.link_edges(network) + self.layers.tunnel_edges(network)
        live = [
            e for e in edges if e.id not in cut and e.a not in down and e.b not in down
        ]
        found = _reach(live, self.anchors[network] - down, s.devices - down)
        return {self.site_of[d] for d in found}

    def _status(
        self,
        network: str | None,
        tree: _Tree,
        members: set[str],
        edges: list[Edge],
        down: set[str],
        cut: set[str],
        anchors: set[str],
    ) -> NetworkStatus:
        """One network's status, by the rules in the module's description."""
        reasons: dict[str, list[str]] = defaultdict(list)
        live = [
            e for e in edges if e.id not in cut and e.a not in down and e.b not in down
        ]
        reached = _reach(live, anchors - down, members - down)
        counted = members - self.quiet

        def group_of(node: str) -> str:
            # A transport or external node is in no group but the whole.
            return tree.leaf.get(node, ROOT)

        # Rule 1: what is down degrades its groups.
        for d in sorted(down & counted):
            reasons[group_of(d)].append(f"{d} down")
        for e in edges:
            if e.id not in cut:
                continue
            # A cable's or circuit's priority limits how far it climbs.
            priority = self.priority.get(e.id, "medium")
            if priority == "ignored":
                continue
            ends = [tree.up(group_of(e.a)), tree.up(group_of(e.b))]
            owner = next(g for g in ends[0] if g in ends[1])
            what = self._name(e)
            for chain in ends:
                for g in chain[: chain.index(owner) + 1]:
                    if priority == "low" and _kind(g) not in ("site", "location"):
                        break
                    if what not in reasons[g]:
                        reasons[g].append(what)
        # Rule 2: groups no anchor reaches are offline; those above, degraded.
        holds: dict[str, set[str]] = defaultdict(set)
        for d in counted:
            for g in tree.up(group_of(d)):
                holds[g].add(d)
        offline = {g for g, ds in holds.items() if g != ROOT and not ds & reached}
        for g in sorted(offline):
            for above in tree.up(g)[1:]:
                if above not in offline:
                    reasons[above].append(f"{tree.names.get(g, g)} offline")
        sites = {self.site_of[d] for d in counted}
        sites_reached = {self.site_of[d] for d in reached}
        # The whole is offline when no two of its sites reach each other,
        # wherever its anchors are: sites cut off from them still work together.
        parts = _components(live)
        together: dict[str, set[str]] = defaultdict(set)
        for d in counted - down:
            together[parts.get(d, d)].add(self.site_of[d])
        needed = 2 if len(sites) > 1 else 1
        whole_offline = max(map(len, together.values()), default=0) < needed
        if whole_offline:
            reasons[ROOT].insert(
                0, "no two sites reach each other" if needed == 2 else "unreachable"
            )
        # Rule 4: partitioned.
        healthy = self._healthy.get(network)
        if healthy is None:
            # Spoke-to-spoke tunnels come and go: no part of how it is built.
            built = [e for e in edges if not e.dynamic]
            healthy = self._healthy[network] = _parts(tree, built, counted)
        now = _parts(tree, live, reached & counted)
        for g, parts in now.items():
            if g not in offline and parts > healthy.get(g, 1):
                reasons[g].append(f"partitioned into {parts} parts")
        groups = [
            GroupStatus(
                kind=_kind(g),
                id=g.split(":", 1)[1],
                name=tree.names.get(g, g),
                status="offline" if g in offline else "degraded",
                reasons=_short(reasons[g]),
            )
            for g in sorted(set(reasons) | offline, key=_order)
            if g != ROOT and g in holds
        ]
        status: Status = (
            "offline"
            if whole_offline
            else "degraded"
            if reasons[ROOT] or offline
            else "operational"
        )
        return NetworkStatus(
            network=network,
            name=tree.names[ROOT],
            status=status,
            reasons=_short(reasons[ROOT]),
            caveats=[],
            groups=groups,
            sites=len(sites),
            reached=len(sites_reached),
            tunnels_down=sorted(e.id for e in edges if e.tunnel and e.id in cut),
        )

    def _with_caveats(
        self, own: NetworkStatus, found: dict[str, NetworkStatus]
    ) -> NetworkStatus:
        """A network's status, with what is degraded beneath it at its sites."""
        if own.network is None:
            return own
        mine = {self.site_of[d] for d in self.layers.slices[own.network].devices}
        caveats = []
        for under in sorted(self.layers.beneath([own.network])):
            for g in found[under].groups:
                if g.kind == "site" and g.id in mine:
                    first = f": {g.reasons[0]}" if g.reasons else ""
                    caveats.append(f"{under} {g.status} at {g.id}{first}")
        return own.model_copy(update={"caveats": caveats})

    def _name(self, edge: Edge) -> str:
        link = self.links.get(edge.id)
        if link:
            return f"{link_name(link)} down"
        fabric, colon, ends = edge.id.partition(":")
        if colon:
            a, _, b = ends.partition("~")
            return f"{fabric}: {a} – {b} down"
        return f"{edge.id} down"


class _Members:
    """Works out whether each resource's members can be used, given what
    is down."""

    def __init__(
        self,
        topology: Topology,
        down: set[str],
        cut: set[str],
        gone: set[str],
        reached: set[str],
    ) -> None:
        self.down = down
        self.cut = cut
        self.gone = gone
        self.reached = reached
        self.by_cid = circuits_by_cid(topology.links)
        self.tunnels = {t.name: t for t in topology.tunnels}
        self.fabrics = {f.name: f for f in topology.fabrics}
        self.defined: dict[str, Resource] = {r.name: r for r in topology.resources}
        self.done: dict[str, ResourceStatus] = {}

    def _ends(self, devices: list[str]) -> tuple[Status, str | None]:
        """Whether a connection up between some devices can be used."""
        for d in devices:
            if d in self.down:
                return "offline", f"{d} down"
        if not any(d in self.reached for d in devices):
            return "offline", "cut off"
        return "operational", None

    def circuit(self, cid: str) -> MemberStatus:
        """A circuit by its CID: usable while up and its device is reached."""
        link = self.by_cid[cid][0]
        if link.id in self.cut:
            status: Status = "offline"
            reason: str | None = "down"
        else:
            status, reason = self._ends([e.device for e in device_ends(link)])
        return MemberStatus(
            kind="circuit", name=cid, status=status, reason=reason, link=link.id
        )

    def tunnel(self, name: str) -> MemberStatus:
        """A tunnel: usable while up and its device is reached."""
        t = self.tunnels[name]
        if name in self.gone:
            return MemberStatus(
                kind="tunnel", name=name, status="offline", reason="down"
            )
        ends = [t.a.device] + ([t.b.device] if isinstance(t.b, TunnelEnd) else [])
        status, reason = self._ends(ends)
        return MemberStatus(kind="tunnel", name=name, status=status, reason=reason)

    def fabric(self, name: str) -> MemberStatus:
        """A fabric: operational with all its tunnels up, offline with none,
        and degraded in between; a group (no tunnels) by its members."""
        f = self.fabrics[name]
        pairs = fabric_tunnels(f)
        if pairs:
            usable = sum(
                1
                for a, b in pairs
                if fabric_tunnel_id(f, a, b) not in self.gone
                and self._ends([a.device, b.device])[0] == "operational"
            )
            total, what = len(pairs), "tunnels"
        else:
            usable = sum(
                1 for m in f.members if self._ends([m.device])[0] == "operational"
            )
            total, what = len(f.members), "members"
        lost = total - usable
        if not lost:
            return MemberStatus(kind="fabric", name=name, status="operational")
        status: Status = "offline" if not usable else "degraded"
        reason = (
            f"all {total} {what} down"
            if not usable
            else f"{lost} of {total} {what} down"
        )
        return MemberStatus(kind="fabric", name=name, status=status, reason=reason)

    def resource(self, name: str) -> ResourceStatus:
        """A resource's status, from its members', inner resources first."""
        found = self.done.get(name)
        if found is not None:
            return found
        r = self.defined[name]
        members = [
            *(self.circuit(c) for c in r.circuits),
            *(self.tunnel(t) for t in r.tunnels),
            *(self.fabric(f) for f in r.fabrics),
            *(self._inner(x) for x in r.resources),
        ]
        usable = [m for m in members if m.status != "offline"]
        status: Status = (
            "operational"
            if all(m.status == "operational" for m in members)
            else "offline"
            if not usable
            else "degraded"
        )
        reasons = [_member_reason(m) for m in members if m.status != "operational"]
        found = self.done[name] = ResourceStatus(
            name=name, status=status, reasons=_short(reasons), members=members
        )
        return found

    def _inner(self, name: str) -> MemberStatus:
        inner = self.resource(name)
        reason = None if inner.status == "operational" else inner.status
        return MemberStatus(
            kind="resource", name=name, status=inner.status, reason=reason
        )


def _member_reason(member: MemberStatus) -> str:
    """Why a resource is not operational, for one of its members:
    ``DAL-REN-01 down``, ``IAD-INET-01: iad-wan-01 down``."""
    reason = member.reason or member.status
    if reason in ("down", "cut off", "degraded", "offline"):
        return f"{member.name} {reason}"
    return f"{member.name}: {reason}"


def _reach(edges: list[Edge], start: set[str], members: set[str]) -> set[str]:
    """Members reached from the anchors; without anchors up, the largest
    group of members that reach each other."""
    adjacent: dict[str, list[str]] = defaultdict(list)
    for e in edges:
        adjacent[e.a].append(e.b)
        adjacent[e.b].append(e.a)

    def spread(seeds: Iterable[str]) -> set[str]:
        seen = set(seeds)
        stack = list(seen)
        while stack:
            for n in adjacent[stack.pop()]:
                if n not in seen:
                    seen.add(n)
                    stack.append(n)
        return seen

    if start:
        return spread(start) & members
    best: set[str] = set()
    left = set(members)
    while left:
        part = spread([left.pop()])
        left -= part
        if len(part & members) > len(best):
            best = part & members
    return best


def resources_needing(report: StatusReport) -> list[ResourceStatus]:
    """The resources that need someone: degraded or offline.

    Args:
        report: Every network's and resource's status.

    Returns:
        Those resources, offline first, in the topology's order.
    """
    return sorted(
        (r for r in report.resources if r.status != "operational"),
        key=lambda r: r.status != "offline",
    )


def needing(report: StatusReport) -> list[NetworkStatus]:
    """The networks that need someone: not operational, or working over
    something degraded.

    Args:
        report: Every network's status.

    Returns:
        Those networks, offline first, then degraded, then working with a
        caveat, the whole network first among equals.
    """
    rank = {"offline": 0, "degraded": 1, "operational": 2}
    found = [report.whole, *report.networks]
    return sorted(
        (n for n in found if n.status != "operational" or n.caveats),
        key=lambda n: (rank[n.status], n.network is not None),
    )


def _components(edges: list[Edge]) -> dict[str, str]:
    """Which part each node is in, by a representative node of it."""
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for e in edges:
        parent[find(e.a)] = find(e.b)
    return {n: find(n) for n in list(parent)}


def _parts(tree: _Tree, edges: list[Edge], present: set[str]) -> dict[str, int]:
    """For each group with parts, how many pieces its parts fall into using
    only the links and tunnels inside it. Its parts are the groups directly
    inside it, each taken as one, and the devices in it directly: a site
    split inside is that site's own outage, not its region's. A transport
    joins the circuits into it, which belong to the whole."""
    # The parts of each group that hold a device present, and how many
    # devices are present in it.
    parts: dict[str, set[str]] = defaultdict(set)
    count: dict[str, int] = defaultdict(int)
    for d in present:
        chain = tree.up(tree.leaf.get(d, ROOT))
        for i, g in enumerate(chain):
            parts[g].add(chain[i - 1] if i else d)
            count[g] += 1

    def joins(node: str) -> bool:
        return node in present or node.startswith("transport:")

    # Only the links and tunnels a group owns can join its parts: one further
    # down lies inside one of them. Each joins the parts its ends are in.
    owned: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for e in edges:
        if not joins(e.a) or not joins(e.b):
            continue
        ends = [tree.up(tree.leaf.get(e.a, ROOT)), tree.up(tree.leaf.get(e.b, ROOT))]
        owner = next(g for g in ends[0] if g in ends[1])
        owned[owner].append((_part(ends[0], owner, e.a), _part(ends[1], owner, e.b)))
    return {g: _pieces(mine, owned[g]) for g, mine in parts.items() if count[g] >= 2}


def _part(chain: tuple[str, ...], group: str, node: str) -> str:
    """The part of a group a node is in: the group directly inside it
    holding the node, or the node itself."""
    i = chain.index(group)
    return chain[i - 1] if i > 0 else node


def _pieces(nodes: set[str], pairs: list[tuple[str, str]]) -> int:
    """How many pieces some nodes fall into, joined in pairs. A pair may join
    through a node outside them, as a transport does."""
    parent = {n: n for n in nodes}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in pairs:
        parent[find(a)] = find(b)
    return len({find(n) for n in nodes})


KINDS: dict[str, GroupKind] = {
    "network": "network",
    "region": "region",
    "site": "site",
    "location": "location",
}


def _kind(group: str) -> GroupKind:
    return KINDS[group.split(":", 1)[0]]


def _order(group: str) -> tuple[int, str]:
    rank = {"network": 0, "region": 1, "site": 2, "location": 3}
    return rank[group.split(":", 1)[0]], group


def _short(reasons: list[str]) -> list[str]:
    if len(reasons) <= MAX_REASONS:
        return reasons
    return [*reasons[: MAX_REASONS - 1], f"and {len(reasons) - MAX_REASONS + 1} more"]
