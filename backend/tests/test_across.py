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
    return {n.network: n for n in answer.networks}


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
    assert len(corp["tunnels_lost"]) == 28
    risks = client.get("/api/risks").json()["networks"]
    grey = next(n for n in risks if n["network"] == "grey")
    first = grey["risks"][0]
    assert first["items"] == [{"kind": "provider", "id": "Northwind Fiber"}]
    assert first["sites"] == ["ATL", "CLT", "RDU"]
    hou = next(r for r in grey["risks"] if r["sites"] == ["HOU"])
    assert {"kind": "device", "id": "hou-blu-01"} in hou["items"]
