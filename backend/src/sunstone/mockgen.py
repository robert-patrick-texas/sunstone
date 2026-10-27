"""Generate mock topologies for the prototype.

Two hub data centers, each with a WAN edge, core, distribution, and access
tier, and branch sites dual-homed to both hubs over carrier circuits. Every
access switch uplinks to a distribution pair, and pairs are joined by
two-member LAGs, so the hierarchy and neighbor views have realistic shapes.

With ``--oncall``, it also writes an on-call directory for the topology:
a team for WAN circuits, one for the hub data centers, one per area of the
country, and a NOC team for everything else, each with fictional people on
a rotation, and contacts for the fictional carriers.

Usage::

    uv run python -m sunstone.mockgen --preset large -o ../data/sample/large.yaml \
        --oncall ../data/sample/large.oncall.yaml
"""

import argparse
import random
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

from sunstone.model import Circuit, Device, Endpoint, Link, Role, Site, Topology
from sunstone.oncall import (
    DEFAULT_URGENCY,
    Carrier,
    Directory,
    HandoverTimes,
    Match,
    Person,
    Rotation,
    Route,
    Team,
)

# (code, name, region, lat, lon). The first two are the hubs.
CITIES = [
    ("DAL", "Dallas DC", "South", 32.7767, -96.7970),
    ("IAD", "Ashburn DC", "Mid-Atlantic", 39.0438, -77.4874),
    ("HOU", "Houston", "South", 29.7604, -95.3698),
    ("AUS", "Austin", "South", 30.2672, -97.7431),
    ("SAT", "San Antonio", "South", 29.4241, -98.4936),
    ("FTW", "Fort Worth", "South", 32.7555, -97.3308),
    ("ELP", "El Paso", "South", 31.7619, -106.4850),
    ("OKC", "Oklahoma City", "South", 35.4676, -97.5164),
    ("TUL", "Tulsa", "South", 36.1540, -95.9928),
    ("LIT", "Little Rock", "South", 34.7465, -92.2896),
    ("MSY", "New Orleans", "South", 29.9511, -90.0715),
    ("BTR", "Baton Rouge", "South", 30.4515, -91.1871),
    ("MEM", "Memphis", "Southeast", 35.1495, -90.0490),
    ("BNA", "Nashville", "Southeast", 36.1627, -86.7816),
    ("ATL", "Atlanta", "Southeast", 33.7490, -84.3880),
    ("BHM", "Birmingham", "Southeast", 33.5186, -86.8104),
    ("JAX", "Jacksonville", "Southeast", 30.3322, -81.6557),
    ("MCO", "Orlando", "Southeast", 28.5383, -81.3792),
    ("TPA", "Tampa", "Southeast", 27.9506, -82.4572),
    ("MIA", "Miami", "Southeast", 25.7617, -80.1918),
    ("CLT", "Charlotte", "Southeast", 35.2271, -80.8431),
    ("RDU", "Raleigh", "Southeast", 35.7796, -78.6382),
    ("RIC", "Richmond", "Mid-Atlantic", 37.5407, -77.4360),
    ("DCA", "Washington", "Mid-Atlantic", 38.9072, -77.0369),
    ("BWI", "Baltimore", "Mid-Atlantic", 39.2904, -76.6122),
    ("PHL", "Philadelphia", "Mid-Atlantic", 39.9526, -75.1652),
    ("NYC", "New York", "Northeast", 40.7128, -74.0060),
    ("EWR", "Newark", "Northeast", 40.7357, -74.1724),
    ("BOS", "Boston", "Northeast", 42.3601, -71.0589),
    ("BDL", "Hartford", "Northeast", 41.7658, -72.6734),
    ("PVD", "Providence", "Northeast", 41.8240, -71.4128),
    ("ALB", "Albany", "Northeast", 42.6526, -73.7562),
    ("BUF", "Buffalo", "Northeast", 42.8864, -78.8784),
    ("PIT", "Pittsburgh", "Northeast", 40.4406, -79.9959),
    ("CLE", "Cleveland", "Midwest", 41.4993, -81.6944),
    ("CMH", "Columbus", "Midwest", 39.9612, -82.9988),
    ("CVG", "Cincinnati", "Midwest", 39.1031, -84.5120),
    ("DTW", "Detroit", "Midwest", 42.3314, -83.0458),
    ("IND", "Indianapolis", "Midwest", 39.7684, -86.1581),
    ("SDF", "Louisville", "Midwest", 38.2527, -85.7585),
    ("ORD", "Chicago", "Midwest", 41.8781, -87.6298),
    ("MKE", "Milwaukee", "Midwest", 43.0389, -87.9065),
    ("MSP", "Minneapolis", "Midwest", 44.9778, -93.2650),
    ("DSM", "Des Moines", "Midwest", 41.5868, -93.6250),
    ("STL", "St. Louis", "Midwest", 38.6270, -90.1994),
    ("MCI", "Kansas City", "Midwest", 39.0997, -94.5786),
    ("OMA", "Omaha", "Midwest", 41.2565, -95.9345),
    ("ICT", "Wichita", "Midwest", 37.6872, -97.3301),
    ("DEN", "Denver", "Mountain", 39.7392, -104.9903),
    ("ABQ", "Albuquerque", "Mountain", 35.0844, -106.6504),
    ("PHX", "Phoenix", "Mountain", 33.4484, -112.0740),
    ("TUS", "Tucson", "Mountain", 32.2226, -110.9747),
    ("LAS", "Las Vegas", "Mountain", 36.1699, -115.1398),
    ("SLC", "Salt Lake City", "Mountain", 40.7608, -111.8910),
    ("BOI", "Boise", "Mountain", 43.6150, -116.2023),
    ("LAX", "Los Angeles", "West", 34.0522, -118.2437),
    ("SAN", "San Diego", "West", 32.7157, -117.1611),
    ("SFO", "San Francisco", "West", 37.7749, -122.4194),
    ("SJC", "San Jose", "West", 37.3382, -121.8863),
    ("SMF", "Sacramento", "West", 38.5816, -121.4944),
    ("PDX", "Portland", "West", 45.5152, -122.6784),
    ("SEA", "Seattle", "West", 47.6062, -122.3321),
    ("GEG", "Spokane", "West", 47.6588, -117.4260),
]

