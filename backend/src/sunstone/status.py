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
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from sunstone.layers import Edge, Layers, far_key
from sunstone.model import Topology
from sunstone.problems import LiveView, link_name

Status = Literal["operational", "degraded", "offline"]
GroupKind = Literal["network", "region", "site", "location"]
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


class StatusReport(_Record):
    """Every network's status at a moment."""

    at: datetime
    whole: NetworkStatus
    networks: list[NetworkStatus]


@dataclass
class _Tree:
    """Groups and their parents, and the leaf group each device is in."""

    parent: dict[str, str]
    leaf: dict[str, str]
    names: dict[str, str]

    def up(self, group: str) -> list[str]:
        """A group and every group above it, to the whole."""
        chain = [group]
        while chain[-1] != ROOT:
            chain.append(self.parent.get(chain[-1], ROOT))
        return chain


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
        tunnels = {t.tunnel: t for t in view.state.tunnels}
        gone = {tid for tid, st in tunnels.items() if st.status == "down"}
        whole_edges = [
            Edge(link.id, link.a.device, far_key(link)) for link in self.topology.links
        ]
        whole = self._status(
            None, self.whole_tree, set(self.site_of), whole_edges, down, cut, self.cores
        )
        found: dict[str, NetworkStatus] = {}
        joined: dict[str, dict[str, str]] = {}
        for name in self.layers.order:
            s = self.layers.slices[name]
            # Its links and tunnels, and the spoke-to-spoke tunnels up now.
            edges = self.layers.link_edges(name) + self.layers.tunnel_edges(name)
            for tid, state in tunnels.items():
                if state.network == name and state.dynamic and state.status == "up":
                    a, b = tid.split(":", 1)[1].split("~")
                    edges.append(Edge(tid, a, b, tunnel=True, dynamic=True))
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
        networks = [self._with_caveats(found[n], found) for n in self.layers.order]
        return StatusReport(at=at, whole=whole, networks=networks)

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

        def group_of(node: str) -> str:
            # A transport or external node is in no group but the whole.
            return tree.leaf.get(node, ROOT)

        # Rule 1: what is down degrades its groups.
        for d in sorted(down & members):
            reasons[group_of(d)].append(f"{d} down")
        for e in edges:
            if e.id not in cut:
                continue
            ends = [tree.up(group_of(e.a)), tree.up(group_of(e.b))]
            owner = next(g for g in ends[0] if g in ends[1])
            what = self._name(e)
            for chain in ends:
                for g in chain[: chain.index(owner) + 1]:
                    if what not in reasons[g]:
                        reasons[g].append(what)
        # Rule 2: groups no anchor reaches are offline; those above, degraded.
        holds: dict[str, set[str]] = defaultdict(set)
        for d in members:
            for g in tree.up(group_of(d)):
                holds[g].add(d)
        offline = {g for g, ds in holds.items() if g != ROOT and not ds & reached}
        for g in sorted(offline):
            for above in tree.up(g)[1:]:
                if above not in offline:
                    reasons[above].append(f"{tree.names.get(g, g)} offline")
        sites = {self.site_of[d] for d in members}
        sites_reached = {self.site_of[d] for d in reached}
        # The whole is offline when no two of its sites reach each other,
        # wherever its anchors are: sites cut off from them still work together.
        parts = _components(live)
        together: dict[str, set[str]] = defaultdict(set)
        for d in members - down:
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
            healthy = self._healthy[network] = _parts(tree, holds, built, members)
        now = _parts(tree, holds, live, reached)
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


def _parts(
    tree: _Tree, holds: dict[str, set[str]], edges: list[Edge], present: set[str]
) -> dict[str, int]:
    """For each group with parts, how many pieces its present members fall
    into using only the links and tunnels inside it."""
    # Each link and tunnel is inside the group it belongs to and every group
    # above that one.
    inside: dict[str, list[Edge]] = defaultdict(list)
    for e in edges:
        if e.a not in present or e.b not in present:
            continue
        ends = [tree.up(tree.leaf.get(e.a, ROOT)), tree.up(tree.leaf.get(e.b, ROOT))]
        owner = next(g for g in ends[0] if g in ends[1])
        for g in tree.up(owner):
            inside[g].append(e)
    found = {}
    for g, ds in holds.items():
        mine = ds & present
        if len(mine) >= 2:
            found[g] = _pieces(mine, inside[g])
    return found


def _pieces(nodes: set[str], edges: list[Edge]) -> int:
    parent = {n: n for n in nodes}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for e in edges:
        parent[find(e.a)] = find(e.b)
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
