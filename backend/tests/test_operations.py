from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from sunstone.api import Files, create_app
from sunstone.impact import Failures, Network
from sunstone.mockgen import PRESETS, generate, to_yaml
from sunstone.model import Topology
from sunstone.operations import OperationsStore, WindowIn
from sunstone.problems import AckIn
from sunstone.simulate import SimulatedState

NOW = datetime(2026, 10, 27, 15, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def topology() -> Topology:
    return generate(PRESETS["small"], seed=1)


@pytest.fixture
def client(tmp_path: Path, topology: Topology) -> TestClient:
    path = tmp_path / "small.yaml"
    path.write_text(to_yaml(topology, "test"), encoding="utf-8")
    files = Files(operations=tmp_path / "ops.json", layouts=tmp_path / "l.json")
    return TestClient(create_app(path, files=files, warm=False))


def window(around: datetime | None = None, **extra: object) -> dict:
    at = around or datetime.now(UTC)
    return {
        "title": "Replace line card",
        # Opened well before the moment, so the 5-minute step that holds it is inside.
        "start": (at - timedelta(minutes=10)).isoformat(),
        "end": (at + timedelta(minutes=30)).isoformat(),
        "targets": [{"kind": "device", "id": "dal-dist-01"}],
        "by": "Pat",
        **extra,
    }


def quiet_moment(topology: Topology) -> datetime:
    """A recent moment when dal-dist-01 and every device next to it are up.

    Work on dal-dist-01 then makes a problem of its own, whatever the
    simulator happens to have down now: a neighbor down at the same time
    would join it in one outage, which the work only partly accounts for.

    Args:
        topology: The test topology.

    Returns:
        The moment, between 15 minutes and 12 hours ago.

    Raises:
        AssertionError: If there is no such moment.
    """
    near = {"dal-dist-01"} | {
        end.device
        for link in topology.links
        if "dal-dist-01" in (link.a.device, link.b.device)
        for end in (link.a, link.b)
    }
    state = SimulatedState(topology)
    now = datetime.now(UTC)
    for minutes in range(15, 12 * 60, 5):
        at = now - timedelta(minutes=minutes)
        devices = state.snapshot(at).devices
        if all(d.status == "up" for d in devices if d.device in near):
            return at
    raise AssertionError("dal-dist-01 or a neighbor was down all the last 12 hours")


class Plans:
    """Plans for the simulator, changeable in a test."""

    def __init__(self) -> None:
        self.version = 0
        self.devices: frozenset[str] = frozenset()

    def planned_at(self, at: datetime) -> Failures:
        return Failures(devices=self.devices)


def test_the_simulator_takes_planned_work_down_and_notices_changed_plans(
    topology: Topology,
) -> None:
    plans = Plans()
    state = SimulatedState(topology, plans=plans)
    status = lambda: {d.device: d.status for d in state.snapshot(NOW).devices}  # noqa: E731
    assert status()["iad-dist-02"] == "up"
    plans.devices, plans.version = frozenset(["iad-dist-02"]), 1
    assert status()["iad-dist-02"] == "down"


def test_a_window_must_end_after_it_starts_and_not_run_for_weeks() -> None:
    base = window()
    with pytest.raises(ValidationError, match="end after it starts"):
        WindowIn.model_validate({**base, "end": base["start"]})
    with pytest.raises(ValidationError, match="at most 7 days"):
        far = datetime.fromisoformat(base["start"]) + timedelta(days=8)
        WindowIn.model_validate({**base, "end": far.isoformat()})


def test_windows_are_planned_changed_and_deleted(client: TestClient) -> None:
    saved = client.post("/api/maintenance", json=window())
    assert saved.status_code == 201
    window_id = saved.json()["id"]
    changed = client.put(f"/api/maintenance/{window_id}", json=window(title="Swap PSU"))
    assert changed.json()["title"] == "Swap PSU"
    assert [w["title"] for w in client.get("/api/maintenance").json()] == ["Swap PSU"]
    assert client.delete(f"/api/maintenance/{window_id}").status_code == 204
    assert client.delete(f"/api/maintenance/{window_id}").status_code == 404
    unknown = client.post(
        "/api/maintenance", json=window(targets=[{"kind": "site", "id": "XXX"}])
    )
    assert unknown.status_code == 422


def test_a_window_naming_something_not_in_the_topology_is_refused(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/maintenance", json=window(targets=[{"kind": "device", "id": "nope-01"}])
    )
    assert response.status_code == 422
    assert "nope-01" in response.text


def test_planned_work_shows_as_planned_problems_and_events(
    client: TestClient, topology: Topology
) -> None:
    at = quiet_moment(topology)
    window_id = client.post("/api/maintenance", json=window(at)).json()["id"]
    state = client.get("/api/state", params={"at": at.isoformat()}).json()
    status = {d["device"]: d["status"] for d in state["devices"]}
    assert status["dal-dist-01"] == "down"
    problems = client.get("/api/problems", params={"at": state["generated_at"]}).json()
    mine = next(
        p
        for p in problems["problems"]
        if p["target"] == {"kind": "device", "id": "dal-dist-01"}
    )
    assert mine["planned"] == [window_id]
    others = [p for p in problems["problems"] if p is not mine]
    assert all(p["planned"] == [] for p in others if p["kind"] != "outage")
    events = client.get("/api/events").json()["events"]
    went_down = [
        e for e in events if e["device"] == "dal-dist-01" and e["kind"] == "down"
    ]
    assert went_down and went_down[-1]["planned"]


def test_problems_are_acknowledged_until_withdrawn(client: TestClient) -> None:
    state = client.get("/api/state").json()
    at = state["generated_at"]
    problem = client.get("/api/problems", params={"at": at}).json()["problems"][0]
    ack = {"problem": problem["id"], "note": "Carrier ticket 4411", "by": "Pat"}
    assert client.post("/api/acks", json=ack).status_code == 201
    shown = client.get("/api/problems").json()["problems"]
    acked = next(p for p in shown if p["id"] == problem["id"])
    assert acked["ack"]["note"] == "Carrier ticket 4411"
    assert acked["ack"]["by"] == "Pat"
    assert (
        client.delete("/api/acks", params={"problem": problem["id"]}).status_code == 204
    )
    assert (
        client.delete("/api/acks", params={"problem": problem["id"]}).status_code == 404
    )
    missing = client.post("/api/acks", json={**ack, "problem": "loss:nowhere"})
    assert missing.status_code == 404


def test_an_acknowledgement_ends_when_its_problem_clears(
    tmp_path: Path, topology: Topology
) -> None:
    store = OperationsStore(tmp_path / "ops.json", Network(topology))
    store.acknowledge(AckIn(problem="loss:a", note="", by="Pat"), NOW)
    store.acknowledge(AckIn(problem="loss:b", note="", by="Pat"), NOW)
    later = NOW + timedelta(minutes=5)
    store.clear_acks({"loss:b"}, later)
    acks = {a.problem: a for a in store.acks()}
    assert acks["loss:a"].cleared_at == later
    assert not acks["loss:a"].active(later)
    assert acks["loss:a"].active(NOW + timedelta(minutes=1))
    assert acks["loss:b"].active(later)
    # Kept a day for replay, then forgotten; and it all survives a restart.
    reopened = OperationsStore(tmp_path / "ops.json", Network(topology))
    assert {a.problem for a in reopened.acks()} == {"loss:a", "loss:b"}
    reopened.clear_acks({"loss:b"}, later + timedelta(days=2))
    assert {a.problem for a in reopened.acks()} == {"loss:b"}


def test_planned_work_counts_sites_as_all_their_devices(
    tmp_path: Path, topology: Topology
) -> None:
    store = OperationsStore(tmp_path / "ops.json", Network(topology))
    store.save_window(
        WindowIn.model_validate(
            {
                **window(),
                "targets": [{"kind": "site", "id": "HOU"}],
                "start": NOW.isoformat(),
                "end": (NOW + timedelta(hours=1)).isoformat(),
            }
        )
    )
    work = store.planned_at(NOW + timedelta(minutes=30))
    assert work.devices == {d.name for d in topology.devices if d.site == "HOU"}
    assert store.planned_at(NOW + timedelta(hours=1)).devices == frozenset()
