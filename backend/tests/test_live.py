from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sunstone.api import create_app
from sunstone.live import NetworkState
from sunstone.mockgen import PRESETS, generate, to_yaml
from sunstone.model import Topology
from sunstone.simulate import STALE_AGE, SimulatedState

NOW = datetime(2026, 10, 27, 15, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def topology() -> Topology:
    return generate(PRESETS["small"], seed=1)


@pytest.fixture(scope="module")
def snapshot(topology: Topology) -> NetworkState:
    return SimulatedState(topology).snapshot(NOW)


def test_the_same_moment_gives_the_same_state(topology: Topology) -> None:
    assert SimulatedState(topology).snapshot(NOW) == SimulatedState(topology).snapshot(
        NOW
    )


def test_state_changes_over_time(topology: Topology, snapshot: NetworkState) -> None:
    later = SimulatedState(topology).snapshot(NOW + timedelta(hours=1))
    assert [i.out_pct for i in later.interfaces] != [
        i.out_pct for i in snapshot.interfaces
    ]


def test_only_some_devices_are_monitored(
    topology: Topology, snapshot: NetworkState
) -> None:
    roles = {d.name: d.role for d in topology.devices}
    monitored = {d.device for d in snapshot.devices}
    assert {n for n, r in roles.items() if r != "access"} <= monitored
    assert any(r == "access" and n not in monitored for n, r in roles.items())
    assert {i.device for i in snapshot.interfaces} <= monitored


def test_a_down_device_reports_nothing_and_its_neighbors_see_the_link_down(
    topology: Topology, snapshot: NetworkState
) -> None:
    down = {d.device for d in snapshot.devices if d.status == "down"}
    assert down
    for device in snapshot.devices:
        if device.device in down:
            assert {(r.rtt_ms, r.loss_pct) for r in device.reachability} == {
                (None, 100)
            }
    assert not any(i.device in down for i in snapshot.interfaces)
    readings = {(i.device, i.interface): i for i in snapshot.interfaces}
    for link in topology.links:
        for near, far in ((link.a, link.b), (link.b, link.a)):
            seen = readings.get((near.device, near.interface))
            if far.device in down and seen:
                assert (seen.oper, seen.in_pct, seen.out_pct) == ("down", 0.0, 0.0)


def test_packet_loss_is_a_rare_event(snapshot: NetworkState) -> None:
    lossy = [
        d.device
        for d in snapshot.devices
        if d.status == "up" and any((r.loss_pct or 0) > 0 for r in d.reachability)
    ]
    assert 1 <= len(lossy) <= max(1, len(snapshot.devices) // 200)


def test_stale_readings_are_old_and_marked(snapshot: NetworkState) -> None:
    stale = {d.device for d in snapshot.devices if d.stale}
    assert stale
    for d in snapshot.devices:
        assert d.observed_at == (NOW - STALE_AGE if d.stale else NOW)
    for i in snapshot.interfaces:
        assert i.stale == (i.device in stale)


def test_both_ends_of_a_link_see_the_same_traffic(
    topology: Topology, snapshot: NetworkState
) -> None:
    readings = {(i.device, i.interface): i for i in snapshot.interfaces}
    compared = 0
    for link in topology.links:
        a = readings.get((link.a.device, link.a.interface))
        b = readings.get((link.b.device, link.b.interface))
        if a and b and not a.stale and not b.stale and a.oper == "up":
            assert a.out_pct is not None and b.in_pct is not None
            assert abs(a.out_pct - b.in_pct) <= 1.0
            compared += 1
    assert compared > 10


def test_load_is_a_percentage_and_some_wan_circuits_run_hot(
    snapshot: NetworkState,
) -> None:
    loads = [p for i in snapshot.interfaces for p in (i.in_pct, i.out_pct)]
    assert all(p is not None and 0 <= p <= 100 for p in loads)
    assert max(p for p in loads if p is not None) >= 90


def test_round_trip_time_grows_with_distance(snapshot: NetworkState) -> None:
    assert [(p.name, p.site) for p in snapshot.positions] == [
        ("west", "DAL"),
        ("east", "IAD"),
    ]
    rtt = {
        d.device: {r.position: r.rtt_ms for r in d.reachability}
        for d in snapshot.devices
        if d.status == "up"
    }
    dal, iad = rtt["dal-core-01"], rtt["iad-core-01"]
    assert dal["west"] is not None and dal["east"] is not None
    assert iad["west"] is not None and iad["east"] is not None
    assert dal["west"] < dal["east"]
    assert iad["east"] < iad["west"]


def test_api_serves_compressed_state(tmp_path: Path, topology: Topology) -> None:
    path = tmp_path / "small.yaml"
    path.write_text(to_yaml(topology, "test"), encoding="utf-8")
    response = TestClient(create_app(path)).get("/api/state")
    assert response.status_code == 200
    assert response.headers["content-encoding"] == "gzip"
    body = response.json()
    assert body["source"] == "simulated"
    assert [p["name"] for p in body["positions"]] == ["west", "east"]
    assert body["devices"] and body["interfaces"]
