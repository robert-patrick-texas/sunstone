"""Generate the layered sample: transports, tunnels, and networks over them.

Two data centers and twenty branches on the Internet, a carrier's private
WAN, or both, a few point-to-point circuits, and networks stacked over them:

- **black**: every circuit and both transports, outside the boundary.
- **corp**: two DMVPN fabrics, one over each transport, with the data
  centers' WAN routers as hubs; and a direct interconnect to a cloud.
- **dci**: a GRE+IPsec+MPLS tunnel between the data centers' WAN routers,
  the same routers that are the DMVPN hubs.
- **blue**: point-to-point tunnels between outer routers, over black.
- **blue2**: a FlexVPN hub and spokes at sites blue does not reach.
- **grey**: tunnels between inner routers, riding blue where there is blue,
  blue2 where there is that, and black directly elsewhere.
- **red-alpha** and **red-bravo**: tenants' networks over grey, through
  their own encryptors at grey sites; two sites have both.
- **partners**: an IPsec tunnel to a partner who runs its own end.

Houston has two WAN switches with two Internet circuits each, from three
providers, and a blue router trunked to both. Tampa has one switch carrying
grey and black in different VLANs, trunked to a router whose grey tunnel
rides black directly.

Each circuit has its roles at the edge, as routing policy would set them at
its site. Every one is transit, since tunnels to other sites ride it. The
data centers' Internet circuits are also the way out (egress, through the
central gateway) and the way in to what they publish (ingress, a DMZ).
Branches with both transports break out locally to the mail service
(egress); the others send everything through the data centers. A research
network joins the data centers to its other members: at IAD for peering
among them only, at DAL as open, carrying Internet routes too. Tampa's
Internet circuit has no roles yet (TBD). IAD is in a co-location facility
whose cross-connects join its two halls. Circuits say what LLDP and CDP
show on our port, the provider's NTU or nothing, by provider. Everything
is fictional.
"""

import random
import zlib
from collections import Counter

from sunstone.mockgen import CITIES, labeled, with_groups
from sunstone.model import (
    Carried,
    Circuit,
    Device,
    Edge,
    Endpoint,
    External,
    ExternalEnd,
    Fabric,
    FabricMember,
    Link,
    NamedNetwork,
    Neighbors,
    Role,
    SegmentIds,
    Sides,
    Site,
    Tenant,
    Topology,
    Transport,
    TransportEnd,
    Tunnel,
    TunnelEnd,
    TunnelPeer,
)

INTERNET = [
    "Northwind Fiber",
    "Bluebonnet Telecom",
    "Crestline Networks",
    "Harbor Transit",
]
MPLS_PROVIDER = "Mesa Carrier"
INET, MPLS = "INET", "Mesa MPLS"
REN, REN_PROVIDER = "Prairie REN", "Prairie Research Network"
COLO = "Granite Colo"
# Providers whose NTU shows on our port over LLDP or CDP; the rest show nothing.
SHOWS_NTU = {"Northwind Fiber", "Harbor Transit", MPLS_PROVIDER, REN_PROVIDER}
# The local exchange carrier that hands Mesa's circuits off at the branches.
LEC = "Pecos Bell"
HUBS = ["DAL", "IAD"]
BLACK_VLAN, GREY_VLAN = 30, 200
PLATFORM = {
    "wan": "ASR1001-X",
    "wsw": "C9300X-24Y",
    "core": "N9K-C9364C",
    "dist": "C9500-48Y4C",
    "acc": "C9300-48P",
    "blu": "ISR4451-X",
    "bl2": "ISR4451-X",
    "gry": "ISR4431",
    "gsw": "C9200-24T",
}
ROLE: dict[str, Role] = {
    "wan": "wan-edge",
    "wsw": "wan-edge",
    "core": "core",
    "dist": "distribution",
    "acc": "access",
    "blu": "wan-edge",
    "bl2": "wan-edge",
    "gry": "distribution",
    "gsw": "access",
}
# Branches by what they have: the transports their WAN routers use, and
# whether they are blue, blue2, or grey over black.
BOTH = ["AUS", "SAT", "ELP", "LIT", "MSY", "BHM", "MCO", "MIA"]
INET_ONLY = ["TUL", "BTR", "JAX"]
MPLS_ONLY = ["FTW"]
BLUE = ["ATL", "OKC", "CLT"]  # and HOU, built on its own
BLUE2 = ["MEM", "BNA"]
GREY_OVER_BLACK = ["RDU"]  # and TPA, built on its own
ALPHA = ["DAL", "HOU", "ATL", "OKC", "TPA"]
BRAVO = ["IAD", "ATL", "CLT", "MEM", "TPA"]