# Fictional carriers: this is mock data and should not look like a real network.
PROVIDERS = [
    "Northwind Fiber",
    "Bluebonnet Telecom",
    "Crestline Networks",
    "Mesa Carrier",
    "Harbor Transit",
]
PLATFORMS: dict[Role, str] = {
    "wan-edge": "ASR1001-X",
    "core": "N9K-C9364C",
    "distribution": "C9500-48Y4C",
    "access": "C9300-48P",
}
NAME_PART: dict[Role, str] = {
    "wan-edge": "wan",
    "core": "core",
    "distribution": "dist",
    "access": "acc",
}
PORT_PREFIX = {
    100_000: "HundredGigE1/0/",
    10_000: "TenGigabitEthernet1/0/",
    1_000: "GigabitEthernet1/0/",
}


# Fictional people for the on-call directory.
FIRST_NAMES = [
    "Pat", "Sam", "Lee", "Robin", "Alex", "Jordan", "Casey", "Morgan", "Riley",
    "Quinn", "Avery", "Drew", "Jamie", "Kai", "Noel", "Reese", "Sage", "Rowan",
]  # fmt: skip
LAST_NAMES = [
    "Rivera", "Chen", "Okafor", "Novak", "Haddad", "Lindqvist", "Moreau", "Tanaka",
    "Ibarra", "Kowalski", "Mensah", "Varga", "Duarte", "Byrne", "Sato", "Abara",
]  # fmt: skip
# Area teams: (id, name, regions, time zone). Areas without sites are left out.
AREAS = [
    ("network-central", "Network Central", ["South", "Midwest"], "America/Chicago"),
    (
        "network-east",
        "Network East",
        ["Southeast", "Northeast", "Mid-Atlantic"],
        "America/New_York",
    ),
    ("network-west", "Network West", ["West", "Mountain"], "America/Denver"),
]
# A Monday, when every rotation's first turn began.
ROTATIONS_START = date(2026, 1, 5)


