from datetime import UTC, datetime, timedelta

import pytest

from sunstone.impact import Failures, Network
from sunstone.layouts import DeviceCenter, LinksCenter, SiteCenter
from sunstone.live import DeviceState, InterfaceState, NetworkState, Reachability
from sunstone.model import Topology
from sunstone.problems import LiveView, find_problems

AT = datetime(2026, 10, 27, 15, 0, tzinfo=UTC)
WAN = {"kind": "wan", "circuit": {"provider": "Mesa Carrier", "circuit_id": "ME-1"}}
CIRCUIT_TO_A = "a-wan-01:Gi1/0/1--c-wan-01:Gi1/0/1"


def link(a: str, b: str, speed: int = 10_000, **extra: object) -> dict:
    (ad, ai), (bd, bi) = a.split(":"), b.split(":")
    ends = {"a": {"device": ad, "interface": ai}, "b": {"device": bd, "interface": bi}}
    return {**ends, "speed_mbps": speed, **extra}


@pytest.fixture
def network() -> Network:
    """Hubs A and B with a core each; a-acc-01 hangs off a-core-01 by a
    two-link LAG; branch C's one router links to both hubs and to its two
    access switches. The web UI's unit tests use the same network."""
    lag = [
        {
            "a": {"device": "a-core-01", "interface": f"Te1/0/{i}", "lag": "Po1"},
            "b": {"device": "a-acc-01", "interface": f"Te1/0/{48 + i}", "lag": "Po10"},
            "speed_mbps": 10_000,
        }
        for i in (1, 2)
    ]
    topology = Topology.model_validate(
        {
            "sites": [
                {"code": "A", "name": "Hub A", "lat": 32.8, "lon": -96.8},
                {"code": "B", "name": "Hub B", "lat": 39.0, "lon": -77.5},
                {"code": "C", "name": "Branch C", "lat": 29.8, "lon": -95.4},
            ],
            "devices": [
                {"name": "a-wan-01", "site": "A", "role": "wan-edge"},
                {"name": "a-core-01", "site": "A", "role": "core"},
                {"name": "a-acc-01", "site": "A", "role": "access"},
                {"name": "b-wan-01", "site": "B", "role": "wan-edge"},
                {"name": "b-core-01", "site": "B", "role": "core"},
                {"name": "c-wan-01", "site": "C", "role": "wan-edge"},
                {"name": "c-acc-01", "site": "C", "role": "access"},
                {"name": "c-acc-02", "site": "C", "role": "access"},
            ],
            "links": [
                link("a-wan-01:Hu1/0/1", "a-core-01:Hu1/0/1", 100_000),
                *lag,
                link("b-wan-01:Hu1/0/1", "b-core-01:Hu1/0/1", 100_000),
                link("a-wan-01:Hu1/0/2", "b-wan-01:Hu1/0/2", 100_000, **WAN),
                link("c-wan-01:Gi1/0/1", "a-wan-01:Gi1/0/1", 1_000, **WAN),
                link("c-wan-01:Gi1/0/2", "b-wan-01:Gi1/0/1", 1_000, **WAN),
                link("c-wan-01:Te1/0/1", "c-acc-01:Te1/0/49"),
                link("c-wan-01:Te1/0/2", "c-acc-02:Te1/0/49"),
            ],
        }
    )
    return Network(topology)


def device(name: str, **extra: object) -> DeviceState:
    reachability = [Reachability(position="west", rtt_ms=2, loss_pct=0)]
    fields = {"status": "up", "observed_at": AT, "stale": False}
    return DeviceState.model_validate(
        {"device": name, **fields, "reachability": reachability, **extra}
    )


def reading(dev: str, ifname: str, **extra: object) -> InterfaceState:
    fields = {"oper": "up", "in_pct": 10, "out_pct": 20, "observed_at": AT}
    return InterfaceState.model_validate(
        {"device": dev, "interface": ifname, **fields, "stale": False, **extra}
    )


def problems_for(
    network: Network, devices: list[DeviceState], interfaces: list[InterfaceState]
):
    state = NetworkState(
        source="test",
        generated_at=AT,
        positions=[],
        devices=devices,
        interfaces=interfaces,
    )
    return find_problems(network, LiveView(state))


HUBS = ["a-core-01", "b-core-01", "a-wan-01", "b-wan-01"]


def test_reach_finds_where_redundancy_already_ends(network: Network) -> None:
    reach = network.reach(Failures())
    assert reach.reached == set(network.names)
    assert dict(reach.fragile) == {
        "a-acc-01": ("a-core-01",),
        "c-acc-01": ("c-wan-01",),
        "c-acc-02": ("c-wan-01",),
    }


def test_a_parallel_link_is_a_second_link_but_not_a_second_way(
    network: Network,
) -> None:
    member = next(i for i, ln in network.links.items() if ln.a.lag == "Po1")
    reach = network.reach(Failures(links=frozenset([member])))
    assert reach.fragile["a-acc-01"] == ("a-core-01",)