class _Layers:
    """Collects everything, handing out port names per device."""

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.sites = {
            code: Site(code=code, name=name, region=region, lat=lat, lon=lon)
            for code, name, region, lat, lon in CITIES[:22]
        }
        self.devices: list[Device] = []
        self.links: list[Link] = []
        self.tunnels: list[Tunnel] = []
        self.externals: list[External] = []
        self._ports: Counter[tuple[str, str]] = Counter()
        self._circuits: Counter[str] = Counter()

    def device(self, site: str, part: str, n: int = 1) -> str:
        """Add a device, named like ``hou-gry-01``."""
        name = f"{site.lower()}-{part}-{n:02d}"
        index = list(self.sites).index(site) + 1
        count = sum(d.site == site for d in self.devices) + 1
        self.devices.append(
            Device(
                name=name,
                site=site,
                role=ROLE[part],
                platform=PLATFORM[part],
                mgmt_ip=f"10.{index}.0.{count}",
            )
        )
        return name

    def port(self, device: str, speed_mbps: int = 1_000) -> str:
        """The device's next free port of a speed."""
        slot = {1_000: "GigabitEthernet0/0/", 10_000: "TenGigabitEthernet0/1/"}
        if speed_mbps == 100_000:
            slot = {100_000: "HundredGigE1/0/"}
        self._ports[(device, slot[speed_mbps])] += 1
        return f"{slot[speed_mbps]}{self._ports[(device, slot[speed_mbps])] - 1}"

    def circuit(
        self, provider: str, shared: bool = False, lec: bool = False
    ) -> Circuit:
        """A circuit from a provider, numbered like its others; into a shared
        transport, the Z side has no CID. Handed off by the local exchange
        carrier, it has the LEC's CID too."""
        self._circuits[provider] += 1
        number = self.rng.randrange(100_000, 1_000_000)
        cid = f"{provider[:2].upper()}-{number}"
        if lec:
            # The LEC's own number, made from the carrier's so the rest of
            # the sample's random numbers stay as they were.
            cid += f" / {LEC} 12/KXFU/{zlib.crc32(cid.encode()) % 900_000 + 100_000}"
        return Circuit(
            provider=provider, circuit_id=Sides(a=cid, z=None if shared else cid)
        )

    def cable(
        self,
        a: str,
        b: str,
        speed_mbps: int = 1_000,
        carries: list[Carried] | None = None,
    ) -> tuple[str, str]:
        """Connect two devices on their next free ports."""
        pa, pb = self.port(a, speed_mbps), self.port(b, speed_mbps)
        self.links.append(
            Link(
                a=Endpoint(device=a, interface=pa),
                b=Endpoint(device=b, interface=pb),
                speed_mbps=speed_mbps,
                carries=carries or [],
            )
        )
        return pa, pb

    def into(
        self,
        device: str,
        transport: str,
        speed_mbps: int,
        provider: str,
        edges: list[Edge] | None,
    ) -> None:
        """A circuit from a device into a transport, with its roles at the
        edge (None: not given yet, TBD); it shows the provider's NTU if the
        provider leaves LLDP and CDP on, and else nothing."""
        vlan = BLACK_VLAN if device.split("-")[1] == "wsw" else None
        shown: Neighbors = "provider" if provider in SHOWS_NTU else "nothing"
        lec = provider == MPLS_PROVIDER and device.split("-")[0].upper() not in HUBS
        self.links.append(
            Link(
                a=Endpoint(device=device, interface=self.port(device)),
                b=TransportEnd(transport=transport),
                speed_mbps=speed_mbps,
                kind="wan",
                circuit=self.circuit(provider, shared=True, lec=lec),
                carries=[Carried(network="black", vlan=vlan)] if vlan else [],
                edges=edges or [],
                neighbors=shown if edges is not None else None,
            )
        )

    def internet(self, device: str, edges: list[Edge] | None) -> None:
        """An Internet circuit from a random provider."""
        self.into(
            device,
            INET,
            self.rng.choice([500, 1_000]),
            self.rng.choice(INTERNET),
            edges,
        )

    def mpls(self, device: str) -> None:
        """A circuit into the carrier's private WAN, for tunnels to other sites."""
        self.into(
            device,
            MPLS,
            self.rng.choice([100, 200, 500]),
            MPLS_PROVIDER,
            ["transit"],
        )

    def tunnel(
        self, name: str, network: str, rides: str, a: str, b: str, technology: str
    ) -> None:
        """A point-to-point tunnel between two devices' loopbacks."""
        number = {"blue": 10, "grey": 20, "dci": 30}[network]
        ends = [
            TunnelEnd(device=d, interface=f"Tunnel{number}{i}", source="Loopback0")
            for i, d in (
                (self._next_tunnel(a, number), a),
                (self._next_tunnel(b, number), b),
            )
        ]
        self.tunnels.append(
            Tunnel(
                name=name,
                network=network,
                rides=rides,
                technology=technology,
                a=ends[0],
                b=ends[1],
            )
        )

    def _next_tunnel(self, device: str, number: int) -> int:
        self._ports[(device, f"Tunnel{number}")] += 1
        return self._ports[(device, f"Tunnel{number}")]

    def encryptor(self, tenant: str, site: str, switch: str) -> None:
        """A tenant's encryptor, its outside port on a grey switch."""
        name = f"{tenant.lower()}-{site.lower()}-1"
        self.externals.append(
            External(
                name=name,
                kind="tenant",
                tenant=tenant,
                network=f"red-{tenant.lower()}",
                platform="Inline encryptor",
            )
        )
        self.links.append(
            Link(
                a=Endpoint(device=switch, interface=self.port(switch)),
                b=ExternalEnd(external=name, interface="ciphertext"),
                speed_mbps=1_000,
                carries=[_grey()],
                # Inline encryptors do not run LLDP or CDP.
                neighbors="nothing",
            )
        )