@dataclass(frozen=True)
class Preset:
    """Size of a generated topology."""

    sites: int
    hub_dist_pairs: int
    hub_access_per_pair: int
    branch_access: tuple[int, int]


PRESETS = {
    "small": Preset(
        sites=5, hub_dist_pairs=1, hub_access_per_pair=6, branch_access=(4, 8)
    ),
    "large": Preset(
        sites=63, hub_dist_pairs=3, hub_access_per_pair=16, branch_access=(20, 66)
    ),
}


class _Builder:
    """Collects devices and links, handing out interface and LAG names."""

    def __init__(self, rng: random.Random, sites: list[Site]) -> None:
        self.rng = rng
        self.devices: list[Device] = []
        self.links: list[Link] = []
        self._site_index = {s.code: i + 1 for i, s in enumerate(sites)}
        self._per_site: Counter[str] = Counter()
        self._ports: Counter[tuple[str, int]] = Counter()
        self._lags: Counter[str] = Counter()

    def device(self, site: Site, role: Role, n: int) -> str:
        """Add a device.

        Args:
            site: Where it is.
            role: Its tier.
            n: Its number within the site and role.

        Returns:
            The device name, such as ``dal-core-01``.

        Raises:
            None
        """
        self._per_site[site.code] += 1
        name = f"{site.code.lower()}-{NAME_PART[role]}-{n:02d}"
        mgmt_ip = f"10.{self._site_index[site.code]}.0.{self._per_site[site.code]}"
        self.devices.append(
            Device(
                name=name,
                site=site.code,
                role=role,
                platform=PLATFORMS[role],
                mgmt_ip=mgmt_ip,
            )
        )
        return name

    def link(
        self,
        a: str,
        b: str,
        speed_mbps: int,
        members: int = 1,
        circuit: Circuit | None = None,
    ) -> None:
        """Connect two devices, as a LAG when ``members`` is more than one.

        Args:
            a: First device name.
            b: Second device name.
            speed_mbps: Speed of each member link.
            members: Number of parallel links; more than one forms a LAG.
            circuit: Carrier circuit; makes the link a WAN link.

        Raises:
            None
        """
        lag_a = self._next_lag(a) if members > 1 else None
        lag_b = self._next_lag(b) if members > 1 else None
        for _ in range(members):
            port_a = self._next_port(a, speed_mbps)
            port_b = self._next_port(b, speed_mbps)
            self.links.append(
                Link(
                    a=Endpoint(device=a, interface=port_a, lag=lag_a),
                    b=Endpoint(device=b, interface=port_b, lag=lag_b),
                    speed_mbps=speed_mbps,
                    kind="wan" if circuit else "lan",
                    circuit=circuit,
                )
            )

    def circuit(self) -> Circuit:
        """Make up a carrier circuit.

        Returns:
            A circuit from a random fictional provider.

        Raises:
            None
        """
        provider = self.rng.choice(PROVIDERS)
        number = self.rng.randrange(100_000, 1_000_000)
        return Circuit(provider=provider, circuit_id=f"{provider[:2].upper()}-{number}")

    def _next_port(self, device: str, speed_mbps: int) -> str:
        self._ports[(device, speed_mbps)] += 1
        return f"{PORT_PREFIX[speed_mbps]}{self._ports[(device, speed_mbps)]}"

    def _next_lag(self, device: str) -> str:
        self._lags[device] += 1
        return f"Port-channel{self._lags[device]}"


