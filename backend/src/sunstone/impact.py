"""What failures do to the network: which devices they cut off from the
core, and which they leave hanging on a single device.

"The core" is every device with the core role, where the data centers, the
monitoring positions, and the way to other sites are. A device is cut off
when no path of working devices and links joins it to any core device. It
has no redundancy when every such path runs through one same device, so one
more failure would cut it off.

Single points of failure come from one depth-first search from a virtual
root joined to every core device (Tarjan's articulation points): a device u
is the only way to the core for the part of the search tree below its child
c when nothing below c links back above u.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict

from sunstone.layouts import Center
from sunstone.model import Link, Topology

ROOT = -1


@dataclass(frozen=True)
class Failures:
    """Devices and links taken out of the network."""

    devices: frozenset[str] = field(default_factory=frozenset)
    links: frozenset[str] = field(default_factory=frozenset)

    def __or__(self, other: Failures) -> Failures:
        """Both sets of failures together."""
        return Failures(self.devices | other.devices, self.links | other.links)


@dataclass(frozen=True)
class Reach:
    """Which devices reach the core, and which of them only through one device."""

    reached: frozenset[str]
    fragile: Mapping[str, tuple[str, ...]]
    """Devices whose every path to the core runs through some single device,
    with those devices, core side first."""


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FailedSet(_Record):
    """Devices and links that fail."""

    devices: list[str]
    links: list[str]


class Impact(_Record):
    """What some failures do to the network."""

    failed: FailedSet
    cut_off: list[str]
    """Devices, not failed themselves, left with no path to the core."""
    exposed: dict[str, list[str]]
    """Devices that had a second path to the core and now have one, with the
    devices that path runs through, core side first."""


class WhatIf(_Record):
    """What failing some items would do, on top of what is already down."""

    impact: Impact
    already: bool
    """Everything named was already down or cut off, so failing it changes nothing."""


class Network:
    """A topology indexed for working out reachability."""

    def __init__(self, topology: Topology) -> None:
        """Index a topology.

        Args:
            topology: The network.

        Raises:
            None
        """
        self.topology = topology
        self.names = [d.name for d in topology.devices]
        self.number = {name: i for i, name in enumerate(self.names)}
        self.cores = [i for i, d in enumerate(topology.devices) if d.role == "core"]
        self.links = {link.id: link for link in topology.links}
        self.site_of = {d.name: d.site for d in topology.devices}
        self.devices_of: dict[str, list[str]] = {s.code: [] for s in topology.sites}
        for d in topology.devices:
            self.devices_of[d.site].append(d.name)
        self.links_of: dict[str, list[Link]] = {}
        for link in topology.links:
            for end in (link.a, link.b):
                self.links_of.setdefault(end.device, []).append(link)
        self._ends = [
            (self.number[link.a.device], self.number[link.b.device], link.id)
            for link in topology.links
        ]
        self._healthy: Reach | None = None

    def failures_of(self, targets: Iterable[Center]) -> Failures:
        """The devices and links some selected items stand for.

        Args:
            targets: Devices, sites (all their devices), and links.

        Returns:
            Everything they include.

        Raises:
            None
        """
        devices: set[str] = set()
        links: set[str] = set()
        for t in targets:
            if t.kind == "device":
                devices.add(t.id)
            elif t.kind == "site":
                devices.update(self.devices_of.get(t.id, []))
            else:
                links.update(t.ids)
        return Failures(frozenset(devices), frozenset(links))

    def reach(self, failures: Failures) -> Reach:
        """Which devices reach the core around some failures, and which of
        them depend on a single device to do so.

        Args:
            failures: Devices and links to leave out.

        Returns:
            Reached devices, and the fragile ones among them.

        Raises:
            None
        """
        if not failures.devices and not failures.links and self._healthy:
            return self._healthy
        n = len(self.names)
        out = {self.number[d] for d in failures.devices if d in self.number}
        adjacent: list[list[tuple[int, int]]] = [[] for _ in range(n)]
        for li, (a, b, link_id) in enumerate(self._ends):
            if a in out or b in out or link_id in failures.links:
                continue
            adjacent[a].append((b, li))
            adjacent[b].append((a, li))

        # Discovery times start at 1: the virtual root is 0, and every core
        # device links back to it, so a core device anywhere has low 0.
        core = set(self.cores)
        disc = [-1] * n
        low = [0] * n
        parent = [ROOT] * n
        parent_link = [-1] * n
        following = [0] * n
        order: list[int] = []
        time = 1
        for start in self.cores:
            if start in out or disc[start] != -1:
                continue
            disc[start], low[start] = time, 0
            time += 1
            order.append(start)
            stack = [start]
            while stack:
                v = stack[-1]
                i = following[v]
                if i < len(adjacent[v]):
                    following[v] = i + 1
                    w, li = adjacent[v][i]
                    # Skip only the tree link: a parallel link back is a second way.
                    if li == parent_link[v]:
                        continue
                    if disc[w] == -1:
                        disc[w] = time
                        low[w] = 0 if w in core else time
                        time += 1
                        parent[w], parent_link[w] = v, li
                        order.append(w)
                        stack.append(w)
                    else:
                        low[v] = min(low[v], disc[w])
                else:
                    stack.pop()
                    p = parent[v]
                    if p != ROOT:
                        low[p] = min(low[p], low[v])

        # In discovery order, every parent is settled before its children.
        chain: list[tuple[str, ...]] = [()] * n
        fragile: dict[str, tuple[str, ...]] = {}
        for v in order:
            p = parent[v]
            if p == ROOT:
                continue
            above = chain[p]
            chain[v] = (*above, self.names[p]) if low[v] >= disc[p] else above
            if chain[v]:
                fragile[self.names[v]] = chain[v]
        found = Reach(frozenset(self.names[v] for v in order), fragile)
        if not failures.devices and not failures.links:
            self._healthy = found
        return found

    def impact(self, failures: Failures, before: Failures | None = None) -> Impact:
        """What some failures do on top of others.

        Args:
            failures: The failures to look at.
            before: Failures already in place (for example, what live state
                shows down); their effects are not counted again.

        Returns:
            The failures, the devices they cut off, and the devices they
            leave without redundancy.

        Raises:
            None
        """
        before = before or Failures()
        was = self.reach(before)
        now = self.reach(before | failures)
        cut_off = was.reached - now.reached - failures.devices
        exposed = {d: list(c) for d, c in now.fragile.items() if d not in was.fragile}
        return Impact(
            failed=FailedSet(
                devices=sorted(failures.devices), links=sorted(failures.links)
            ),
            cut_off=sorted(cut_off),
            exposed=dict(sorted(exposed.items())),
        )

    def what_if(self, failures: Failures, before: Failures | None = None) -> WhatIf:
        """What failing some devices and links would do.

        Args:
            failures: The failures to suppose.
            before: Failures already in place, such as what live state shows down.

        Returns:
            Their impact, and whether they were all down or cut off already.

        Raises:
            None
        """
        reached = self.reach(before or Failures()).reached

        def gone(link_id: str) -> bool:
            link = self.links.get(link_id)
            ends = {link.a.device, link.b.device} if link else set()
            return (
                before is not None and link_id in before.links
            ) or not ends <= reached

        already = before is not None and (
            all(d not in reached for d in failures.devices)
            and all(gone(link) for link in failures.links)
        )
        return WhatIf(impact=self.impact(failures, before), already=already)