def _grey(b: int | None = None) -> Carried:
    return Carried(
        network="grey",
        vlan=GREY_VLAN,
        b=SegmentIds(vlan=b) if b is not None else None,
    )


def _carries(network: str, vlan: int | None = None) -> list[Carried]:
    return [Carried(network=network, vlan=vlan)]


def _datacenter(g: _Layers, site: str) -> dict[str, str]:
    """A data center: WAN routers, core, distribution, access, and the
    outer, inner, and grey-switch tiers."""
    wans = [g.device(site, "wan", i) for i in (1, 2)]
    cores = [g.device(site, "core", i) for i in (1, 2)]
    for w in wans:
        for c in cores:
            g.cable(w, c, 10_000)
    g.cable(cores[0], cores[1], 100_000)
    dists = [g.device(site, "dist", i) for i in (1, 2)]
    for d in dists:
        for c in cores:
            g.cable(c, d, 10_000)
    for n in (1, 2, 3):
        acc = g.device(site, "acc", n)
        for d in dists:
            g.cable(d, acc)
    # Tunnels to the branches, the central way out, and the DMZ.
    for _ in range(2):
        g.internet(wans[0], ["transit", "egress", "ingress"])
    g.mpls(wans[1])
    blue = g.device(site, "blu")
    g.cable(wans[0], blue, carries=_carries("black"))
    grey = g.device(site, "gry")
    g.cable(blue, grey, carries=_carries("blue"))
    # The inner router also reaches black itself, for grey over black.
    g.cable(wans[0], grey, carries=_carries("black"))
    gsw = g.device(site, "gsw")
    g.cable(grey, gsw, carries=[_grey()])
    found = {"wan1": wans[0], "wan2": wans[1], "blu": blue, "gry": grey, "gsw": gsw}
    if site == "DAL":
        blue2 = g.device(site, "bl2")
        g.cable(wans[1], blue2, carries=_carries("black"))
        g.cable(blue2, grey, carries=_carries("blue2"))
        found["bl2"] = blue2
    return found