def _build_site(b: _Builder, site: Site, hub: bool, preset: Preset) -> list[str]:
    """Add one site's devices and internal links.

    Args:
        b: The builder to add to.
        site: The site.
        hub: True for a hub data center, False for a branch.
        preset: Sizes to use.

    Returns:
        The names of the site's two WAN edge routers.

    Raises:
        None
    """
    wans = [b.device(site, "wan-edge", i) for i in (1, 2)]
    if hub:
        cores = [b.device(site, "core", i) for i in (1, 2)]
        for w in wans:
            for c in cores:
                b.link(w, c, 100_000)
        b.link(cores[0], cores[1], 100_000, members=2)
        uplinks, uplink_speed = cores, 100_000
        pairs, per_pair = preset.hub_dist_pairs, preset.hub_access_per_pair
    else:
        uplinks, uplink_speed = wans, 10_000
        pairs, per_pair = 1, b.rng.randint(*preset.branch_access)
    access_n = 0
    for p in range(pairs):
        dists = [b.device(site, "distribution", 2 * p + i) for i in (1, 2)]
        for d in dists:
            for u in uplinks:
                b.link(u, d, uplink_speed)
        b.link(dists[0], dists[1], 10_000, members=2)
        for _ in range(per_pair):
            access_n += 1
            access = b.device(site, "access", access_n)
            for d in dists:
                b.link(d, access, 10_000)
    return wans


def generate(preset: Preset, seed: int) -> Topology:
    """Generate a topology.

    Args:
        preset: Sizes to use.
        seed: Random seed; the same seed and preset give the same topology.

    Returns:
        The generated, validated topology.

    Raises:
        ValueError: If the preset asks for fewer than 2 or more sites than
            there are cities.
    """
    if not 2 <= preset.sites <= len(CITIES):
        raise ValueError(f"sites must be between 2 and {len(CITIES)}")
    rng = random.Random(seed)
    sites = [
        Site(code=code, name=name, region=region, lat=lat, lon=lon)
        for code, name, region, lat, lon in CITIES[: preset.sites]
    ]
    b = _Builder(rng, sites)
    hub_wans = [_build_site(b, s, True, preset) for s in sites[:2]]
    for i in range(2):
        b.link(hub_wans[0][i], hub_wans[1][i], 100_000, circuit=b.circuit())
    for site in sites[2:]:
        wans = _build_site(b, site, False, preset)
        # Dual-homed: wan-01 to the first hub, wan-02 to the second.
        for i in range(2):
            speed = rng.choice([1_000, 10_000])
            b.link(wans[i], hub_wans[i][i], speed, circuit=b.circuit())
    return Topology(sites=sites, devices=b.devices, links=b.links)


