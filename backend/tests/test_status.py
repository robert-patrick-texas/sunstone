"""Status: the rules for what is operational, degraded, and offline."""

from collections.abc import Set
from datetime import UTC, datetime

import pytest

from sunstone.layers import Layers
from sunstone.live import DeviceState, InterfaceState, NetworkState, TunnelState
from sunstone.model import Topology, device_ends
from sunstone.problems import LiveView
from sunstone.status import NetworkStatus, Statuses

NOW = datetime(2026, 11, 7, 15, 0, tzinfo=UTC)


def cable(a: str, b: str, **extra: object) -> dict:
    return {
        "a": {"device": a.split(":")[0], "interface": a.split(":")[1]},
        "b": {"device": b.split(":")[0], "interface": b.split(":")[1]},
        "speed_mbps": 1000,
        **extra,
    }


def internet(end: str, circuit: str) -> dict:
    device, port = end.split(":")
    return {
        "a": {"device": device, "interface": port},
        "b": {"transport": "INET"},
        "speed_mbps": 500,
        "kind": "wan",
        "circuit": {"provider": "Northwind Fiber", "circuit_id": circuit},
    }


@pytest.fixture
def topology() -> Topology:
    """Region Texas (inside South) with sites A, B, C; region North with D.
    A has the core; B has a floor of its own; D is on the Internet twice."""

    def site(code: str, region: str) -> dict:
        return {"code": code, "name": code, "region": region, "lat": 30, "lon": -97}

    def device(name: str, site: str, role: str = "wan-edge", **extra: str) -> dict:
        return {"name": name, "site": site, "role": role, **extra}

    return Topology.model_validate(
        {
            "name": "Enterprise",
            "regions": [
                {"name": "South"},
                {"name": "Texas", "parent": "South"},
                {"name": "North"},
            ],
            "sites": [
                site("A", "Texas"),
                site("B", "Texas"),
                site("C", "Texas"),
                site("D", "North"),
            ],
            "locations": [{"site": "B", "name": "Floor 1"}],
            "devices": [
                device("a-core-01", "A", "core"),
                device("a-wan-01", "A"),
                device("b-wan-01", "B"),
                device("b-acc-01", "B", "access", location="Floor 1"),
                device("b-acc-02", "B", "access"),
                device("c-wan-01", "C"),
                device("d-wan-01", "D"),
            ],
            "links": [
                cable("a-core-01:p1", "a-wan-01:p1"),
                cable("a-wan-01:p2", "b-wan-01:p1"),
                cable("b-wan-01:p2", "c-wan-01:p1"),
                cable("a-wan-01:p3", "c-wan-01:p2"),
                cable("b-wan-01:p3", "b-acc-01:p1"),
                cable("b-wan-01:p4", "b-acc-02:p1"),
                cable("c-wan-01:p3", "d-wan-01:p1"),
                internet("a-wan-01:i1", "NO-A"),
                internet("d-wan-01:i1", "NO-D1"),
                internet("d-wan-01:i2", "NO-D2"),
            ],
            "networks": [
                {"name": "black", "boundary": "outside", "anchors": ["A"]},
                {"name": "blue", "anchors": ["A"]},
                {"name": "red", "tenant": "T", "rides": ["blue"]},
            ],
            "tenants": [{"name": "T"}],
            "transports": [{"name": "INET", "kind": "internet", "network": "black"}],
            "externals": [
                {"name": "r-a", "kind": "tenant", "tenant": "T", "network": "red"},
                {"name": "r-d", "kind": "tenant", "tenant": "T", "network": "red"},
            ],
            "tunnels": [
                {
                    "name": "BLUE-A-D",
                    "network": "blue",
                    "rides": "black",
                    "a": {
                        "device": "a-wan-01",
                        "interface": "Tunnel1",
                        "source": "Loopback0",
                    },
                    "b": {
                        "device": "d-wan-01",
                        "interface": "Tunnel1",
                        "source": "Loopback0",
                    },
                }
            ],
        }
    )


def red_handoffs(topology: Topology) -> Topology:
    """The topology with the tenant's encryptors handed off at A and D."""
    extra = [
        {
            "a": {"device": "a-wan-01", "interface": "r1"},
            "b": {"external": "r-a"},
            "speed_mbps": 1000,
        },
        {
            "a": {"device": "d-wan-01", "interface": "r1"},
            "b": {"external": "r-d"},
            "speed_mbps": 1000,
        },
    ]
    data = topology.model_dump(exclude={"links": {"__all__": {"id"}}})
    data["links"] += extra
    return Topology.model_validate(data)