def _branch(g: _Layers, site: str, inet: bool, mpls: bool) -> dict[str, str]:
    """A branch's WAN routers and access switches."""
    wans = [g.device(site, "wan", i + 1) for i in range(int(inet) + int(mpls))]
    if inet:
        # Branches with both transports break out locally to the mail service.
        g.internet(wans[0], ["transit", "egress"] if site in BOTH else ["transit"])
    if mpls:
        g.mpls(wans[-1])
    for n in range(1, g.rng.randint(2, 4)):
        acc = g.device(site, "acc", n)
        for w in wans:
            g.cable(w, acc)
    found = {"inet": wans[0] if inet else "", "mpls": wans[-1] if mpls else ""}
    return found


def _secure(g: _Layers, site: str, outer: str, under: str) -> dict[str, str]:
    """An outer router on a WAN router, an inner one behind it, and a grey switch."""
    found = {}
    upstream = under
    if outer:
        found[outer] = g.device(site, outer)
        g.cable(under, found[outer], carries=_carries("black"))
        upstream = found[outer]
    found["gry"] = g.device(site, "gry")
    network = {"blu": "blue", "bl2": "blue2", "": "black"}[outer]
    g.cable(upstream, found["gry"], carries=_carries(network))
    found["gsw"] = g.device(site, "gsw")
    g.cable(found["gry"], found["gsw"], carries=[_grey()])
    return found


def _houston(g: _Layers) -> dict[str, str]:
    """Two WAN switches with four Internet circuits from three providers,
    and a blue router trunked to both."""
    switches = [g.device("HOU", "wsw", i) for i in (1, 2)]
    for sw, providers in zip(
        switches, [INTERNET[0:3:2], [INTERNET[0], INTERNET[3]]], strict=True
    ):
        for provider in providers:
            g.into(sw, INET, 1_000, provider, ["transit", "egress"])
    blue = g.device("HOU", "blu")
    for sw in switches:
        g.cable(sw, blue, carries=_carries("black", BLACK_VLAN))
    grey = g.device("HOU", "gry")
    g.cable(blue, grey, carries=_carries("blue"))
    gsw = g.device("HOU", "gsw")
    # The grey switch calls grey VLAN 400; the router, VLAN 200.
    g.cable(grey, gsw, carries=[_grey(b=400)])
    return {"blu": blue, "gry": grey, "gsw": gsw}


def _tampa(g: _Layers) -> dict[str, str]:
    """One switch carrying grey and black in VLANs 200 and 30, trunked to a
    router whose grey tunnel rides black directly."""
    sw = g.device("TPA", "wsw")
    gsw = g.device("TPA", "gsw")
    grey = g.device("TPA", "gry")
    # Gi0/0/0: access port in grey VLAN 200, to the grey switch.
    g.cable(sw, gsw, carries=[_grey()])
    # Gi0/0/1: access port in black VLAN 30, to the Internet circuit, whose
    # roles and what it shows are still to be documented.
    g.into(sw, INET, 1_000, INTERNET[1], None)
    # Gi0/0/2: trunk to the router with both.
    g.cable(sw, grey, carries=[_grey(), *_carries("black", BLACK_VLAN)])
    return {"gry": grey, "gsw": gsw}