def generate_directory(topology: Topology, seed: int) -> Directory:
    """Generate an on-call directory for a topology.

    Args:
        topology: The topology the teams own.
        seed: Random seed; the same seed and topology give the same directory.

    Returns:
        Teams for WAN circuits, the hub data centers, each area with branch
        sites, and everything else, in that order of routes; fictional people with
        phone numbers from the range kept for fiction (555-0100 to 555-0199);
        a contact for each carrier; and the NOC's two 12-hour shifts, changing
        at 07:00 and 19:00 in Dallas.

    Raises:
        None
    """
    rng = random.Random(seed)
    names = rng.sample([f"{f} {last}" for f in FIRST_NAMES for last in LAST_NAMES], 60)
    people: list[Person] = []

    def hire(count: int) -> list[str]:
        hired = []
        for _ in range(count):
            name = names.pop()
            person_id = name.lower().replace(" ", "-")
            phone = f"+1 214 555 01{len(people):02d}"
            people.append(Person(id=person_id, name=name, phone=phone))
            hired.append(person_id)
        return hired

    def team(head: tuple[str, str], rotation: dict, size: int) -> Team:
        team_id, name = head
        return Team(
            id=team_id,
            name=name,
            rotation=Rotation(people=hire(size), starts=ROTATIONS_START, **rotation),
            manager=hire(1)[0],
        )

    weekly = {"every_days": 7, "handoff": "09:00"}
    daily = {"every_days": 1, "handoff": "08:00", "timezone": "America/Chicago"}
    teams = [
        team(("wan", "WAN and carriers"), daily, 3),
        team(
            ("datacenter", "Data centers"), weekly | {"timezone": "America/Chicago"}, 4
        ),
    ]
    routes = [
        Route(match=Match(kinds=["wan"]), team="wan"),
        Route(
            match=Match(sites=[s.code for s in topology.sites[:2]]), team="datacenter"
        ),
    ]
    # The hubs are the data centers' whatever their region.
    regions = {s.region for s in topology.sites[2:] if s.region}
    for team_id, name, area, zone in AREAS:
        present = [r for r in area if r in regions]
        if present:
            teams.append(team((team_id, name), weekly | {"timezone": zone}, 4))
            routes.append(Route(match=Match(regions=present), team=team_id))
    teams.append(team(("noc", "NOC"), daily | {"handoff": "07:00"}, 3))
    routes.append(Route(team="noc"))
    providers = sorted({ln.circuit.provider for ln in topology.links if ln.circuit})
    carriers = [
        Carrier(
            provider=p,
            phone=f"+1 800 555 01{i:02d}",
            portal=f"https://noc.{p.split()[0].lower()}.example",
        )
        for i, p in enumerate(providers)
    ]
    return Directory(
        people=people,
        teams=teams,
        routes=routes,
        carriers=carriers,
        urgency=dict(DEFAULT_URGENCY),
        handovers=HandoverTimes(at=["07:00", "19:00"], timezone="America/Chicago"),
    )


def directory_yaml(directory: Directory, header: str) -> str:
    """Render an on-call directory as the YAML the loader reads.

    Args:
        directory: The directory.
        header: Comment placed at the top of the file.

    Returns:
        YAML text that spells out rotations and escalation, but leaves out
        empty conditions.

    Raises:
        None
    """
    data = directory.model_dump(mode="json", exclude_none=True)
    for route in data["routes"]:
        match = {k: v for k, v in route.pop("match").items() if v}
        if match:
            route["match"] = match
    body = yaml.safe_dump(data, sort_keys=False, default_flow_style=None, width=120)
    return f"# {header}\n{body}"


def to_yaml(topology: Topology, header: str) -> str:
    """Render a topology as the YAML the loader reads.

    Args:
        topology: The topology.
        header: Comment placed at the top of the file.

    Returns:
        YAML text without computed fields, defaults, or empty values.

    Raises:
        None
    """
    data = topology.model_dump(
        mode="json",
        exclude_none=True,
        exclude_defaults=True,
        exclude={"links": {"__all__": {"id"}}},
    )
    body = yaml.safe_dump(data, sort_keys=False, default_flow_style=None, width=120)
    return f"# {header}\n{body}"


def main() -> None:
    """Write a generated topology to a file.

    Raises:
        SystemExit: On invalid arguments.
    """
    parser = argparse.ArgumentParser(description="Generate a mock Sunstone topology.")
    parser.add_argument("--preset", choices=sorted(PRESETS), default="small")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument("--oncall", type=Path, help="also write an on-call directory")
    args = parser.parse_args()

    topology = generate(PRESETS[args.preset], args.seed)
    header = (
        f"Mock data, not a real network. Generated by: "
        f"sunstone.mockgen --preset {args.preset} --seed {args.seed}"
    )
    args.output.write_text(to_yaml(topology, header), encoding="utf-8")
    print(
        f"{args.output}: {len(topology.sites)} sites, {len(topology.devices)} devices, "
        f"{len(topology.links)} links"
    )
    if args.oncall:
        directory = generate_directory(topology, args.seed)
        args.oncall.write_text(directory_yaml(directory, header), encoding="utf-8")
        print(
            f"{args.oncall}: {len(directory.teams)} teams, "
            f"{len(directory.people)} people"
        )


if __name__ == "__main__":
    main()
