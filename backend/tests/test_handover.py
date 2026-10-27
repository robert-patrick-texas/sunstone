from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sunstone.api import Files, create_app
from sunstone.handover import outages
from sunstone.live import StateEvent
from sunstone.mockgen import (
    PRESETS,
    directory_yaml,
    generate,
    generate_directory,
    to_yaml,
)
from sunstone.model import Topology

T0 = datetime(2026, 10, 27, 8, 0, tzinfo=UTC)
STEP = timedelta(minutes=5)


@pytest.fixture(scope="module")
def topology() -> Topology:
    return generate(PRESETS["small"], seed=1)


def at(steps: int) -> datetime:
    return T0 + STEP * steps


def event(steps: int, kind: str, name: str, planned: bool = False) -> StateEvent:
    field = "link" if kind.startswith("link") else "device"
    return StateEvent.model_validate(
        {"at": at(steps), "kind": kind, field: name, "planned": planned}
    )


def test_devices_down_together_at_a_site_are_one_outage(topology: Topology) -> None:
    site = {d.name: d.site for d in topology.devices}
    hou = [d.name for d in topology.devices if d.site == "HOU"][:2]
    circuit = next(
        ln
        for ln in topology.links
        if ln.kind == "wan" and "HOU" in {site[ln.a.device], site[ln.b.device]}
    )
    other = next(
        ln for ln in topology.links if ln.kind == "wan" and ln.id != circuit.id
    )
    events = [
        # Down since before history, back early in the span.
        event(10, "up", "dal-core-02"),
        # Over before the span begins: left out.
        event(2, "down", "iad-core-01"),
        event(3, "up", "iad-core-01"),
        event(20, "down", hou[0]),
        event(20, "down", hou[1]),
        event(20, "link-down", circuit.id),
        event(26, "up", hou[0]),
        event(28, "link-up", circuit.id),
        event(30, "up", hou[1]),
        event(40, "link-down", other.id, planned=True),
    ]
    found = outages(events, topology, at(5))
    assert [o.title for o in found] == [
        f"Circuit {other.circuit.circuit_id} down" if other.circuit else "",
        "HOU: 2 devices and 1 link down",
        "dal-core-02 down",
    ]
    lone, branch, early = found
    assert (lone.end, lone.planned, lone.target.kind) == (None, True, "links")
    assert (branch.start, branch.end, branch.planned) == (at(20), at(30), False)
    assert branch.target.model_dump() == {"kind": "site", "id": "HOU"}
    assert (branch.devices, branch.links) == (sorted(hou), [circuit.id])
    assert (early.start, early.end) == (None, at(10))


def handover_client(topology: Topology, tmp_path: Path) -> TestClient:
    path = tmp_path / "small.yaml"
    path.write_text(to_yaml(topology, "test"), encoding="utf-8")
    directory = generate_directory(topology, seed=1)
    (tmp_path / "small.oncall.yaml").write_text(
        directory_yaml(directory, "test"), encoding="utf-8"
    )
    files = Files(
        operations=tmp_path / "ops.json",
        layouts=tmp_path / "l.json",
        changes=tmp_path / "changes.json",
    )
    return TestClient(create_app(path, files=files, warm=False))


def test_the_handover_says_what_is_open_and_what_was_done(
    topology: Topology, tmp_path: Path
) -> None:
    client = handover_client(topology, tmp_path)
    [problem, *_] = client.get("/api/problems").json()["problems"]
    ack = {"problem": problem["id"], "by": "Pat", "note": "Carrier ticket 4411"}
    assert client.post("/api/acks", json=ack).status_code == 201
    assert (
        client.post(
            "/api/pages", json={"problem": problem["id"], "by": "Pat"}
        ).status_code
        == 201
    )
    now = datetime.now(UTC)
    window = {
        "title": "Replace line card",
        "start": (now + timedelta(hours=2)).isoformat(),
        "end": (now + timedelta(hours=3)).isoformat(),
        "targets": [{"kind": "device", "id": "dal-dist-01"}],
        "by": "Pat",
    }
    assert client.post("/api/maintenance", json=window).status_code == 201

    handover = client.get("/api/handover", params={"hours": 8}).json()
    since, until = (datetime.fromisoformat(handover[k]) for k in ("since", "until"))
    assert until - since == timedelta(hours=8)
    shown = next(p for p in handover["problems"] if p["id"] == problem["id"])
    assert shown["ack"]["note"] == "Carrier ticket 4411"
    assert shown["paging"] is not None
    assert [a["by"] for a in handover["acks"]] == ["Pat"]
    assert [pg["problem"] for pg in handover["pages"]] == [problem["id"]]
    assert [made["title"] for made in handover["pages"] + handover["acks"]] == [
        problem["title"]
    ] * 2
    assert [w["title"] for w in handover["windows"]] == ["Replace line card"]
    assert handover["outages"], "the simulator has something down in any 8 hours"
    assert all(
        o["end"] is None or datetime.fromisoformat(o["end"]) >= since
        for o in handover["outages"]
    )
    assert {t["id"] for t in handover["oncall"]["teams"]} >= {"wan", "noc"}
    assert handover["changes"] == []

    assert client.get("/api/handover", params={"hours": 30}).status_code == 422