def generate_layers(seed: int) -> Topology:
    """Generate the layered sample.

    Args:
        seed: Random seed; the same seed gives the same topology.

    Returns:
        The validated topology.

    Raises:
        None
    """
    g = _Layers(random.Random(seed))
    dc = {code: _datacenter(g, code) for code in ("DAL", "IAD")}
    for _ in range(2):
        g.links.append(
            Link(
                a=Endpoint(
                    device=dc["DAL"]["wan2"],
                    interface=g.port(dc["DAL"]["wan2"], 100_000),
                ),
                b=Endpoint(
                    device=dc["IAD"]["wan2"],
                    interface=g.port(dc["IAD"]["wan2"], 100_000),
                ),
                speed_mbps=100_000,
                kind="wan",
                circuit=g.circuit(MPLS_PROVIDER),
            )
        )
    branches: dict[str, dict[str, str]] = {}
    for code in BOTH + BLUE:
        branches[code] = _branch(g, code, inet=True, mpls=True)
    for code in INET_ONLY + GREY_OVER_BLACK:
        branches[code] = _branch(g, code, inet=True, mpls=False)
    for code in MPLS_ONLY + BLUE2:
        branches[code] = _branch(g, code, inet=False, mpls=True)
    secure = {"HOU": _houston(g), "TPA": _tampa(g)}
    for code in BLUE:
        secure[code] = _secure(g, code, "blu", branches[code]["inet"])
    for code in BLUE2:
        secure[code] = _secure(g, code, "bl2", branches[code]["mpls"])
    for code in GREY_OVER_BLACK:
        secure[code] = _secure(g, code, "", branches[code]["inet"])
    secure |= {code: dc[code] for code in ("DAL", "IAD")}

    # Point-to-point circuits, beside the transports: a licensed microwave
    # service, and a circuit each of whose sides has its own IDs.
    for a, b in (("DAL", "FTW"), ("AUS", "SAT")):
        near = dc["DAL"]["wan2"] if a == "DAL" else branches[a]["inet"]
        far = branches[b]["mpls"] or branches[b]["inet"]
        circuit = g.circuit(MPLS_PROVIDER)
        if a == "AUS":
            cid = circuit.circuit_id.a
            circuit = circuit.model_copy(
                update={
                    "circuit_id": Sides(
                        a=f"{cid} / {LEC} 12/KXFU/204411",
                        z=f"{cid} / Gulf Coast Bell 31/KQGS/558120",
                    )
                }
            )
        g.links.append(
            Link(
                a=Endpoint(device=near, interface=g.port(near, 10_000)),
                b=Endpoint(device=far, interface=g.port(far, 10_000)),
                speed_mbps=10_000,
                kind="wan",
                circuit=circuit,
                medium="microwave" if a == "DAL" else None,
                enterprise_cid=Sides(a="AUS-SAT-01", z="SAT-AUS-01")
                if a == "AUS"
                else None,
            )
        )
    # dci: between the data centers, on the routers that are DMVPN hubs.
    g.tunnel(
        "DCI-1", "dci", "black", dc["DAL"]["wan1"], dc["IAD"]["wan1"], "GRE+IPsec+MPLS"
    )
    # blue: each blue site to both data centers, and between them.
    blue_dual_stack = "IPsec+GRE, IPv4 and IPv6"
    g.tunnel(
        "BLUE-DAL-IAD",
        "blue",
        "black",
        dc["DAL"]["blu"],
        dc["IAD"]["blu"],
        blue_dual_stack,
    )
    for code in ["HOU", *BLUE]:
        for hub in ("DAL", "IAD"):
            g.tunnel(
                f"BLUE-{code}-{hub}",
                "blue",
                "black",
                secure[code]["blu"],
                dc[hub]["blu"],
                blue_dual_stack,
            )
    # grey: over blue where both ends have it, blue2 where that, else black.
    g.tunnel(
        "GREY-DAL-IAD", "grey", "blue", dc["DAL"]["gry"], dc["IAD"]["gry"], "GRE+IPsec"
    )
    for code in ["HOU", *BLUE]:
        for hub in ("DAL", "IAD"):
            g.tunnel(
                f"GREY-{code}-{hub}",
                "grey",
                "blue",
                secure[code]["gry"],
                dc[hub]["gry"],
                "GRE+IPsec",
            )
    for code in BLUE2:
        g.tunnel(
            f"GREY-{code}-DAL",
            "grey",
            "blue2",
            secure[code]["gry"],
            dc["DAL"]["gry"],
            "GRE+IPsec",
        )
    for code in ["TPA", *GREY_OVER_BLACK]:
        for hub in ("DAL", "IAD"):
            g.tunnel(
                f"GREY-{code}-{hub}",
                "grey",
                "black",
                secure[code]["gry"],
                dc[hub]["gry"],
                "GRE+IPsec",
            )
    # partners: Acme runs its own end.
    g.tunnels.append(
        Tunnel(
            name="Acme VPN",
            network="partners",
            rides="black",
            technology="IPsec",
            a=TunnelEnd(
                device=dc["DAL"]["wan1"], interface="Tunnel50", source="Loopback0"
            ),
            b=TunnelPeer(external="Acme Logistics", peer="198.51.100.7"),
        )
    )

    inet_spokes = [
        branches[c]["inet"] for c in BOTH + BLUE + INET_ONLY + GREY_OVER_BLACK
    ]
    mpls_spokes = [branches[c]["mpls"] for c in BOTH + BLUE + MPLS_ONLY + BLUE2]
    fabrics = [
        _fabric(
            "DMVPN-INET",
            "corp",
            "hub-spoke-dynamic",
            "DMVPN phase 3",
            [dc[s]["wan1"] for s in ("DAL", "IAD")],
            inet_spokes,
            100,
        ),
        _fabric(
            "DMVPN-MPLS",
            "corp",
            "hub-spoke",
            "DMVPN phase 2",
            [dc[s]["wan2"] for s in ("DAL", "IAD")],
            mpls_spokes,
            200,
        ),
        _fabric(
            "BLUE2",
            "blue2",
            "hub-spoke",
            "FlexVPN",
            [dc["DAL"]["bl2"]],
            [secure[c]["bl2"] for c in BLUE2],
            300,
        ),
    ]

    # A cloud reached over the Internet and by a direct interconnect, and a
    # mail application reached over the Internet only.
    iad_wan2 = dc["IAD"]["wan2"]
    g.links.append(
        Link(
            a=Endpoint(device=iad_wan2, interface=g.port(iad_wan2, 10_000)),
            b=ExternalEnd(external="Nimbus Cloud"),
            speed_mbps=10_000,
            kind="wan",
            circuit=g.circuit("Nimbus Cloud"),
            carries=_carries("corp"),
            # A cloud region joined directly, its edge router seen on our port.
            edges=["interconnect"],
            neighbors="far-end",
        )
    )
    g.externals += [
        External(
            name="Nimbus Cloud",
            kind="application",
            reached_over=[INET],
            description="Cloud provider",
        ),
        External(
            name="Stratus Mail",
            kind="application",
            reached_over=[INET],
            description="Email and calendars",
        ),
        External(
            name="Acme Logistics",
            kind="partner",
            description="Freight partner; runs its own VPN gateway",
        ),
    ]
    for tenant, sites in (("Alpha", ALPHA), ("Bravo", BRAVO)):
        for code in sites:
            g.encryptor(tenant, code, secure[code]["gsw"])

    # The research network, at each data center's Internet router.
    research: list[tuple[str, list[Edge]]] = [("IAD", ["peering"]), ("DAL", ["open"])]
    for code, edges in research:
        router = dc[code]["wan1"]
        g.links.append(
            Link(
                a=Endpoint(device=router, interface=g.port(router, 10_000)),
                b=TransportEnd(transport=REN),
                speed_mbps=10_000,
                kind="wan",
                circuit=g.circuit(REN_PROVIDER, shared=True),
                edges=edges,
                neighbors="provider",
            )
        )

    topology = Topology(
        sites=list(g.sites.values()),
        devices=g.devices,
        links=g.links,
        networks=[
            NamedNetwork(
                name="black", boundary="outside", description="Circuits and transports"
            ),
            NamedNetwork(
                name="corp", anchors=HUBS, description="Offices and data centers"
            ),
            NamedNetwork(
                name="dci", anchors=HUBS, description="Data center interconnect"
            ),
            NamedNetwork(
                name="blue", anchors=HUBS, description="Outer encryption, first fabric"
            ),
            NamedNetwork(
                name="blue2",
                anchors=["DAL"],
                description="Outer encryption where blue does not reach",
            ),
            NamedNetwork(
                name="grey",
                anchors=HUBS,
                # Its own regions, rather than the sites'.
                regions={
                    "grey-west": ["DAL", "HOU", "OKC", "TPA"],
                    "grey-east": ["IAD", "ATL", "CLT", "MEM", "BNA", "RDU"],
                },
                description="Inner encryption, second fabric",
            ),
            NamedNetwork(
                name="red-alpha",
                tenant="Alpha",
                rides=["grey"],
                description="Alpha's own network",
            ),
            NamedNetwork(
                name="red-bravo",
                tenant="Bravo",
                rides=["grey"],
                description="Bravo's own network",
            ),
            NamedNetwork(name="partners", description="Tunnels to partners"),
        ],
        transports=[
            Transport(
                name=INET, kind="internet", network="black", description="The Internet"
            ),
            Transport(
                name=MPLS,
                kind="private-wan",
                network="black",
                provider=MPLS_PROVIDER,
                description="Carrier MPLS VPN",
            ),
            Transport(
                name=REN,
                kind="research",
                network="black",
                provider=REN_PROVIDER,
                description="Research and education network",
            ),
        ],
        externals=g.externals,
        tenants=[
            Tenant(name="Alpha", description="Tenant with its own encryptors"),
            Tenant(name="Bravo", description="Tenant with its own encryptors"),
        ],
        tunnels=g.tunnels,
        fabrics=fabrics,
    )
    return labeled(_cross_connected(with_groups(topology), "IAD"))