def view(
    topology: Topology,
    down: Set[str] = frozenset(),
    cut: Set[str] = frozenset(),
    tunnels: list[TunnelState] | None = None,
) -> LiveView:
    """A snapshot with every device and port up but those said otherwise.

    ``cut`` names links by their A end, as ``device:port``.
    """
    devices = [
        DeviceState(
            device=d.name,
            status="down" if d.name in down else "up",
            observed_at=NOW,
            stale=False,
            reachability=[],
        )
        for d in topology.devices
    ]
    interfaces = [
        InterfaceState(
            device=e.device,
            interface=e.interface,
            oper="down" if f"{link.a.device}:{link.a.interface}" in cut else "up",
            in_pct=1,
            out_pct=1,
            observed_at=NOW,
            stale=False,
        )
        for link in topology.links
        for e in device_ends(link)
    ]
    state = NetworkState(
        source="test",
        generated_at=NOW,
        positions=[],
        devices=devices,
        interfaces=interfaces,
        tunnels=tunnels or [],
    )
    return LiveView(state)


def groups(status: NetworkStatus) -> dict[str, str]:
    return {g.id: g.status for g in status.groups}


def whole(
    topology: Topology, down: Set[str] = frozenset(), cut: Set[str] = frozenset()
) -> NetworkStatus:
    return Statuses(topology).report(NOW, view(topology, down, cut)).whole


def test_everything_up_is_operational(topology: Topology) -> None:
    w = whole(topology)
    assert (w.name, w.status, w.groups, w.sites, w.reached) == (
        "Enterprise",
        "operational",
        [],
        4,
        4,
    )


def test_inside_a_site_stays_at_the_site(topology: Topology) -> None:
    w = whole(topology, down={"b-acc-02"})
    assert w.status == "operational"
    assert groups(w) == {"B": "degraded"}
    b = next(g for g in w.groups if g.id == "B")
    assert b.reasons == ["b-acc-02 down", "b-wan-01 – b-acc-02 down"]


def test_a_link_between_sites_degrades_them_and_their_region(
    topology: Topology,
) -> None:
    w = whole(topology, cut={"a-wan-01:p2"})
    assert w.status == "operational"
    assert groups(w) == {"Texas": "degraded", "A": "degraded", "B": "degraded"}


def test_a_site_cut_off_raises_every_level(topology: Topology) -> None:
    w = whole(topology, cut={"a-wan-01:p2", "b-wan-01:p2"})
    assert w.status == "degraded"
    assert groups(w) == {
        "South": "degraded",
        "Texas": "degraded",
        "A": "degraded",
        "B": "offline",
        "C": "degraded",
        "B/Floor 1": "offline",
    }
    assert "B offline" in w.reasons


def test_a_location_cut_off_raises_every_level(topology: Topology) -> None:
    w = whole(topology, down={"b-acc-01"})
    assert w.status == "degraded"
    assert groups(w)["B/Floor 1"] == "offline"
    assert groups(w)["South"] == "degraded"
    assert w.reasons == ["Floor 1 offline"]


def test_a_circuit_into_a_transport_belongs_to_the_whole(topology: Topology) -> None:
    w = whole(topology, cut={"d-wan-01:i1"})
    assert w.status == "degraded"
    assert groups(w) == {"North": "degraded", "D": "degraded"}
    assert w.reasons == ["Circuit NO-D1 down"]


def test_a_region_reached_only_from_outside_is_partitioned(topology: Topology) -> None:
    # C keeps its way to the core through D and the Internet.
    w = whole(topology, cut={"b-wan-01:p2", "a-wan-01:p3"})
    texas = next(g for g in w.groups if g.id == "Texas")
    assert texas.status == "degraded"
    assert "partitioned into 2 parts" in texas.reasons
    assert "C" not in {g.id for g in w.groups if g.status == "offline"}


def test_a_network_over_a_degraded_one_works_with_a_caveat(topology: Topology) -> None:
    # One of D's two Internet circuits down: black is degraded at D, blue works.
    report = Statuses(topology).report(NOW, view(topology, cut={"d-wan-01:i1"}))
    black, blue, _ = report.networks
    assert (black.status, groups(black)) == (
        "degraded",
        {"North": "degraded", "D": "degraded"},
    )
    assert (blue.status, blue.caveats) == (
        "operational",
        ["black degraded at D: Circuit NO-D1 down"],
    )


def test_a_two_site_network_is_offline_when_one_site_is(topology: Topology) -> None:
    down = [TunnelState(tunnel="BLUE-A-D", network="blue", status="down")]
    report = Statuses(topology).report(NOW, view(topology, tunnels=down))
    blue = report.networks[1]
    assert (blue.status, blue.reached, blue.tunnels_down) == (
        "offline",
        1,
        ["BLUE-A-D"],
    )
    assert blue.reasons[0] == "no two sites reach each other"


