"""Overrides: Sunstone's own exceptions to what the topology says."""

import json
import shutil
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_discovery import AllUp, drifted
from test_discovery import topology as small  # noqa: F401  (a fixture)
from test_status import NOW, groups, topology, view, whole

from sunstone.api import Files, create_app
from sunstone.discovery import (
    NeighborRules,
    SimulatedDiscovery,
    Visibility,
    compare,
    port_key,
)
from sunstone.handover import outages
from sunstone.impact import Network
from sunstone.live import StateEvent
from sunstone.model import Topology
from sunstone.overrides import (
    Override,
    OverrideIn,
    Stamp,
    Target,
    apply,
    lines,
    new_override,
)
from sunstone.problems import find_problems

__all__ = ["topology"]  # the fixture, shared with the status tests

SAMPLE = Path(__file__).parents[2] / "data" / "sample" / "layers.yaml"


def made(target: Target, kind: str, **more: object) -> Override:
    """An override made at NOW."""
    return new_override(
        OverrideIn.model_validate(
            {"target": target, "kind": kind, "by": "Pat", **more}
        ),
        NOW,
    )


def device(name: str) -> Target:
    return Target(kind="device", id=name)


# What each kind is made on, and what it needs.


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"target": {"kind": "network", "id": "blue"}, "kind": "hide-map"}, "network"),
        (
            {"target": {"kind": "link", "id": "x"}, "kind": "rename", "value": "y"},
            "link",
        ),
        (
            {"target": {"kind": "device", "id": "x"}, "kind": "label", "value": "y"},
            "key",
        ),
        (
            {"target": {"kind": "device", "id": "x"}, "kind": "hide-map", "value": "y"},
            "value",
        ),
        (
            {
                "target": {"kind": "device", "id": "x"},
                "kind": "lock",
                "key": "name",
                "value": "y",
            },
            "cannot be locked",
        ),
        (
            {"target": {"kind": "port", "id": "x"}, "kind": "one-device", "value": "y"},
            "interface",
        ),
        (
            {
                "target": {"kind": "device", "id": "x", "interface": "p1"},
                "kind": "tag",
                "value": "y",
            },
            "interface",
        ),
    ],
)
def test_each_kind_is_made_where_it_makes_sense(body: dict, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        OverrideIn.model_validate({**body, "by": "Pat"})


# Applied to the topology.


def test_a_lock_keeps_a_field_and_says_what_the_topology_says(
    topology: Topology,
) -> None:
    lock = made(device("b-acc-02"), "lock", key="role", value="distribution")
    same = made(device("b-acc-01"), "lock", key="role", value="access")
    over = apply(topology, [lock, same], NOW)
    roles = {d.name: d.role for d in over.topology.devices}
    assert roles["b-acc-02"] == "distribution"
    [differs, kept] = over.now
    assert (differs.state, differs.topology_value) == ("active", "access")
    assert (kept.state, kept.topology_value) == ("active", None)


def test_a_site_renamed_is_renamed_in_the_topology(topology: Topology) -> None:
    rename = made(Target(kind="site", id="B"), "rename", value="Bravo Hub")
    over = apply(topology, [rename], NOW)
    assert next(s.name for s in over.topology.sites if s.code == "B") == "Bravo Hub"
    assert over.now[0].topology_value == "B"


def test_hiding_a_site_from_status_ignores_its_devices(topology: Topology) -> None:
    hide = made(Target(kind="site", id="B"), "hide-status")
    over = apply(topology, [hide], NOW)
    rated = {d.name: d.priority for d in over.topology.devices}
    assert {n for n, p in rated.items() if p == "ignored"} == {
        "b-wan-01",
        "b-acc-01",
        "b-acc-02",
    }


def test_one_whose_target_is_gone_is_kept_and_not_applied(topology: Topology) -> None:
    gone = made(device("z-acc-09"), "lock", key="role", value="core")
    bad = made(device("b-acc-01"), "lock", key="site", value="Z")
    good = made(device("b-acc-02"), "lock", key="role", value="core")
    over = apply(topology, [gone, bad, good], NOW)
    # The one the topology takes applies all the same.
    assert {d.name: d.role for d in over.topology.devices}["b-acc-02"] == "core"
    assert [o.state for o in over.now] == ["not-applied", "not-applied", "active"]
    assert over.now[0].reason == "No device z-acc-09 now"
    assert (over.now[1].reason or "").startswith(
        "device 'b-acc-01' is at unknown site 'Z'"
    )


def test_one_expired_or_withdrawn_stops_applying(topology: Topology) -> None:
    expired = made(device("b-acc-02"), "hide-status").model_copy(
        update={"expires": NOW - timedelta(minutes=1)}
    )
    withdrawn = made(device("b-acc-01"), "hide-status").model_copy(
        update={"withdrawn": Stamp(by="Sam", at=NOW)}
    )
    over = apply(topology, [expired, withdrawn], NOW)
    assert over.topology == topology
    assert [o.state for o in over.now] == ["expired"]


def test_device_names_and_ports_go_to_discovery(topology: Topology) -> None:
    port = Target(kind="port", id="b-wan-01", interface="GigabitEthernet0/1")
    over = apply(
        topology,
        [
            made(device("b-acc-01"), "alias", value="old-b-1"),
            made(device("b-acc-02"), "rename", value="B ACC 2"),
            made(port, "one-device", value="b-acc-01"),
            made(port, "ignore-neighbor", value="phone-1"),
        ],
        NOW,
    )
    assert over.rules.names == {"old-b-1": "b-acc-01", "B ACC 2": "b-acc-02"}
    assert over.rules.one_device == {("b-wan-01", "gi0/1"): "b-acc-01"}
    assert over.rules.ignored == {("b-wan-01", "gi0/1"): frozenset({"phone-1"})}


# Status and problems.


def test_a_device_hidden_from_status_raises_no_problem(topology: Topology) -> None:
    hidden = apply(topology, [made(device("b-acc-02"), "hide-status")], NOW).topology
    assert groups(whole(topology, down={"b-acc-02"})) == {"B": "degraded"}
    assert whole(hidden, down={"b-acc-02"}).groups == []
    assert find_problems(Network(hidden), view(hidden, down={"b-acc-02"})) == []


def test_what_a_hidden_device_cuts_off_still_counts(topology: Topology) -> None:
    hidden = apply(topology, [made(device("b-wan-01"), "hide-status")], NOW).topology
    w = whole(hidden, down={"b-wan-01"})
    # Its access switches are cut off with it: they count.
    assert groups(w)["B"] == "offline"
    [problem] = find_problems(Network(hidden), view(hidden, down={"b-wan-01"}))
    assert problem.title == "B cut off"


# Discovery.


def test_an_alias_matches_a_switchs_old_hostname(small: Topology) -> None:  # noqa: F811
    cabling = drifted(small)
    [(switch, old)] = cabling.renamed.items()
    state = AllUp(small)
    found = SimulatedDiscovery(small, cabling, state).discover(NOW)
    seen = Visibility.of(state.snapshot(NOW))
    before = compare(small, found, seen)
    about = [f for f in before.findings if old in (f.detail or "")]
    assert about and all(f.kind == "wrong-neighbor" for f in about)
    after = compare(small, found, seen, NeighborRules(names={old: switch}))
    assert not [f for f in after.findings if old in (f.detail or "")]
    assert len(after.findings) == len(before.findings) - len(about)


def test_a_port_with_a_device_inline_is_one_device_or_ignores_it(
    small: Topology,  # noqa: F811
) -> None:
    cabling = drifted(small)
    [(ports, (inline, _))] = cabling.inline.items()
    state = AllUp(small)
    found = SimulatedDiscovery(small, cabling, state).discover(NOW)
    seen = Visibility.of(state.snapshot(NOW))
    [here, there] = sorted(ports)

    def about(rules: NeighborRules) -> list[str]:
        result = compare(small, found, seen, rules)
        return [f.id for f in result.findings if inline in (f.detail or "")]

    assert len(about(NeighborRules())) == 1
    keys = {p: (p[0], port_key(p[1])) for p in ports}
    # One end alone still sees it at the other.
    assert len(about(NeighborRules(one_device={keys[here]: there[0]}))) == 1
    both = {keys[here]: there[0], keys[there]: here[0]}
    assert about(NeighborRules(one_device=both)) == []
    ignored = {keys[p]: frozenset({inline}) for p in ports}
    assert about(NeighborRules(ignored=ignored)) == []


# The handover.


def test_the_handover_lists_overrides_made_withdrawn_and_expired() -> None:
    t = device("b-acc-01")
    early = made(t, "tag", value="lab").model_copy(
        update={"at": NOW - timedelta(hours=20)}
    )
    withdrawn = early.model_copy(
        update={"withdrawn": Stamp(by="Sam", at=NOW - timedelta(hours=2))}
    )
    expiring = made(t, "hide-map").model_copy(
        update={"expires": NOW - timedelta(hours=1)}
    )
    found = lines([withdrawn, expiring], NOW - timedelta(hours=12), NOW)
    assert [(line.event, line.override.kind) for line in found] == [
        ("made", "hide-map"),
        ("expired", "hide-map"),
        ("withdrawn", "tag"),
    ]


# The API.


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """The API on a copy of the layered sample."""
    shutil.copy(SAMPLE, tmp_path / "layers.yaml")
    files = Files(
        operations=tmp_path / "ops.json",
        changes=tmp_path / "changes.json",
        overrides=tmp_path / "overrides.json",
        handovers=tmp_path / "handovers.json",
        incidents=tmp_path / "incidents.json",
    )
    return TestClient(create_app(tmp_path / "layers.yaml", files=files, warm=False))


def post(client: TestClient, target: dict, kind: str, **more: object) -> dict:
    response = client.post(
        "/api/overrides", json={"target": target, "kind": kind, "by": "Pat", **more}
    )
    assert response.status_code == 201, response.text
    return response.json()


def titles(client: TestClient) -> list[str]:
    return [f["title"] for f in client.get("/api/discovery").json()["findings"]]


def test_an_alias_clears_the_renamed_switchs_findings(client: TestClient) -> None:
    before = titles(client)
    assert "Another device on bhm-wan-01 Gi0/0/1" in before
    alias = post(
        client, {"kind": "device", "id": "bhm-acc-01"}, "alias", value="bhm-sw-70"
    )
    after = titles(client)
    assert [t for t in before if t not in after] == [
        "Another device on bhm-wan-01 Gi0/0/1",
        "Another device on bhm-wan-02 Gi0/0/1",
    ]
    [listed] = client.get("/api/overrides").json()["overrides"]
    assert (listed["id"], listed["state"]) == (alias["id"], "active")
    withdrawn = client.post(
        f"/api/overrides/{alias['id']}/withdraw", json={"by": "Sam"}
    )
    assert withdrawn.status_code == 204
    assert titles(client) == before
    assert client.get("/api/overrides").json()["overrides"] == []


def test_a_second_of_a_kind_replaces_the_first(
    client: TestClient, tmp_path: Path
) -> None:
    target = {"kind": "device", "id": "bhm-acc-01"}
    first = post(client, target, "label", key="rack", value="B12")
    second = post(client, target, "label", key="rack", value="B14")
    post(client, target, "label", key="row", value="3")
    listed = client.get("/api/overrides").json()["overrides"]
    assert [(o["key"], o["value"]) for o in listed] == [("row", "3"), ("rack", "B14")]
    saved = json.loads((tmp_path / "overrides.json").read_text())["overrides"]
    assert [o["id"] for o in saved if o["withdrawn"]] == [first["id"]]
    assert second["id"] in {o["id"] for o in listed}
    again = client.post(
        "/api/overrides",
        json={"target": target, "kind": "tag", "value": "lab", "by": "Pat"},
    )
    assert again.status_code == 201
    repeated = client.post(
        "/api/overrides",
        json={"target": target, "kind": "tag", "value": "LAB", "by": "Pat"},
    )
    assert repeated.status_code == 409


def test_what_the_network_will_not_take_is_refused(client: TestClient) -> None:
    for body, code in [
        (
            {"target": {"kind": "device", "id": "nope"}, "kind": "tag", "value": "x"},
            409,
        ),
        (
            {
                "target": {"kind": "device", "id": "bhm-acc-01"},
                "kind": "lock",
                "key": "site",
                "value": "NOPE",
            },
            409,
        ),
        (
            {
                "target": {"kind": "device", "id": "bhm-acc-01"},
                "kind": "tag",
                "value": "x",
                "expires": "2020-01-01T00:00:00Z",
            },
            422,
        ),
    ]:
        response = client.post("/api/overrides", json={**body, "by": "Pat"})
        assert response.status_code == code, response.text


def test_a_lock_and_hiding_change_the_topology_served(client: TestClient) -> None:
    post(
        client,
        {"kind": "device", "id": "bhm-acc-01"},
        "lock",
        key="role",
        value="distribution",
    )
    post(client, {"kind": "site", "id": "BHM"}, "hide-status")
    post(client, {"kind": "site", "id": "BHM"}, "rename", value="Birmingham Hub")
    served = client.get("/api/topology").json()
    assert next(s["name"] for s in served["sites"] if s["code"] == "BHM") == (
        "Birmingham Hub"
    )
    at_bhm = [d for d in served["devices"] if d["site"] == "BHM"]
    assert {d["priority"] for d in at_bhm} == {"ignored"}
    assert next(d["role"] for d in at_bhm if d["name"] == "bhm-acc-01") == (
        "distribution"
    )
    lock = next(
        o
        for o in client.get("/api/overrides").json()["overrides"]
        if o["kind"] == "lock"
    )
    assert lock["topology_value"] == "access"


def test_one_expires_while_the_server_runs(client: TestClient) -> None:
    soon = datetime.now(UTC) + timedelta(seconds=1)
    post(
        client,
        {"kind": "device", "id": "bhm-acc-01"},
        "lock",
        key="role",
        value="distribution",
        expires=soon.isoformat(),
    )
    role = lambda: next(  # noqa: E731
        d["role"]
        for d in client.get("/api/topology").json()["devices"]
        if d["name"] == "bhm-acc-01"
    )
    assert role() == "distribution"
    time.sleep(max(0.0, (soon - datetime.now(UTC)).total_seconds()) + 0.1)
    assert role() == "access"
    [expired] = client.get("/api/overrides").json()["overrides"]
    assert expired["state"] == "expired"
    renewed = client.post(
        f"/api/overrides/{expired['id']}/renew", json={"by": "Sam", "expires": None}
    )
    assert renewed.status_code == 200
    assert renewed.json()["renewed"]["by"] == "Sam"
    assert role() == "distribution"


def test_overrides_survive_the_topology_file_being_replaced(tmp_path: Path) -> None:
    shutil.copy(SAMPLE, tmp_path / "layers.yaml")
    files = Files(overrides=tmp_path / "overrides.json", changes=tmp_path / "c.json")
    app = TestClient(create_app(tmp_path / "layers.yaml", files=files, warm=False))
    post(app, {"kind": "device", "id": "bhm-acc-01"}, "alias", value="bhm-sw-70")
    text = (tmp_path / "layers.yaml").read_text()
    (tmp_path / "layers.yaml").write_text(text.replace("bhm-acc-01", "bhm-acc-11"))
    again = TestClient(create_app(tmp_path / "layers.yaml", files=files, warm=False))
    [kept] = again.get("/api/overrides").json()["overrides"]
    assert (kept["state"], kept["reason"]) == (
        "not-applied",
        "No device bhm-acc-01 now",
    )


def test_a_fix_leaves_what_an_override_set_on_its_link_out(client: TestClient) -> None:
    finding = next(
        f
        for f in client.get("/api/discovery").json()["findings"]
        if f["kind"] == "wrong-port" and f.get("fix") and f["fix"]["before"]
    )
    link = finding["fix"]["before"]
    link_id = next(
        ln["id"]
        for ln in client.get("/api/topology").json()["links"]
        if ln["a"] == link["a"] and ln["b"] == link["b"]
    )
    post(client, {"kind": "link", "id": link_id}, "lock", key="speed_mbps", value="1")
    finding = next(
        f
        for f in client.get("/api/discovery").json()["findings"]
        if f["id"] == finding["id"]
    )
    assert finding["fix"]["after"]["speed_mbps"] == 1
    accepted = client.post("/api/changes", json={"finding": finding["id"], "by": "Pat"})
    assert accepted.status_code == 201, accepted.text
    moved = finding["fix"]["after"]
    served = next(
        ln
        for ln in client.get("/api/topology").json()["links"]
        if ln["a"] == moved["a"] and ln["b"] == moved["b"]
    )
    assert served["speed_mbps"] == link["speed_mbps"]


def test_the_handover_leaves_devices_hidden_from_status_out(
    topology: Topology,
) -> None:
    hidden = apply(topology, [made(device("b-acc-02"), "hide-status")], NOW).topology
    events = [
        StateEvent(at=NOW, kind="down", device=name)
        for name in ("b-acc-01", "b-acc-02")
    ]
    assert [o.title for o in outages(events, topology, NOW)] == ["B: 2 devices down"]
    assert [o.title for o in outages(events, hidden, NOW)] == ["b-acc-01 down"]