def _cross_connected(topology: Topology, code: str) -> Topology:
    """Make the links between a site's halls the co-location provider's
    cross-connects, each with the provider's order number."""
    hall = {d.name: d.location for d in topology.devices if d.site == code}
    links = []
    n = 0
    for ln in topology.links:
        b = ln.b
        if (
            isinstance(b, Endpoint)
            and ln.a.device in hall
            and b.device in hall
            and hall[ln.a.device] != hall[b.device]
        ):
            n += 1
            order = Sides(a=f"XC-{40_000 + n * 17}")
            ln = ln.model_copy(
                update={
                    "circuit": Circuit(
                        provider=COLO, circuit_id=order, type="cross-connect"
                    )
                }
            )
        links.append(ln)
    return topology.model_copy(update={"links": links})


def _fabric(
    name: str,
    network: str,
    shape: str,
    technology: str,
    hubs: list[str],
    spokes: list[str],
    number: int,
) -> Fabric:
    """A hub-and-spoke fabric on each member's Tunnel interface of a number."""
    members = [
        FabricMember(
            device=d, interface=f"Tunnel{number}", role=role, source="Loopback0"
        )
        for role, devices in (("hub", hubs), ("spoke", spokes))
        for d in devices
    ]
    return Fabric.model_validate(
        {
            "name": name,
            "network": network,
            "rides": "black",
            "shape": shape,
            "technology": technology,
            "members": members,
        }
    )
