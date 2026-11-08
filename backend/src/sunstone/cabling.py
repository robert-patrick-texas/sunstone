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
    Tunnel,
    TunnelEnd,
    device_b,
    device_ends,
    layer2,
    link_roles,
    ports,
    sees_across,
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
    across a circuit or a layer-2 service, or inside MACsec or a tunnel, or
    an endpoint."""

    device: str
    """The device reporting it."""
    interface: str
    remote: str
    remote_port: str
    platform: str | None
    capabilities: tuple[str, ...]
    needs: tuple[tuple[str, str], ...] = ()
    """Ports beyond the reporting one that must be up for it to be seen:
    the far device's circuit, across a layer-2 service."""
    tunnel: str | None = None
    """A tunnel, or MACsec connection, that must be up for it to be seen."""
    cdp_only: bool = False
    """Seen over CDP alone: across a circuit whose NTU takes LLDP's frames,
    or over a tunnel."""


NTU_PLATFORM = "Ethernet NTU"
# Endpoints on access ports: phones over LLDP-MED, and printers.
PHONE_PLATFORM, PRINTER_PLATFORM = "IP Phone 8865", "Printer"


class Beyond:
    """What LLDP and CDP really show across circuits, on links to someone
    else's device, over tunnels, and on access ports, in the simulated
    network.

    Each circuit and link beyond our devices shows what its documentation
    first said, or for a circuit into a transport that does not say, the
    provider's NTU; a link to an external node that does not say shows
    nothing. Where the provider's NTU shows, LLDP stops at it, so the far
    end, if it shows too, is seen over CDP alone. Across a layer-2 service
    each circuit that shows the far end sees the other devices on it that
    do (on an E-Tree, a leaf sees only the roots). A port with MACsec shows
    what its link says, as any other: where LLDP and CDP run inside the
    MACsec, its far end is seen inside it, and only its MACsec far ends
    across a layer-2 service; where they run alongside it, in clear, it
    sees and is seen as a port without MACsec. CDP runs over about two in
    three GRE tunnels.

    Like cabling, a little of it disagrees with the documentation, chosen
    with a seed so it stays put: a circuit between two of our devices whose
    provider passes nothing, though it does not say so; a circuit into a
    transport said to show nothing that shows its NTU; where two circuits
    into one routed transport are for something other than transit (two
    sites peering with a research network), a layer-2 path across it that
    lets each see the other's router; two leaves of an E-Tree that see each
    other; and a tunnel whose far end is really on another tunnel interface.
    Watched access switches each report up to three phones and printers on
    ports no link documents.

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
        self.transports = {t.name: t for t in topology.transports}
        self.at_port = ports(topology)
        self.secured: dict[tuple[str, str], list[tuple[Tunnel, TunnelEnd | None]]] = {}
        """The MACsec connections on each port, with their far ends (None
        for someone else's device)."""
        for t in topology.tunnels:
            if t.kind != "macsec":
                continue
            b = t.b if isinstance(t.b, TunnelEnd) else None
            self.secured.setdefault((t.a.device, t.a.interface), []).append((t, b))
            if b is not None:
                self.secured.setdefault((b.device, b.interface), []).append((t, t.a))
        self.real: dict[str, tuple[Neighbors, ...]] = {}
        """What each circuit and link beyond our devices really shows."""
        for ln in topology.links:
            if isinstance(ln.b, Endpoint) and not _carrier(ln):
                continue
            said = shows(ln)
            if not said:
                said = ("provider",) if isinstance(ln.b, TransportEnd) else ("nothing",)
            self.real[ln.id] = said
        self.filtered: str | None = None
        """A circuit between two of our devices said to show the far end
        that really shows nothing."""
        self.unsaid: str | None = None
        """A circuit into a transport said to show nothing that shows its NTU."""
        self.bridged: tuple[Link, Link] | None = None
        """Two circuits into one routed transport, for something other than
        transit, across which each sees the other's router."""
        self.leaked: tuple[Link, Link] | None = None
        """Two leaves of an E-Tree that see each other."""
        self.tunnels: dict[str, str] = {}
        """GRE tunnels CDP runs over, each with the interface its B end is
        really on."""
        for t in topology.tunnels:
            if (
                t.kind == "ip"
                and isinstance(t.b, TunnelEnd)
                and "GRE" in (t.technology or "")
                and zlib.crc32(t.name.encode()) % 3
            ):
                self.tunnels[t.name] = t.b.interface
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
            and not ln.neighbors
            and not self._macsec(ln)
            and seen(ln)
        ]
        if between:
            self.filtered = between[rng.randrange(len(between))].id
            self.real[self.filtered] = ("nothing",)
        quiet = [
            ln
            for ln in links
            if isinstance(ln.b, TransportEnd)
            and ln.neighbors == ["nothing"]
            and seen(ln)
        ]
        if quiet:
            self.unsaid = quiet[rng.randrange(len(quiet))].id
            self.real[self.unsaid] = ("provider",)
        by_transport: dict[str, list[Link]] = {}
        leaves: dict[str, list[Link]] = {}
        for ln in links:
            b = ln.b
            if not isinstance(b, TransportEnd) or not seen(ln):
                continue
            transport = self.transports.get(b.transport)
            roles = link_roles(ln, externals)
            if (
                not layer2(transport)
                and roles.source == "declared"
                and "transit" not in roles.edges
            ):
                by_transport.setdefault(b.transport, []).append(ln)
            if (
                transport is not None
                and transport.service == "e-tree"
                and b.role != "root"
                and self.real.get(ln.id) == ("far-end",)
                and not self._macsec(ln)
            ):
                leaves.setdefault(b.transport, []).append(ln)
        pairs = [
            found[:2] for _, found in sorted(by_transport.items()) if len(found) > 1
        ]
        if pairs:
            self.bridged = (pairs[0][0], pairs[0][1])
        trees = [found for _, found in sorted(leaves.items()) if len(found) > 1]
        if trees:
            i = rng.randrange(len(trees[0]) - 1)
            self.leaked = (trees[0][i], trees[0][i + 1])
        moved = [
            t
            for t in topology.tunnels
            if t.name in self.tunnels
            and isinstance(t.b, TunnelEnd)
            and {t.a.device, t.b.device} <= answering
        ]
        if moved:
            t = moved[rng.randrange(len(moved))]
            self.tunnels[t.name] = _another_tunnel(topology, t)
        self._endpoints(watched)

    def _macsec(self, link: Link) -> bool:
        """Whether MACsec is on a link's port at any of our ends."""
        return any((e.device, e.interface) in self.secured for e in device_ends(link))

    def _inside(self, port: tuple[str, str]) -> list[tuple[Tunnel, TunnelEnd | None]]:
        """The MACsec on a port that LLDP and CDP run inside: with it, they
        reach only its far ends, and nothing in clear gets in."""
        return [
            (t, far) for t, far in self.secured.get(port, []) if t.neighbors == "inside"
        ]

    def rows(self, link: Link) -> list[Shown]:
        """What LLDP and CDP show at our end, or ends, of a circuit or a link
        beyond our devices, other than our own cable's far end.

        Args:
            link: A link as now documented.

        Returns:
            The provider's NTU at each of our ends, someone else's device,
            our own routers across a layer-2 service or path, or a MACsec
            far end across one; none for a link that shows nothing, and
            none for one that shows our far end over a cable or circuit,
            which the cable reports.

        Raises:
            None
        """
        if self.bridged and link.id in {ln.id for ln in self.bridged}:
            here, there = (
                self.bridged if self.bridged[0].id == link.id else self.bridged[::-1]
            )
            return [_across(here, there)]
        real = self.real.get(link.id, ())
        found: list[Shown] = []
        if "provider" in real:
            ends = device_ends(link)
            found += [
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
        if "far-end" not in real:
            return found
        b = link.b
        if isinstance(b, ExternalEnd):
            external = next(
                (e for e in self.topology.externals if e.name == b.external), None
            )
            found.append(
                Shown(
                    device=link.a.device,
                    interface=link.a.interface,
                    remote=f"{b.external.split()[0].lower()}-edge-"
                    f"{link.a.device.split('-')[0]}",
                    remote_port=b.interface or "Ethernet1",
                    platform=external.platform if external else None,
                    capabilities=("router",),
                    cdp_only="provider" in real,
                )
            )
        elif isinstance(b, TransportEnd):
            found += self._peers(link)
        return found

    def _peers(self, link: Link) -> list[Shown]:
        """Our own devices a circuit into a layer-2 service sees across it:
        its MACsec far ends, if LLDP and CDP run inside MACsec on its port;
        else every other circuit on the service that shows the far end in
        clear."""
        port = (link.a.device, link.a.interface)
        secured = self._inside(port)
        at = self.at_port
        if secured:
            return [
                Shown(
                    device=link.a.device,
                    interface=link.a.interface,
                    remote=far.device,
                    remote_port=far.interface,
                    platform=None,
                    capabilities=("router",),
                    needs=((far.device, far.interface),),
                    tunnel=t.name,
                )
                for t, far in secured
                if far is not None and at.get((far.device, far.interface)) is not link
            ]
        leaked = {ln.id for ln in self.leaked} if self.leaked else set()
        ntu = "provider" in self.real.get(link.id, ())
        return [
            _across(link, there, needs=True, cdp_only=ntu)
            for there in self.topology.links
            if (
                sees_across(link, there, self.transports)
                or ({link.id, there.id} <= leaked and link.id != there.id)
            )
            and "far-end" in self.real.get(there.id, ())
            and not self._inside((there.a.device, there.a.interface))
        ]

    def over_tunnels(self) -> list[Shown]:
        """What CDP shows over the tunnels it runs over, from both ends,
        each while its tunnel is up.

        Returns:
            A row at each end of each such tunnel.

        Raises:
            None
        """
        found = []
        for t in self.topology.tunnels:
            real = self.tunnels.get(t.name)
            b = t.b
            if real is None or not isinstance(b, TunnelEnd):
                continue
            for here, here_port, there, there_port in (
                (t.a.device, t.a.interface, b.device, real),
                (b.device, real, t.a.device, t.a.interface),
            ):
                found.append(
                    Shown(
                        device=here,
                        interface=here_port,
                        remote=there,
                        remote_port=there_port,
                        platform=None,
                        capabilities=("router",),
                        tunnel=t.name,
                        cdp_only=True,
                    )
                )
        return found

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


def _across(
    here: Link, there: Link, needs: bool = False, cdp_only: bool = False
) -> Shown:
    """Our router at the far circuit, seen on our circuit's port across a
    layer-2 path; over CDP alone where the provider's NTU takes LLDP's
    frames."""
    return Shown(
        device=here.a.device,
        interface=here.a.interface,
        remote=there.a.device,
        remote_port=there.a.interface,
        platform=None,
        capabilities=("router",),
        needs=((there.a.device, there.a.interface),) if needs else (),
        cdp_only=cdp_only,
    )


def _another_tunnel(topology: Topology, tunnel: Tunnel) -> str:
    """A tunnel interface at a tunnel's B end that no tunnel documents: where
    it really is, when the documentation has the wrong number."""
    b = tunnel.b
    assert isinstance(b, TunnelEnd)
    used = {
        e.interface
        for t in topology.tunnels
        for e in (t.a, t.b)
        if isinstance(e, TunnelEnd) and e.device == b.device
    }
    used |= {
        m.interface for f in topology.fabrics for m in f.members if m.device == b.device
    }
    number = int(re.sub(r"\D", "", b.interface) or "0") + 10
    while f"Tunnel{number}" in used:
        number += 1
    return f"Tunnel{number}"


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
