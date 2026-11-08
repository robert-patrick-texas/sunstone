"""Failures across the layers: "what if" through every network, and shared risk."""

import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sunstone.across import Across, Before, ProviderTarget
from sunstone.api import create_app
from sunstone.impact import Failures, Network
from sunstone.layouts import DeviceCenter
from sunstone.live import TunnelState
from sunstone.model import Topology
from sunstone.problems import Problem
from sunstone.status import Statuses


def cable(a: str, b: str, *networks: str) -> dict:
    return {
        "a": {"device": a.split(":")[0], "interface": a.split(":")[1]},
        "b": {"device": b.split(":")[0], "interface": b.split(":")[1]},
        "speed_mbps": 1000,
        "carries": [{"network": n} for n in networks],
    }


def internet(end: str, provider: str, circuit: str) -> dict:
    device, port = end.split(":")
    return {
        "a": {"device": device, "interface": port},
        "b": {"transport": "INET"},
        "speed_mbps": 500,
        "kind": "wan",
        "circuit": {"provider": provider, "circuit_id": circuit},
    }


def tunnel(name: str, network: str, rides: str, a: str, b: str) -> dict:
    def end(device: str) -> dict:
        return {"device": device, "interface": f"Tunnel-{name}", "source": "Loopback0"}

    return {"name": name, "network": network, "rides": rides, "a": end(a), "b": end(b)}


@pytest.fixture
def topology() -> Topology:
    """A data center A and a branch H, as Houston is built in the layered
    sample: two WAN switches with two Internet circuits each, a blue router
    trunked to both, and a grey router behind it with two grey tunnels to
    two grey routers at A."""

    def device(name: str, site: str, role: str = "wan-edge") -> dict:
        return {"name": name, "site": site, "role": role}

    return Topology.model_validate(
        {
            "name": "Enterprise",
            "regions": [{"name": "South"}],
            "sites": [
                {"code": "A", "name": "A", "region": "South", "lat": 30, "lon": -97},
                {"code": "H", "name": "H", "region": "South", "lat": 29, "lon": -95},
            ],
            "devices": [
                device("a-core-01", "A", "core"),
                device("a-wan-01", "A"),
                device("a-blu-01", "A"),
                device("a-gry-01", "A"),
                device("a-gry-02", "A"),
                device("h-wsw-01", "H"),
                device("h-wsw-02", "H"),
                device("h-blu-01", "H"),
                device("h-gry-01", "H"),
            ],
            "links": [
                cable("a-core-01:p1", "a-wan-01:p1"),
                cable("a-wan-01:p2", "a-blu-01:p1", "black"),
                cable("a-blu-01:p2", "a-gry-01:p1", "blue"),
                cable("a-blu-01:p3", "a-gry-02:p1", "blue"),
                internet("a-wan-01:i1", "Northwind Fiber", "NO-A"),
                internet("h-wsw-01:i1", "Northwind Fiber", "NO-H1"),
                internet("h-wsw-01:i2", "Crestline Networks", "CR-H1"),
                internet("h-wsw-02:i1", "Northwind Fiber", "NO-H2"),
                internet("h-wsw-02:i2", "Harbor Transit", "HA-H1"),
                cable("h-wsw-01:p1", "h-blu-01:p1", "black"),
                cable("h-wsw-02:p1", "h-blu-01:p2", "black"),
                cable("h-blu-01:p3", "h-gry-01:p1", "blue"),
            ],
            "networks": [
                {"name": "black", "boundary": "outside", "anchors": ["A"]},
                {"name": "blue", "anchors": ["A"]},
                {"name": "grey", "anchors": ["A"]},
            ],
            "transports": [{"name": "INET", "kind": "internet", "network": "black"}],
            "tunnels": [
                tunnel("BLUE-H-A", "blue", "black", "h-blu-01", "a-blu-01"),
                tunnel("GREY-H-A1", "grey", "blue", "h-gry-01", "a-gry-01"),
                tunnel("GREY-H-A2", "grey", "blue", "h-gry-01", "a-gry-02"),
            ],
        }
    )