def test_the_whole_works_on_while_its_anchors_are_cut_off(topology: Topology) -> None:
    # A is cut off from the rest, which still reach each other.
    w = whole(topology, cut={"a-wan-01:p2", "a-wan-01:p3", "a-wan-01:i1"})
    assert w.status == "degraded"
    assert {g.id for g in w.groups if g.status == "offline"} >= {"B", "C", "D"}
    assert w.reached == 1


def test_a_tenants_network_reaches_across_what_it_rides(topology: Topology) -> None:
    layered = red_handoffs(topology)
    statuses = Statuses(layered)
    red = statuses.report(NOW, view(layered)).networks[2]
    assert (red.name, red.status, red.sites, red.reached) == (
        "red",
        "operational",
        2,
        2,
    )
    down = [TunnelState(tunnel="BLUE-A-D", network="blue", status="down")]
    red = statuses.report(NOW, view(layered, tunnels=down)).networks[2]
    assert (red.status, red.reached) == ("offline", 1)


def test_tunnels_follow_what_they_ride(topology: Topology) -> None:
    layers = Layers(topology)
    assert layers.tunnels_up(set(), set()) == {"BLUE-A-D": True}
    both = {
        link.id
        for link in topology.links
        if link.a.device == "d-wan-01" and "i" in link.a.interface
    }
    assert layers.tunnels_up(set(), both) == {"BLUE-A-D": False}
    assert layers.tunnels_up(set(), set(), failing={"BLUE-A-D"}) == {"BLUE-A-D": False}
    assert layers.tunnels_up({"d-wan-01"}, set()) == {"BLUE-A-D": False}


def test_files_without_groups_have_flat_regions(topology: Topology) -> None:
    flat = Topology.model_validate(
        {
            **topology.model_dump(exclude={"links": {"__all__": {"id"}}}),
            "regions": [],
            "name": None,
        }
    )
    w = whole(flat, cut={"a-wan-01:p2", "b-wan-01:p2"})
    assert w.name == "Network"
    assert groups(w)["Texas"] == "degraded"
    assert "South" not in groups(w)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d["regions"].append({"name": "Texas"}), "duplicate region name"),
        (
            lambda d: d["regions"][0].update(parent="Texas"),
            "region 'South' is inside itself",
        ),
        (
            lambda d: d["sites"][0].update(region="Oklahoma"),
            "unknown region 'Oklahoma'",
        ),
        (
            lambda d: d["devices"][4].update(location="Floor 9"),
            "unknown location 'Floor 9'",
        ),
        (
            lambda d: d["locations"].append({"site": "Z", "name": "X"}),
            "unknown site 'Z'",
        ),
        (lambda d: d["networks"][0].update(anchors=["Q"]), "unknown anchor site 'Q'"),
        (
            lambda d: d["networks"][1].update(regions={"r1": ["A", "B"], "r2": ["B"]}),
            "puts site 'B' in 2 regions",
        ),
    ],
)
def test_invalid_groups_are_rejected(topology: Topology, change, message) -> None:
    data = topology.model_dump(exclude={"links": {"__all__": {"id"}}})
    change(data)
    with pytest.raises(ValueError, match=message):
        Topology.model_validate(data)


def test_a_fabric_tunnel_down_is_named_by_its_fabric_and_ends(
    topology: Topology,
) -> None:
    data = topology.model_dump(exclude={"links": {"__all__": {"id"}}})
    data["networks"].append({"name": "corp", "anchors": ["A"]})
    data["fabrics"] = [
        {
            "name": "DMVPN",
            "network": "corp",
            "rides": "black",
            "shape": "hub-spoke",
            "members": [
                {"device": "a-wan-01", "interface": "Tunnel100", "role": "hub"},
                {"device": "d-wan-01", "interface": "Tunnel100", "role": "spoke"},
            ],
        }
    ]
    layered = Topology.model_validate(data)
    down = [
        TunnelState(tunnel="DMVPN:d-wan-01~a-wan-01", network="corp", status="down")
    ]
    report = Statuses(layered).report(NOW, view(layered, tunnels=down))
    corp = next(n for n in report.networks if n.network == "corp")
    assert corp.status == "offline"
    assert "DMVPN: d-wan-01 – a-wan-01 down" in corp.reasons


def test_the_internet_joins_what_the_whole_holds(topology: Topology) -> None:
    # D still reaches the rest over its circuits: the whole is not partitioned.
    w = whole(topology, cut={"c-wan-01:p3"})
    assert w.status == "degraded"
    assert not [r for r in w.reasons if "partitioned" in r]
