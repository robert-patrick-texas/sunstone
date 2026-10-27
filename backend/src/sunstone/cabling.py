"""The simulated network as it is really cabled.

Documentation drifts from the network. A cable gets moved to a spare port,
or to the other switch of a distribution pair; someone patches two access
switches together and never writes it down; a lab switch hangs off an
access port; LLDP and CDP are turned off on a switch; a media converter on
a link hides each end from the other's LLDP. The simulator's live state and
its discovery both follow the real cables: a documented port with no cable
is down, the port a cable really reaches carries the traffic, and discovery
reports what is really there. So a link that live state shows down can be
one that discovery shows cabled elsewhere.

There is about one of each per thousand links, at least one, chosen from
the topology with a seed so they stay put, as drift does; the switch with
LLDP off, the lab switches, and the undocumented patches are on switches
the simulator watches, so discovery can see them.
"""

import random
from collections.abc import Set
from dataclasses import dataclass

from sunstone.model import Endpoint, Link, Topology
from sunstone.problems import natural

UNKNOWN_PLATFORM = "WS-C2960X-24TS"


@dataclass(frozen=True)
class Cable:
    """A real cable, with its ends in the same order as the link it carries."""

    a: Endpoint
    b: Endpoint
    link: Link
    """The documented link whose traffic it carries, or for a cable no one
    documented, a link made up for it."""
    documented: bool
    """It stands for a documented link, wherever its ends really are."""
    platform: str | None = None
    """The far end's platform, when the far end is not in the topology."""


class Cabling:
    """Every real cable, and the documented ports left without one."""

    def __init__(
        self, topology: Topology, watched: Set[str] | None = None, seed: int = 1
    ) -> None:
        """Work out the cabling.

        Args:
            topology: The documented network.
            watched: Devices the simulator watches, to put drift where
                discovery can see it; None for cabling exactly as documented.
            seed: Random seed; the same seed gives the same drift.

        Raises:
            None
        """
        self.topology = topology
        self.hidden: set[str] = set()
        """Documented links a media converter hides from LLDP and CDP."""
        self.silent: set[str] = set()
        """Devices with LLDP and CDP off."""
        self.moved: dict[str, Endpoint] = {}
        """Documented links whose access end is really on another port."""
        self.rewired: dict[str, tuple[str, Endpoint]] = {}
        """Documented links whose distribution end is really on the other
        switch of the pair: the switch documented, and the real end."""
        self.extra: list[Cable] = []
        """Cables no one documented, some to devices not in the topology."""
        self._used: dict[str, set[str]] = {}
        for ln in topology.links:
            for end in (ln.a, ln.b):
                self._used.setdefault(end.device, set()).add(end.interface)
        if watched is not None:
            self._drift(watched, random.Random(seed))

    @property
    def cables(self) -> list[Cable]:
        """Every real cable: the documented ones where they really are, then the rest.

        Returns:
            The cables.

        Raises:
            None
        """
        return [*(self._real(ln) for ln in self.topology.links), *self.extra]

    @property
    def dangling(self) -> list[tuple[Endpoint, Link]]:
        """Documented ports with no cable, each with its documented link.

        Returns:
            The ports.

        Raises:
            None
        """
        found = []
        for ln in self.topology.links:
            if ln.id in self.moved:
                found.append(
                    (ln.a if ln.a.device == self.moved[ln.id].device else ln.b, ln)
                )
            elif ln.id in self.rewired:
                documented, _ = self.rewired[ln.id]
                found.append((ln.a if ln.a.device == documented else ln.b, ln))
        return found

    def _real(self, link: Link) -> Cable:
        a, b = link.a, link.b
        if link.id in self.moved:
            end = self.moved[link.id]
            a, b = (end, b) if a.device == end.device else (a, end)
        elif link.id in self.rewired:
            documented, end = self.rewired[link.id]
            a, b = (end, b) if a.device == documented else (a, end)
        return Cable(a=a, b=b, link=link, documented=True)

    def _spare(self, device: str, like: str) -> str:
        """A port on a device that no cable uses, named like another."""
        prefix = like.rstrip("0123456789")
        used = self._used.setdefault(device, set())
        n = 48
        while f"{prefix}{n}" in used:
            n += 1
        used.add(f"{prefix}{n}")
        return f"{prefix}{n}"

    def _drift(self, watched: Set[str], rng: random.Random) -> None:
        topology = self.topology
        devices = {d.name: d for d in topology.devices}
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

        def ends(ln: Link) -> tuple[Endpoint, Endpoint]:
            """The access end, then the distribution end."""
            return (
                (ln.a, ln.b) if devices[ln.a.device].role == "access" else (ln.b, ln.a)
            )

        self.hidden = {ln.id for ln in pick(many)}
        for ln in pick(many):
            access, _ = ends(ln)
            port = self._spare(access.device, access.interface)
            self.moved[ln.id] = Endpoint(device=access.device, interface=port)
        for ln in pick(many):
            _, dist = ends(ln)
            pair = [
                d.name
                for d in topology.devices
                if d.site == devices[dist.device].site
                and d.role == "distribution"
                and d.name != dist.device
            ]
            if pair:
                taken.add(pair[0])
                port = self._spare(pair[0], dist.interface)
                real = Endpoint(device=pair[0], interface=port)
                self.rewired[ln.id] = (dist.device, real)
        switches = sorted(
            (
                d
                for d in topology.devices
                if d.role == "access" and d.name in watched and d.name not in taken
            ),
            key=lambda d: (d.site, natural(d.name)),
        )
        for i in range(many):
            pairs = [
                (x, y)
                for x, y in zip(switches, switches[1:], strict=False)
                if x.site == y.site and not {x.name, y.name} & taken
            ]
            if pairs:
                x, y = pairs[rng.randrange(len(pairs))]
                taken.update({x.name, y.name})
                self._cable(
                    Endpoint(
                        device=x.name,
                        interface=self._spare(x.name, "GigabitEthernet1/0/1"),
                    ),
                    Endpoint(
                        device=y.name,
                        interface=self._spare(y.name, "GigabitEthernet1/0/1"),
                    ),
                )
            spare = [d for d in switches if d.name not in taken]
            if spare:
                lone = spare[rng.randrange(len(spare))]
                taken.add(lone.name)
                self._cable(
                    Endpoint(
                        device=lone.name,
                        interface=self._spare(lone.name, "GigabitEthernet1/0/1"),
                    ),
                    Endpoint(
                        device=f"lab-sw-{i + 1:02d}", interface="GigabitEthernet0/1"
                    ),
                    UNKNOWN_PLATFORM,
                )
        spare = [d for d in switches if d.name not in taken]
        if spare:
            self.silent = {spare[rng.randrange(len(spare))].name}

    def _cable(self, a: Endpoint, b: Endpoint, platform: str | None = None) -> None:
        link = Link(a=a, b=b, speed_mbps=1_000)
        self.extra.append(
            Cable(a=a, b=b, link=link, documented=False, platform=platform)
        )