@pytest.fixture
def across(topology: Topology) -> Across:
    return Across(Network(topology), Statuses(topology))


def device(name: str) -> Failures:
    return Failures(devices=frozenset([name]))


def by_network(answer) -> dict:
    return by_name(answer.networks)


def by_name(networks: list) -> dict:
    return {n.network: n for n in networks}


def test_a_switch_takes_two_circuits_and_blue_stays_up(across: Across) -> None:
    answer = by_network(across.what_if(device("h-wsw-01"), None))
    black = answer["black"]
    # Its two circuits and its trunk to the blue router.
    assert len(black.links_lost) == 3
    assert black.after.status == "operational"
    assert [(g.id, g.status) for g in black.after.groups] == [("H", "degraded")]
    blue = answer["blue"]
    assert (blue.before, blue.after.status, blue.tunnels_lost) == (
        "operational",
        "operational",
        [],
    )
    assert blue.after.caveats == ["black degraded at H: h-wsw-01 down"]
    assert answer["grey"].after.caveats


def test_a_router_beneath_grey_takes_both_its_tunnels(across: Across) -> None:
    answer = by_network(across.what_if(device("h-blu-01"), None))
    assert answer["blue"].tunnels_lost == ["BLUE-H-A"]
    grey = answer["grey"]
    assert (grey.tunnels, grey.tunnels_lost) == (2, ["GREY-H-A1", "GREY-H-A2"])
    assert grey.sites_lost == ["H"]
    # Two sites, and one of them cut off.
    assert grey.after.status == "offline"
    # Physically, the grey router is cut off behind it.
    assert across.what_if(device("h-blu-01"), None).impact.cut_off == ["h-gry-01"]


def test_a_site_split_inside_stays_the_sites_own(topology: Topology) -> None:
    # Without the blue router, H's switches reach each other only over the
    # Internet: H is degraded, but South's sites still reach each other.
    report = Statuses(topology).of(datetime.now(UTC), {"h-blu-01"}, set(), [])
    assert [(g.kind, g.id) for g in report.whole.groups] == [("site", "H")]
    assert report.whole.status == "operational"


def test_a_provider_fails_with_every_circuit_of_its(across: Across) -> None:
    failures = across.failures_of(
        [ProviderTarget(kind="provider", id="Northwind Fiber")]
    )
    assert len(failures.links) == 3
    answer = by_network(across.what_if(failures, None))
    # A's only circuit is Northwind's: blue's tunnel goes, and grey's with it.
    assert answer["blue"].tunnels_lost == ["BLUE-H-A"]
    assert answer["grey"].sites_lost == ["H"]
    assert across.failures_of([DeviceCenter(kind="device", id="h-gry-01")]) == device(
        "h-gry-01"
    )


def test_what_is_down_already_is_not_lost_again(across: Across) -> None:
    before = Before(
        Failures(),
        (TunnelState(tunnel="GREY-H-A1", network="grey", status="down"),),
    )
    grey = by_network(across.what_if(device("h-blu-01"), before))["grey"]
    assert grey.tunnels_lost == ["GREY-H-A2"]
    assert grey.after.status == "offline"


def test_each_moment_is_compared_with_its_own_before(topology: Topology) -> None:
    # What each moment compares with is kept: asking at one moment, then at
    # another, then at the first again, answers each as if asked first.
    across = Across(Network(topology), Statuses(topology))
    one = datetime(2026, 1, 1, tzinfo=UTC)
    two = datetime(2026, 1, 1, 0, 0, 10, tzinfo=UTC)
    down = Before(
        Failures(),
        (TunnelState(tunnel="GREY-H-A1", network="grey", status="down"),),
    )
    up = Before(Failures(), ())

    def grey(a: Across, before: Before, at: datetime):
        return by_network(a.what_if(device("h-blu-01"), before, at))["grey"]

    first = grey(across, down, one)
    second = grey(across, up, two)
    assert first.tunnels_lost == ["GREY-H-A2"]
    assert second.tunnels_lost == ["GREY-H-A1", "GREY-H-A2"]
    assert grey(across, down, one) == first
    assert second == grey(Across(Network(topology), Statuses(topology)), up, two)


