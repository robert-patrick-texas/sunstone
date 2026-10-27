from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sunstone.api import create_app
from sunstone.live import NetworkState
from sunstone.mockgen import PRESETS, generate, to_yaml
from sunstone.model import Topology
from sunstone.simulate import (
    FAULT_WINDOW_S,
    MAX_RUN,
    RETENTION,
    STALE_AGE,
    SimulatedState,
)

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


def test_some_circuits_go_down_while_both_routers_stay_up(
    topology: Topology, snapshot: NetworkState
) -> None:
    up = {d.device for d in snapshot.devices if d.status == "up"}
    readings = {(i.device, i.interface): i.oper for i in snapshot.interfaces}
    cut = [
        link
        for link in topology.links
        if link.kind == "wan"
        and {link.a.device, link.b.device} <= up
        and readings.get((link.a.device, link.a.interface)) == "down"
        and readings.get((link.b.device, link.b.interface)) == "down"
    ]
    assert cut


def test_a_branch_that_loses_every_circuit_is_cut_off(topology: Topology) -> None:
    state = SimulatedState(topology)
    branches = {s.code for s in topology.sites} - {"DAL", "IAD"}
    for window in range(48):
        snapshot = state.snapshot(NOW + timedelta(minutes=5 * window))
        status = {d.device: d.status for d in snapshot.devices}
        isolated = [
            site
            for site in branches
            if all(
                status.get(d.name, "down") == "down"
                for d in topology.devices
                if d.site == site
            )
        ]
        if isolated:
            break
    else:
        pytest.fail("no branch was cut off in four hours")
    site = isolated[0]
    names = {d.name for d in topology.devices if d.site == site}
    assert not any(i.device in names for i in snapshot.interfaces)
    readings = {(i.device, i.interface): i.oper for i in snapshot.interfaces}
    circuits = [
        link
        for link in topology.links
        if link.kind == "wan" and {link.a.device, link.b.device} & names
    ]
    assert circuits
    for link in circuits:
        hub = link.b if link.a.device in names else link.a
        assert readings[(hub.device, hub.interface)] == "down"


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
    longest = STALE_AGE + timedelta(seconds=MAX_RUN * FAULT_WINDOW_S)
    for d in snapshot.devices:
        if d.stale:
            # The last reading came in when the incident began, or earlier.
            assert NOW - longest <= d.observed_at <= NOW - STALE_AGE
        else:
            assert d.observed_at == NOW
    for i in snapshot.interfaces:
        assert i.stale == (i.device in stale)


def test_faults_last_more_than_one_step_and_change_a_few_at_a_time(
    topology: Topology,
) -> None:
    state = SimulatedState(topology)
    down = []
    for step in range(12):
        snapshot = state.snapshot(NOW + timedelta(minutes=5 * step))
        down.append({d.device for d in snapshot.devices if d.status == "down"})
    # Over an hour, most steps keep some of the devices that were already down.
    kept = [bool(a & b) for a, b in zip(down, down[1:], strict=False)]
    assert sum(kept) >= len(kept) // 2


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


def test_round_trip_time_grows_with_distance(
    topology: Topology, snapshot: NetworkState
) -> None:
    assert [(p.name, p.site) for p in snapshot.positions] == [
        ("west", "DAL"),
        ("east", "IAD"),
    ]
    site = {d.name: d.site for d in topology.devices}
    rtt = {
        d.device: {r.position: r.rtt_ms or 0.0 for r in d.reachability}
        for d in snapshot.devices
        if d.status == "up" and not d.stale
    }
    # Any device that is up at each hub will do.
    dal = next(r for name, r in rtt.items() if site[name] == "DAL")
    iad = next(r for name, r in rtt.items() if site[name] == "IAD")
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


def test_events_say_what_changed_between_snapshots(topology: Topology) -> None:
    state = SimulatedState(topology)
    events = state.events(NOW - timedelta(hours=3), NOW)
    assert events == sorted(events, key=lambda e: e.at)
    kinds = {e.kind for e in events}
    assert {"down", "up", "nodata", "reporting", "link-down", "link-up"} <= kinds
    step = timedelta(seconds=FAULT_WINDOW_S)
    for event in events:
        if event.kind not in ("down", "up"):
            continue
        before, after = (
            {d.device: d.status for d in state.snapshot(t).devices}
            for t in (event.at - step, event.at)
        )
        assert (before[event.device or ""], after[event.device or ""]) == (
            ("up", "down") if event.kind == "down" else ("down", "up")
        )


def test_events_include_load_crossing_the_high_marks(topology: Topology) -> None:
    events = SimulatedState(topology).events(NOW - RETENTION, NOW)
    loads = [e for e in events if e.kind in ("busy", "congested", "load-normal")]
    assert loads
    for e in loads:
        assert e.link and e.pct is not None
        assert (e.pct >= 95) == (e.kind == "congested")


def test_history_lines_up_with_snapshots(topology: Topology) -> None:
    state = SimulatedState(topology)
    events = state.events(NOW - timedelta(hours=6), NOW)
    device = next(e.device for e in events if e.kind == "down" and e.device)
    history = state.history(device, NOW - timedelta(hours=6), NOW)
    assert history is not None
    assert len(history.status) == 6 * 12 + 1
    assert set(history.rtt_ms) == {"west", "east"}
    links = [
        link for link in topology.links if device in (link.a.device, link.b.device)
    ]
    assert len(history.interfaces) == len(links)
    step = timedelta(seconds=history.step_s)
    for i, status in enumerate(history.status):
        snap = state.snapshot(history.start + i * step)
        seen = next(d for d in snap.devices if d.device == device)
        expected = "down" if seen.status == "down" else "nodata" if seen.stale else "up"
        assert status == expected
        if status != "up":
            assert all(v is None for v in history.rtt_ms["west"][i : i + 1])
            assert all(f.in_pct[i] is None for f in history.interfaces)
    assert "down" in history.status


def test_history_is_none_for_an_unmonitored_device(topology: Topology) -> None:
    state = SimulatedState(topology)
    unwatched = next(d.name for d in topology.devices if d.name not in state.watched)
    assert state.history(unwatched, NOW - timedelta(hours=1), NOW) is None


def test_api_replays_any_moment_of_the_last_day(
    tmp_path: Path, topology: Topology
) -> None:
    path = tmp_path / "small.yaml"
    path.write_text(to_yaml(topology, "test"), encoding="utf-8")
    client = TestClient(create_app(path))
    at = (datetime.now(UTC) - timedelta(hours=3)).isoformat()
    response = client.get("/api/state", params={"at": at})
    assert response.status_code == 200
    assert response.json()["generated_at"].startswith(at[:19])
    for bad in ("2020-01-01T00:00:00Z", "2099-01-01T00:00:00Z", "2026-10-27T15:00:00"):
        assert client.get("/api/state", params={"at": bad}).status_code == 422

    log = client.get("/api/events").json()
    assert log["events"] and log["since"] < log["until"]
    device = next(e["device"] for e in log["events"] if e["device"])
    history = client.get(f"/api/history/{device}")
    assert history.status_code == 200
    assert history.json()["device"] == device
    state = SimulatedState(topology)
    unwatched = next(d.name for d in topology.devices if d.name not in state.watched)
    assert client.get(f"/api/history/{unwatched}").status_code == 404
