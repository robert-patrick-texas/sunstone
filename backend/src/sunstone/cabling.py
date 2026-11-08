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
the simulator watches, so discovery can see them. Lab switches come and
go: each is plugged in for about half of all three-hour blocks, so
discovery's history has something to show.

The cables stay put when the documentation changes: ``documenting`` matches
the same cables against another version of it, so a link documented where
its cable really is reads as up, and a cable no longer documented carries
traffic all the same.

What LLDP and CDP show where no cable of ours reaches the far end is in
``Beyond``: across each circuit and on each link to someone else's device,
what each says it shows, except that a circuit into a transport that does
not say shows the provider's NTU, and a few disagree with the documentation
as drift; and on access ports, phones and printers no one documents.
"""

import copy
import random
import re
import zlib
from collections.abc import Set
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from sunstone.model import (
    Endpoint,
    ExternalEnd,
    Link,
    Neighbors,
    Topology,
    TransportEnd,
    device_b,
    device_ends,
    link_roles,
    shows,
)
from sunstone.problems import natural

UNKNOWN_PLATFORM = "WS-C2960X-24TS"
# Lab switches are plugged in, or not, for blocks this long.
LAB_BLOCK = timedelta(hours=3)


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
    temporary: bool = False
    """It is plugged in only some of the time."""
    hidden: bool = False
    """A media converter on it hides each end from the other's LLDP and CDP."""