TRUNKS = frozenset({"h-blu-01:p1--h-wsw-01:p1", "h-blu-01:p2--h-wsw-02:p1"})
TO_A_GRY_01 = "a-blu-01:p2--a-gry-01:p1"
TO_A_GRY_02 = "a-blu-01:p3--a-gry-02:p1"
AT = datetime(2026, 1, 1, tzinfo=UTC)


def problem(across: Across, name: str, failed: Failures) -> Problem:
    """A problem standing for some failures, as live state finds one."""
    return Problem(
        id=name,
        kind="outage",
        title=name,
        detail="",
        target=DeviceCenter(kind="device", id="a-core-01"),
        impact=across.network.impact(failed),
        lost=0,
        exposed=0,
    )


def reported(across: Across, now: Failures, *failing: str) -> list[TunnelState]:
    """The tunnels' states live state would show with some failures."""
    up = across.layers.tunnels_up(set(now.devices), set(now.links), failing)
    return [
        TunnelState(tunnel=t, network=n, status="up" if up[t] else "down")
        for t, n in across.layers.all_tunnels()
    ]


def test_fixing_a_problem_brings_back_what_it_takes_with_the_rest_down(
    across: Across,
) -> None:
    # H's blue router loses both trunks, and grey's first router at A its
    # only cable: two outages, with grey's first tunnel down at both ends.
    now = Failures(links=TRUNKS | {TO_A_GRY_01})
    problems = [
        problem(across, "h", Failures(links=TRUNKS)),
        problem(across, "a", Failures(links=frozenset([TO_A_GRY_01]))),
    ]
    answer = across.fixing(AT, now, reported(across, now), problems)
    h = by_name(answer["h"])
    assert (h["blue"].tunnels_lost, h["blue"].sites_lost) == (["BLUE-H-A"], ["H"])
    assert h["black"].links_lost == sorted(TRUNKS)
    # Fixing H brings back the second grey tunnel only: the first still
    # ends at a router cut off at A.
    assert (h["grey"].tunnels_lost, h["grey"].sites_lost) == (["GREY-H-A2"], ["H"])
    # Fixed, grey would be up, its first tunnel down degrading only the
    # groups it joins; as things are, its two sites cannot reach each other.
    assert (h["grey"].before, h["grey"].after.status) == ("operational", "offline")
    # Fixing A's cable brings back blue's link to it, and no grey tunnel
    # while H is still down.
    a = by_name(answer["a"])
    assert a["blue"].links_lost == [TO_A_GRY_01]
    assert "grey" not in a or a["grey"].tunnels_lost == []
    # The whole network's part is each problem's physical impact.
    assert all(n.network is not None for n in answer["h"] + answer["a"])


def test_fixing_an_outage_brings_back_the_links_down_inside_it(across: Across) -> None:
    # Live state shows the link between the two routers cut off at H down
    # too; fixing the outage brings it back with them.
    inside = "h-blu-01:p3--h-gry-01:p1"
    now = Failures(links=TRUNKS | {inside})
    answer = across.fixing(
        AT, now, reported(across, now), [problem(across, "h", Failures(links=TRUNKS))]
    )
    grey = by_name(answer["h"])["grey"]
    assert grey.tunnels_lost == ["GREY-H-A1", "GREY-H-A2"]
    assert by_name(answer["h"])["blue"].links_lost == [inside]


def test_a_tunnel_down_of_its_own_accord_stays_down_after_a_fix(across: Across) -> None:
    now = Failures(links=frozenset([TO_A_GRY_02]))
    # The first grey tunnel is down although everything it rides works.
    tunnels = reported(across, now, "GREY-H-A1")
    answer = across.fixing(AT, now, tunnels, [problem(across, "a", now)])
    grey = by_name(answer["a"])["grey"]
    assert (grey.tunnels_lost, grey.sites_lost) == (["GREY-H-A2"], ["H"])
    # Asked again with the same things down, the answer is kept.
    assert across.fixing(AT, now, tunnels, [problem(across, "a", now)]) == answer