def test_a_failed_device_cuts_off_what_hangs_on_it_only(network: Network) -> None:
    impact = network.impact(Failures(devices=frozenset(["c-wan-01"])))
    assert impact.cut_off == ["c-acc-01", "c-acc-02"]
    assert impact.exposed == {}


def test_devices_that_lose_their_second_way_are_named_with_what_they_now_depend_on(
    network: Network,
) -> None:
    impact = network.impact(Failures(links=frozenset([CIRCUIT_TO_A])))
    assert impact.cut_off == []
    # The access switches had no redundancy to lose, so only the router counts.
    assert impact.exposed == {"c-wan-01": ["b-wan-01"]}


def test_a_whole_site_fails(network: Network) -> None:
    failures = network.failures_of([SiteCenter(kind="site", id="A")])
    impact = network.impact(failures)
    assert impact.failed.devices == ["a-acc-01", "a-core-01", "a-wan-01"]
    # One core device is left, so everything now depends on it.
    assert impact.exposed == {
        "b-wan-01": ["b-core-01"],
        "c-wan-01": ["b-core-01", "b-wan-01"],
    }


def test_earlier_failures_are_not_counted_again(network: Network) -> None:
    before = Failures(links=frozenset([CIRCUIT_TO_A]))
    impact = network.impact(Failures(devices=frozenset(["b-wan-01"])), before)
    assert impact.cut_off == ["c-acc-01", "c-acc-02", "c-wan-01"]
    assert impact.exposed == {"a-wan-01": ["a-core-01"]}


def test_what_if_says_when_everything_named_is_already_gone(network: Network) -> None:
    before = Failures(devices=frozenset(["c-wan-01"]))
    behind = network.failures_of([DeviceCenter(kind="device", id="c-acc-01")])
    assert network.what_if(behind, before).already
    hub = network.failures_of([DeviceCenter(kind="device", id="a-wan-01")])
    assert not network.what_if(hub, before).already
    assert not network.what_if(behind).already


def test_a_branch_whose_router_is_unreachable_is_one_outage(network: Network) -> None:
    problems = problems_for(
        network,
        [*(device(d) for d in HUBS), device("c-wan-01", status="down")],
        [
            reading("a-wan-01", "Gi1/0/1", oper="down"),
            reading("b-wan-01", "Gi1/0/1", oper="down"),
        ],
    )
    assert len(problems) == 1
    outage = problems[0]
    assert (outage.kind, outage.title, outage.detail) == (
        "outage",
        "C cut off",
        "3 devices · 2 circuits ME-1, ME-1 down",
    )
    assert outage.target == SiteCenter(kind="site", id="C")
    assert (outage.lost, outage.exposed) == (3, 0)
    # The router is where reach stops; its unmonitored switches are cut off behind it.
    assert outage.impact is not None
    assert outage.impact.failed.devices == ["c-wan-01"]
    assert outage.impact.cut_off == ["c-acc-01", "c-acc-02"]
    assert len(outage.impact.failed.links) == 2


def test_problems_are_ranked_and_described(network: Network) -> None:
    problems = problems_for(
        network,
        [
            *(device(d) for d in HUBS if d != "b-wan-01"),
            device(
                "b-wan-01",
                reachability=[Reachability(position="west", rtt_ms=30, loss_pct=2.5)],
            ),
            device("c-wan-01"),
            device("c-acc-01", stale=True, observed_at=AT - timedelta(minutes=10)),
        ],
        [
            reading("a-wan-01", "Gi1/0/1", oper="down"),
            reading("c-wan-01", "Gi1/0/1", oper="down"),
            reading("a-wan-01", "Hu1/0/2", out_pct=97, in_pct=12),
        ],
    )
    assert [(p.kind, p.title, p.detail) for p in problems] == [
        (
            "link-down",
            "Circuit ME-1 down",
            "c-wan-01 Gi1/0/1 ↔ a-wan-01 Gi1/0/1 · 1 device left without redundancy",
        ),
        ("congested", "Circuit ME-1 at 97%", "a-wan-01 Hu1/0/2 → b-wan-01 · 100G link"),
        ("loss", "b-wan-01", "2.5% from west"),
        ("nodata", "c-acc-01", "last reading 10 min before this snapshot"),
    ]
    assert problems[0].target == LinksCenter(kind="links", ids=[CIRCUIT_TO_A])
    assert problems[0].impact is not None
    assert problems[0].impact.exposed == {"c-wan-01": ["b-wan-01"]}


def test_a_link_keeps_its_id_whether_busy_or_congested(network: Network) -> None:
    hubs = [device(d) for d in HUBS]
    busy = problems_for(network, hubs, [reading("a-wan-01", "Hu1/0/2", out_pct=85)])
    hot = problems_for(network, hubs, [reading("a-wan-01", "Hu1/0/2", out_pct=99)])
    assert (busy[0].kind, hot[0].kind) == ("busy", "congested")
    assert busy[0].id == hot[0].id


def test_nothing_is_wrong_when_everything_is_up(network: Network) -> None:
    assert problems_for(network, [device(d) for d in HUBS], []) == []