class Cabling:
    """Every real cable, and the documented ports left without one.

    The drift (``hidden``, ``moved``, ``rewired``, ``extra``, ``silent``) is
    from the documentation the network was cabled from, which
    ``documenting`` keeps.
    """

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
            for end in (ln.a, device_b(ln)):
                self._used.setdefault(end.device, set()).add(end.interface)
        if watched is not None:
            self._drift(watched, random.Random(seed))
        # Each cable with the link it carried as first documented, which
        # names it from then on, whatever the documentation says later.
        self._wires = [
            *(
                replace(self._real(ln), hidden=ln.id in self.hidden)
                for ln in topology.links
            ),
            *self.extra,
        ]
        self._match()

    @property
    def cables(self) -> list[Cable]:
        """Every real cable, each with the documented link whose traffic it
        carries, or with a link made up for it if none is documented.

        Returns:
            The cables, in the order they were first documented, then the rest.

        Raises:
            None
        """
        return self._cables

    @property
    def dangling(self) -> list[tuple[Endpoint, Link]]:
        """Documented ports with no cable, each with its documented link.

        Returns:
            The ports.

        Raises:
            None
        """
        return self._dangling

    def documenting(self, topology: Topology) -> Cabling:
        """The same cables, against another version of the documentation.

        Args:
            topology: The network as now documented: the same devices, with
                links that may differ.

        Returns:
            The cabling, each cable carrying the documented link at either
            of its ends.

        Raises:
            None
        """
        other = copy.copy(self)
        other.topology = topology
        other._match()
        return other

    def in_place(self, link: str, at: datetime) -> bool:
        """Whether the cable carrying a link is plugged in at a moment.

        Args:
            link: The link's id: documented, or made up for a cable no one documented.
            at: The moment.

        Returns:
            False for a temporary cable outside its blocks; else True.

        Raises:
            None
        """
        name = self._temporary.get(link)
        if name is None:
            return True
        block = int(at.timestamp() // LAB_BLOCK.total_seconds())
        return zlib.crc32(f"{name}|{block}".encode()) % 2 == 0

    def _real(self, link: Link) -> Cable:
        a, b = link.a, device_b(link)
        if link.id in self.moved:
            end = self.moved[link.id]
            a, b = (end, b) if a.device == end.device else (a, end)
        elif link.id in self.rewired:
            documented, end = self.rewired[link.id]
            a, b = (end, b) if a.device == documented else (a, end)
        return Cable(a=a, b=b, link=link, documented=True)

    def _match(self) -> None:
        """Give each cable the documented link at either of its ends, and
        find the documented ports no cable reaches."""
        on: dict[tuple[str, str], Link] = {}
        for ln in self.topology.links:
            for end in (ln.a, device_b(ln)):
                on[(end.device, end.interface)] = ln
        cabled: set[tuple[str, str]] = set()
        carried: set[str] = set()
        self._cables: list[Cable] = []
        self._temporary: dict[str, str] = {}
        for wire in self._wires:
            ends = [(e.device, e.interface) for e in (wire.a, wire.b)]
            cabled.update(ends)
            link = next(
                (on[e] for e in ends if e in on and on[e].id not in carried), None
            )
            if link is None:
                # Not documented (any more): a link made up for it.
                own = wire.link
                if {own.a, device_b(own)} != {wire.a, wire.b}:
                    own = Link(
                        a=wire.a, b=wire.b, speed_mbps=own.speed_mbps, kind=own.kind
                    )
                cable = replace(wire, link=own, documented=False)
            else:
                carried.add(link.id)
                # Ends in the same order as the link's.
                flip = ends[1] == (link.a.device, link.a.interface) or ends[0] == (
                    device_b(link).device,
                    device_b(link).interface,
                )
                a, b = (wire.b, wire.a) if flip else (wire.a, wire.b)
                cable = replace(wire, a=a, b=b, link=link, documented=True)
            if wire.temporary:
                self._temporary[cable.link.id] = wire.link.id
            self._cables.append(cable)
        self._dangling = [
            (end, ln)
            for ln in self.topology.links
            for end in (ln.a, device_b(ln))
            if (end.device, end.interface) not in cabled
        ]

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
                and {devices[ln.a.device].role, devices[device_b(ln).device].role}
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
                if {ln.a.device, device_b(ln).device} & taken:
                    continue
                taken.update({ln.a.device, device_b(ln).device})
                chosen.append(ln)
            return chosen

        def ends(ln: Link) -> tuple[Endpoint, Endpoint]:
            """The access end, then the distribution end."""
            return (
                (ln.a, device_b(ln))
                if devices[ln.a.device].role == "access"
                else (device_b(ln), ln.a)
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
        # Lab switches, the ones not in the topology, come and go.
        self.extra.append(
            Cable(
                a=a,
                b=b,
                link=link,
                documented=False,
                platform=platform,
                temporary=platform is not None,
            )
        )


@dataclass(frozen=True)
class Shown:
    """One neighbor LLDP or CDP shows on a port, when it is not one of our
    cables: the provider's NTU, someone else's device, one of our devices
    across a circuit, or an endpoint."""

    device: str
    """The device reporting it."""
    interface: str
    remote: str
    remote_port: str
    platform: str | None
    capabilities: tuple[str, ...]


NTU_PLATFORM = "Ethernet NTU"
# Endpoints on access ports: phones over LLDP-MED, and printers.
PHONE_PLATFORM, PRINTER_PLATFORM = "IP Phone 8865", "Printer"


class Beyond:
    """What LLDP and CDP really show across circuits, on links to someone
    else's device, and on access ports, in the simulated network.

    Each circuit and link beyond our devices shows what its documentation
    first said, or for a circuit into a transport that does not say, the
    provider's NTU; a link to an external node that does not say shows
    nothing. Like cabling, a little of it disagrees with the documentation,
    chosen with a seed so it stays put: a circuit between two of our devices
    whose provider passes nothing, though it does not say so; a circuit into
    a transport said to show nothing that shows its NTU; and where two
    circuits into one transport are for something other than transit (two
    sites peering with a research network), a layer-2 path across it that
    lets each see the other's router. Watched access switches each report up
    to three phones and printers on ports no link documents.

    What a link really shows stays as first documented, keyed by its id,
    however the documentation changes later.
    """

    def __init__(
        self,
        topology: Topology,
        watched: Set[str] | None = None,
        seed: int = 1,
    ) -> None:
        """Work out what each link beyond our cables really shows.

        Args:
            topology: The network as first documented.
            watched: Devices the simulator watches, to put drift and
                endpoints where discovery can see them; None for exactly
                as documented, without endpoints.
            seed: Random seed; the same seed gives the same drift.

        Raises:
            None
        """
        self.topology = topology
        externals = {e.name: e for e in topology.externals}
        self.real: dict[str, Neighbors] = {}
        """What each circuit and link beyond our devices really shows."""
        for ln in topology.links:
            if isinstance(ln.b, Endpoint) and not _carrier(ln):
                continue
            said = shows(ln)
            if said is None:
                said = "provider" if isinstance(ln.b, TransportEnd) else "nothing"
            self.real[ln.id] = said
        self.filtered: str | None = None
        """A circuit between two of our devices said to show the far end
        that really shows nothing."""
        self.unsaid: str | None = None
        """A circuit into a transport said to show nothing that shows its NTU."""
        self.bridged: tuple[Link, Link] | None = None
        """Two circuits into one transport, for something other than
        transit, across which each sees the other's router."""
        self.endpoints: list[Shown] = []
        if watched is None:
            return
        rng = random.Random(seed)
        links = sorted(topology.links, key=lambda ln: ln.id)
        answering = watched

        def seen(ln: Link) -> bool:
            return all(e.device in answering for e in device_ends(ln))

        between = [
            ln
            for ln in links
            if isinstance(ln.b, Endpoint)
            and _carrier(ln)
            and ln.neighbors is None
            and seen(ln)
        ]
        if between:
            self.filtered = between[rng.randrange(len(between))].id
            self.real[self.filtered] = "nothing"
        quiet = [
            ln
            for ln in links
            if isinstance(ln.b, TransportEnd) and ln.neighbors == "nothing" and seen(ln)
        ]
        if quiet:
            self.unsaid = quiet[rng.randrange(len(quiet))].id
            self.real[self.unsaid] = "provider"
        by_transport: dict[str, list[Link]] = {}
        for ln in links:
            roles = link_roles(ln, externals)
            if (
                isinstance(ln.b, TransportEnd)
                and roles.source == "declared"
                and "transit" not in roles.edges
                and seen(ln)
            ):
                by_transport.setdefault(ln.b.transport, []).append(ln)
        pairs = [
            found[:2] for _, found in sorted(by_transport.items()) if len(found) > 1
        ]
        if pairs:
            self.bridged = (pairs[0][0], pairs[0][1])
        self._endpoints(watched)

    def rows(self, link: Link) -> list[Shown]:
        """What LLDP and CDP show at our end, or ends, of a circuit or a link
        beyond our devices, other than our own cable's far end.

        Args:
            link: A link as now documented.

        Returns:
            The provider's NTU at each of our ends, someone else's device,
            or our own router across a layer-2 path; none for a link that
            shows nothing, and none for one that shows our far end, which
            the cable reports.

        Raises:
            None
        """
        if self.bridged and link.id in {ln.id for ln in self.bridged}:
            here, there = (
                self.bridged if self.bridged[0].id == link.id else self.bridged[::-1]
            )
            return [
                Shown(
                    device=here.a.device,
                    interface=here.a.interface,
                    remote=there.a.device,
                    remote_port=there.a.interface,
                    platform=None,
                    capabilities=("router",),
                )
            ]
        real = self.real.get(link.id)
        if real is None or real == "nothing":
            return []
        if real == "far-end":
            b = link.b
            if not isinstance(b, ExternalEnd):
                return []
            external = next(
                (e for e in self.topology.externals if e.name == b.external), None
            )
            return [
                Shown(
                    device=link.a.device,
                    interface=link.a.interface,
                    remote=f"{b.external.split()[0].lower()}-edge-"
                    f"{link.a.device.split('-')[0]}",
                    remote_port=b.interface or "Ethernet1",
                    platform=external.platform if external else None,
                    capabilities=("router",),
                )
            ]
        ends = device_ends(link)
        return [
            Shown(
                device=end.device,
                interface=end.interface,
                remote=_ntu(link, "" if len(ends) == 1 else "az"[i]),
                remote_port="LAN1",
                platform=NTU_PLATFORM,
                capabilities=("switch",),
            )
            for i, end in enumerate(ends)
        ]

    def _endpoints(self, watched: Set[str]) -> None:
        """Up to three phones and printers on each watched access switch."""
        used: dict[str, set[str]] = {}
        for ln in self.topology.links:
            for end in device_ends(ln):
                used.setdefault(end.device, set()).add(end.interface)
        for d in self.topology.devices:
            if d.role != "access" or d.name not in watched:
                continue
            count = zlib.crc32(d.name.encode()) % 4
            port = 10
            for i in range(count):
                while f"GigabitEthernet1/0/{port}" in used.get(d.name, set()):
                    port += 1
                phone = i % 2 == 0
                mac = f"{zlib.crc32(f'{d.name}|{i}'.encode()):08X}"
                self.endpoints.append(
                    Shown(
                        device=d.name,
                        interface=f"GigabitEthernet1/0/{port}",
                        remote=f"SEP0040{mac}" if phone else f"prn-{d.name}-{i + 1}",
                        remote_port="Port 1",
                        platform=PHONE_PLATFORM if phone else PRINTER_PLATFORM,
                        capabilities=("phone",) if phone else ("host",),
                    )
                )
                port += 1


def _carrier(link: Link) -> bool:
    """Whether a carrier's service, not a cable, joins a link's ends."""
    return link.circuit is not None and link.circuit.type == "carrier"


def _ntu(link: Link, side: str) -> str:
    """The name a provider's NTU gives itself: the provider and the number
    of the circuit it terminates, and the side, for a circuit between two of
    our devices."""
    circuit = link.circuit
    if circuit is None:
        return f"ntu-{side}"
    provider = circuit.provider.split()[0].lower()
    digits = re.sub(r"\D", "", circuit.circuit_id.a.split()[0]) or "0"
    return f"{provider}-ntu-{digits}{side}"