def test_shared_risks_on_top_of_what_is_down(across: Across) -> None:
    # With one of H's switches down, the other carries grey's tunnels alone.
    now = Failures(devices=frozenset(["h-wsw-01"]))
    grey = across.risks(now, reported(across, now)).networks[0]
    new = [r for r in grey.risks if r.new]
    assert [[(i.kind, i.id) for i in r.items] for r in new] == [
        [("device", "h-wsw-02"), ("link", "h-blu-01:p2--h-wsw-02:p1")]
    ]
    assert (new[0].tunnels, new[0].sites) == (["GREY-H-A1", "GREY-H-A2"], ["H"])
    # What was a risk on the network as documented still is, and is not
    # new; what is down already is no risk.
    old = next(r for r in grey.risks if not r.new)
    assert ("provider", "Northwind Fiber") in [(i.kind, i.id) for i in old.items]
    assert "h-wsw-01" not in {i.id for r in grey.risks for i in r.items}
    assert not any(r.new for r in across.risks().networks[0].risks)


def test_networks_nothing_reaches_are_left_out(across: Across) -> None:
    answer = across.what_if(device("a-gry-02"), None)
    # Its link to the blue router carries blue; black is not reached.
    assert [n.network for n in answer.networks] == [None, "blue", "grey"]
    grey = by_network(answer)["grey"]
    assert grey.tunnels_lost == ["GREY-H-A2"]
    assert grey.sites_lost == []


def test_shared_risks_gather_what_takes_the_same_tunnels(across: Across) -> None:
    report = across.risks()
    # Blue has one tunnel, which shares nothing.
    assert [n.network for n in report.networks] == ["grey"]
    grey = report.networks[0]
    assert grey.tunnels == 2
    assert len(grey.risks) == 1
    risk = grey.risks[0]
    assert (risk.tunnels, risk.sites) == (["GREY-H-A1", "GREY-H-A2"], ["H"])
    items = [(i.kind, i.id) for i in risk.items]
    # Providers first; grey's own tunnel ends are not risks of its.
    assert items[0] == ("provider", "Northwind Fiber")
    assert ("device", "h-blu-01") in items
    assert ("device", "a-blu-01") in items
    assert not {"h-gry-01", "a-gry-01", "a-gry-02"} & {i for _, i in items}
    # One switch of two takes nothing.
    assert ("device", "h-wsw-01") not in items


def test_the_api_answers_across_the_layers(tmp_path: Path) -> None:
    sample = Path(__file__).parents[2] / "data" / "sample" / "layers.yaml"
    path = tmp_path / "layers.yaml"
    shutil.copy(sample, path)
    client = TestClient(create_app(path, warm=False))
    answer = client.post(
        "/api/impact",
        json={"failures": [{"kind": "provider", "id": "Mesa Carrier"}]},
    ).json()
    corp = next(n for n in answer["networks"] if n["network"] == "corp")
    assert corp["sites_lost"] == ["BNA", "FTW", "MEM"]
    # 28 over Mesa's MPLS, and the 4 MACsec connections over its E-LAN.
    assert len(corp["tunnels_lost"]) == 32
    assert sum(t.startswith("MACSEC-") for t in corp["tunnels_lost"]) == 4
    risks = client.get("/api/risks").json()["networks"]
    grey = next(n for n in risks if n["network"] == "grey")
    first = grey["risks"][0]
    assert first["items"] == [{"kind": "provider", "id": "Northwind Fiber"}]
    assert first["sites"] == ["ATL", "CLT", "RDU"]
    hou = next(r for r in grey["risks"] if r["sites"] == ["HOU"])
    assert {"kind": "device", "id": "hou-blu-01"} in hou["items"]
    # With live state: what fixing each outage and link down would bring
    # back to each named network, and the risks as things stand.
    at = client.get("/api/state").json()["generated_at"]
    problems = client.get("/api/problems", params={"at": at}).json()["problems"]
    assert all(p["networks"] == [] for p in problems if p["impact"] is None)
    assert all(n["network"] is not None for p in problems for n in p["networks"])
    now = client.get("/api/risks", params={"at": at}).json()["networks"]
    assert [n["network"] for n in now] == [n["network"] for n in risks]
