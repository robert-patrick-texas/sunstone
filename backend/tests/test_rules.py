"""Rules: overrides on everything that matches."""

import shutil
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_overrides import device, made
from test_status import NOW, topology

from sunstone.api import Files, create_app
from sunstone.discovery import like
from sunstone.model import Topology
from sunstone.overrides import (
    Excepted,
    Rule,
    RuleIn,
    Stamp,
    apply,
    new_rule,
    rule_lines,
)

__all__ = ["topology"]  # the fixture, shared with the status tests

SAMPLE = Path(__file__).parents[2] / "data" / "sample" / "layers.yaml"


def rule(name: str, match: dict, kind: str, **more: object) -> Rule:
    """A rule made at NOW."""
    return new_rule(
        RuleIn.model_validate(
            {"name": name, "match": match, "kind": kind, "by": "Pat", **more}
        ),
        NOW,
    )


def ids(targets: list) -> list[str]:
    """The keys of targets, or of what rules apply on."""
    return [getattr(t, "target", t).id for t in targets]


# Patterns.


@pytest.mark.parametrize(
    ("pattern", "value", "matches"),
    [
        ("*-acc-*", "b-acc-01", True),
        ("*-ACC-*", "b-acc-01", True),
        ("*-acc-*", "b-wan-01", False),
        ("SEP*", "SEP0040ABCD", True),
        ("Gi1/0/4?", "Gi1/0/48", True),
        ("Gi1/0/4?", "Gi1/0/480", False),
        ("[x]", "[x]", True),
        ("a.b", "axb", False),
    ],
)
def test_patterns_match_whole_values_ignoring_case(
    pattern: str, value: str, matches: bool
) -> None:
    assert like([pattern], value) is matches


# What a rule is made on, and what it needs.


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"match": {"of": "device", "interface": ["Gi1/0/48"]}}, "interface"),
        ({"match": {"of": "site", "role": ["access"]}}, "cannot test role"),
        ({"match": {"of": "port", "role": ["access"]}}, "interface pattern"),
        ({"kind": "rename", "value": "x"}, "kind"),
        ({"kind": "ignore-neighbor", "value": "*"}, "not made on devices"),
        (
            {
                "match": {"of": "port", "interface": ["*"]},
                "kind": "one-device",
                "value": "x",
            },
            "takes no value",
        ),
        (
            {
                "match": {"of": "port", "interface": ["*"]},
                "kind": "ignore-neighbor",
                "value": None,
            },
            "needs value",
        ),
        ({"kind": "lock", "key": "name", "value": "x"}, "cannot be locked"),
        ({"name": " "}, "name"),
    ],
)
def test_each_kind_of_rule_is_made_where_it_makes_sense(
    body: dict, message: str
) -> None:
    base = {
        "name": "R",
        "match": {"of": "device"},
        "kind": "tag",
        "value": "lab",
        "by": "Pat",
    }
    with pytest.raises(ValidationError, match=message):
        RuleIn.model_validate({**base, **body})


# What a rule matches.


def test_a_rule_matches_by_every_test_given(topology: Topology) -> None:
    access = rule("Access", {"of": "device", "role": ["access"]}, "tag", value="x")
    at_b = rule(
        "B", {"of": "device", "site": ["B"], "name": ["*-wan-*"]}, "tag", value="y"
    )
    over = apply(topology, [], NOW, [access, at_b])
    assert [ids(r.matches) for r in over.ruled] == [
        ["b-acc-01", "b-acc-02"],
        ["b-wan-01"],
    ]


def test_a_region_matches_the_regions_inside_it(topology: Topology) -> None:
    south = rule("South", {"of": "site", "region": ["south"]}, "tag", value="x")
    links = rule("Links", {"of": "link", "region": ["North"]}, "tag", value="y")
    [sites, north] = apply(topology, [], NOW, [south, links]).ruled
    assert ids(sites.matches) == ["A", "B", "C"]
    # Either end in the region: the link from C to D, and D's own.
    assert len(north.matches) == 3


def test_links_match_by_role_at_the_edge_and_priority(topology: Topology) -> None:
    internal = rule("Inside", {"of": "link", "role": ["internal"]}, "tag", value="x")
    tbd = rule("TBD", {"of": "link", "role": ["tbd"]}, "tag", value="y")
    medium = rule("Medium", {"of": "link", "priority": ["medium"]}, "tag", value="z")
    [inside, unknown, rated] = apply(topology, [], NOW, [internal, tbd, medium]).ruled
    assert len(inside.matches) == 7
    # Circuits into the Internet, which no one has given roles yet.
    assert len(unknown.matches) == 3
    assert len(rated.matches) == 10


def test_rules_see_overrides_on_single_objects_but_not_other_rules(
    topology: Topology,
) -> None:
    tagged = made(device("c-wan-01"), "tag", value="lab")
    locked = made(device("b-wan-01"), "lock", key="role", value="access")
    adds = rule("Adds", {"of": "device", "name": ["d-*"]}, "tag", value="lab")
    lab = rule("Lab", {"of": "device", "tag": ["lab"]}, "hide-map")
    access = rule("Access", {"of": "device", "role": ["access"]}, "tag", value="a")
    over = apply(topology, [tagged, locked], NOW, [adds, lab, access])
    # d-wan-01's tag comes from a rule, so the lab rule does not see it.
    assert ids(over.ruled[1].matches) == ["c-wan-01"]
    assert ids(over.ruled[2].matches) == ["b-wan-01", "b-acc-01", "b-acc-02"]


# Which wins.


def test_an_override_on_the_object_wins_then_the_newer_rule(
    topology: Topology,
) -> None:
    own = made(device("b-acc-01"), "lock", key="platform", value="Own")
    older = rule(
        "Old", {"of": "device", "role": ["access"]}, "lock", key="platform", value="Old"
    )
    newer = rule(
        "New",
        {"of": "device", "name": ["b-acc-02"]},
        "lock",
        key="platform",
        value="New",
    )
    over = apply(topology, [own], NOW, [older, newer])
    platforms = {d.name: d.platform for d in over.topology.devices}
    assert (platforms["b-acc-01"], platforms["b-acc-02"]) == ("Own", "New")
    [old, new] = over.ruled
    assert ids(old.matches) == []
    assert ids(old.overridden) == ["b-acc-01", "b-acc-02"]
    assert ids(new.matches) == ["b-acc-02"]
    # What the topology said, where the rule's lock differs.
    assert new.matches[0].topology_value == ""


def test_tags_from_rules_and_overrides_add_up(topology: Topology) -> None:
    own = made(device("b-acc-01"), "tag", value="lab")
    tags = rule("Tags", {"of": "device", "role": ["access"]}, "tag", value="lab")
    [r] = apply(topology, [own], NOW, [tags]).ruled
    assert ids(r.matches) == ["b-acc-01", "b-acc-02"]
    assert r.overridden == []


def test_an_exception_takes_an_object_out(topology: Topology) -> None:
    hide = rule("Quiet", {"of": "device", "role": ["access"]}, "hide-status")
    out = Excepted(target=device("b-acc-01"), by="Sam", at=NOW)
    over = apply(topology, [], NOW, [hide.model_copy(update={"excepted": [out]})])
    priorities = {d.name: d.priority for d in over.topology.devices}
    assert (priorities["b-acc-01"], priorities["b-acc-02"]) == (None, "ignored")
    assert ids(over.ruled[0].matches) == ["b-acc-02"]


def test_hiding_sites_from_status_ignores_their_devices(topology: Topology) -> None:
    hide = rule("North", {"of": "site", "region": ["North"]}, "hide-status")
    over = apply(topology, [], NOW, [hide])
    assert [d.name for d in over.topology.devices if d.priority == "ignored"] == [
        "d-wan-01"
    ]


def test_one_expired_or_withdrawn_stops_applying(topology: Topology) -> None:
    hide = rule("Quiet", {"of": "device", "role": ["access"]}, "hide-status")
    expired = hide.model_copy(update={"expires": NOW - timedelta(minutes=1)})
    withdrawn = hide.model_copy(
        update={"id": "w", "withdrawn": Stamp(by="Sam", at=NOW)}
    )
    over = apply(topology, [], NOW, [expired, withdrawn])
    assert [(r.state, r.matches) for r in over.ruled] == [("expired", [])]
    assert not [d for d in over.topology.devices if d.priority == "ignored"]


def test_one_the_topology_will_not_take_is_not_applied(topology: Topology) -> None:
    nowhere = rule(
        "Nowhere", {"of": "device", "role": ["access"]}, "lock", key="site", value="Z"
    )
    quiet = rule("Quiet", {"of": "device", "name": ["d-*"]}, "hide-status")
    over = apply(topology, [], NOW, [nowhere, quiet])
    [refused, applied] = over.ruled
    assert refused.state == "not-applied" and "Z" in (refused.reason or "")
    assert refused.matches == []
    assert applied.state == "active"
    assert {d.name: d.site for d in over.topology.devices}["b-acc-01"] == "B"
    assert {d.name: d.priority for d in over.topology.devices}["d-wan-01"] == "ignored"


def test_rules_on_ports_go_to_discovery(topology: Topology) -> None:
    ports = rule(
        "Chains",
        {"of": "port", "role": ["access"], "interface": ["Gi1/0/48"]},
        "ignore-neighbor",
        value="*-acc-*",
    )
    over = apply(topology, [], NOW, [ports])
    [port] = over.rules.ports
    assert port.devices == {"b-acc-01", "b-acc-02"}
    assert port.on("b-acc-01", "GigabitEthernet1/0/48")
    assert not port.on("b-acc-01", "GigabitEthernet1/0/47")
    assert not port.on("b-wan-01", "GigabitEthernet1/0/48")
    assert ids(over.ruled[0].matches) == ["b-acc-01", "b-acc-02"]


# The handover.


def test_the_handover_lists_rules_made_withdrawn_and_expired() -> None:
    early = rule("Lab", {"of": "device"}, "tag", value="lab").model_copy(
        update={"at": NOW - timedelta(hours=20)}
    )
    withdrawn = early.model_copy(
        update={"withdrawn": Stamp(by="Sam", at=NOW - timedelta(hours=2))}
    )
    expiring = rule("Map", {"of": "device"}, "hide-map").model_copy(
        update={"expires": NOW - timedelta(hours=1)}
    )
    found = rule_lines([withdrawn, expiring], NOW - timedelta(hours=12), NOW)
    assert [(line.event, line.rule.name) for line in found] == [
        ("made", "Map"),
        ("expired", "Map"),
        ("withdrawn", "Lab"),
    ]


# The API.


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """The API on a copy of the layered sample."""
    shutil.copy(SAMPLE, tmp_path / "layers.yaml")
    return TestClient(
        create_app(tmp_path / "layers.yaml", files=files(tmp_path), warm=False)
    )


def files(at: Path) -> Files:
    return Files(
        operations=at / "ops.json",
        changes=at / "changes.json",
        overrides=at / "overrides.json",
        handovers=at / "handovers.json",
        incidents=at / "incidents.json",
    )


ACCESS_48 = {"of": "port", "role": ["access"], "interface": ["Gi1/0/48"]}
CHAINS = {
    "name": "Daisy chains",
    "match": ACCESS_48,
    "kind": "ignore-neighbor",
    "value": "*-acc-*",
    "by": "Pat",
}


def titles(client: TestClient) -> list[str]:
    return [f["title"] for f in client.get("/api/discovery").json()["findings"]]


def make(client: TestClient, body: dict) -> dict:
    response = client.post("/api/rules", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def test_the_preview_says_what_a_rule_on_ports_would_set_aside(
    client: TestClient,
) -> None:
    narrow = client.post("/api/rules/preview", json=CHAINS).json()
    assert narrow["set_aside"] == ["Undocumented link elp-acc-01 – elp-acc-02"]
    assert narrow["raised"] == []
    assert len(narrow["matches"]) == 53
    # Any neighbor on port 48 of any kind: the real uplink finding too.
    wide = {
        **CHAINS,
        "match": {**ACCESS_48, "interface": ["*/0/48"]},
        "value": "*",
    }
    found = client.post("/api/rules/preview", json=wide).json()
    # The lab switch on clt-gsw-01's port 48 is plugged in for half of all
    # three-hour blocks, so it is set aside only when discovery sees it.
    lab = [t for t in titles(client) if t.startswith("Unknown neighbor lab-sw-01")]
    assert found["set_aside"] == [
        "iad-gry-01 – iad-gsw-01 on another port",
        "Undocumented link elp-acc-01 – elp-acc-02",
        *lab,
    ]
    # Its documented port is down, as nothing is plugged into it.
    assert found["raised"] == []
    # Every row on one switch dropped: its uplinks are no longer seen.
    every = {
        **CHAINS,
        "match": {"of": "port", "name": ["aus-acc-01"], "interface": ["*"]},
        "value": "*",
    }
    assert client.post("/api/rules/preview", json=every).json()["raised"] == [
        "aus-wan-01 – aus-acc-01 not seen",
        "aus-wan-02 – aus-acc-01 not seen",
    ]
    # Nothing was made.
    assert client.get("/api/overrides").json()["rules"] == []


def test_a_rule_on_ports_sets_findings_aside(client: TestClient) -> None:
    before = titles(client)
    phones = [t for t in before if t.startswith("Unknown neighbor SEP")]
    assert len(phones) == 2
    make(client, CHAINS)
    make(
        client,
        {
            "name": "IP phones",
            "match": {"of": "port", "role": ["access"], "interface": ["*"]},
            "kind": "ignore-neighbor",
            "value": "SEP*",
            "by": "Pat",
        },
    )
    after = titles(client)
    assert sorted(t for t in before if t not in after) == sorted(
        [*phones, "Undocumented link elp-acc-01 – elp-acc-02"]
    )
    listed = client.get("/api/overrides").json()["rules"]
    assert [r["name"] for r in listed] == ["IP phones", "Daisy chains"]
    assert all(r["state"] == "active" for r in listed)


def test_a_label_rule_on_two_platforms(client: TestClient) -> None:
    made_ = make(
        client,
        {
            "name": "EoL 2027",
            "match": {"of": "device", "platform": ["ISR4431", "C9200-24T"]},
            "kind": "label",
            "key": "lifecycle",
            "value": "EoL 2027",
            "by": "Pat",
        },
    )
    [listed] = client.get("/api/overrides").json()["rules"]
    assert listed["id"] == made_["id"]
    assert len(listed["matches"]) == 20


def test_what_repeats_or_will_not_be_taken_is_refused(client: TestClient) -> None:
    make(client, CHAINS)
    again = client.post("/api/rules", json={**CHAINS, "name": "Other"})
    assert again.status_code == 409 and "Daisy chains" in again.json()["detail"]
    named = client.post("/api/rules", json={**CHAINS, "value": "x*"})
    assert named.status_code == 409 and "named" in named.json()["detail"]
    nowhere = {
        "name": "Nowhere",
        "match": {"of": "device", "role": ["access"]},
        "kind": "lock",
        "key": "site",
        "value": "ZZZ",
        "by": "Pat",
    }
    refused = client.post("/api/rules", json=nowhere)
    assert refused.status_code == 409, refused.text
    late = {**CHAINS, "name": "Late", "expires": (NOW - timedelta(days=1)).isoformat()}
    assert client.post("/api/rules", json=late).status_code == 422


def test_hiding_by_rule_changes_the_topology_served(client: TestClient) -> None:
    body = {
        "name": "Quiet branches",
        "match": {"of": "device", "platform": ["C9200-24T"]},
        "kind": "hide-status",
        "by": "Pat",
    }
    r = make(client, body)
    devices = client.get("/api/topology").json()["devices"]
    quiet = [d["name"] for d in devices if d.get("priority") == "ignored"]
    assert len(quiet) == 10
    # Taken out of it, and put back.
    one = {"target": {"kind": "device", "id": quiet[0]}, "by": "Sam"}
    out = client.post(f"/api/rules/{r['id']}/except", json=one)
    assert out.status_code == 200, out.text
    assert out.json()["excepted"][0]["target"]["id"] == quiet[0]
    assert client.post(f"/api/rules/{r['id']}/except", json=one).status_code == 409
    devices = client.get("/api/topology").json()["devices"]
    assert sum(d.get("priority") == "ignored" for d in devices) == 9
    [listed] = client.get("/api/overrides").json()["rules"]
    assert len(listed["matches"]) == 9
    back = client.post(f"/api/rules/{r['id']}/include", json=one)
    assert back.status_code == 200 and back.json()["excepted"] == []
    assert client.post(f"/api/rules/{r['id']}/include", json=one).status_code == 409
    other = {"target": {"kind": "device", "id": "dal-wan-01"}, "by": "Sam"}
    assert client.post(f"/api/rules/{r['id']}/except", json=other).status_code == 409
    # Withdrawn, it stops applying.
    gone = client.post(f"/api/rules/{r['id']}/withdraw", json={"by": "Sam"})
    assert gone.status_code == 204
    devices = client.get("/api/topology").json()["devices"]
    assert not [d for d in devices if d.get("priority") == "ignored"]
    assert client.get("/api/overrides").json()["rules"] == []
    assert (
        client.post(f"/api/rules/{r['id']}/withdraw", json={"by": "Sam"}).status_code
        == 404
    )


def test_a_rule_expires_and_is_renewed(client: TestClient) -> None:
    soon = datetime.now(UTC) + timedelta(seconds=1)
    r = make(client, {**CHAINS, "expires": soon.isoformat()})
    assert "Undocumented link elp-acc-01 – elp-acc-02" not in titles(client)
    time.sleep(1.2)
    [listed] = client.get("/api/overrides").json()["rules"]
    assert listed["state"] == "expired"
    assert "Undocumented link elp-acc-01 – elp-acc-02" in titles(client)
    renewed = client.post(
        f"/api/rules/{r['id']}/renew", json={"by": "Sam", "expires": None}
    )
    assert renewed.status_code == 200
    assert "Undocumented link elp-acc-01 – elp-acc-02" not in titles(client)


def test_rules_are_kept_and_go_in_the_handover(tmp_path: Path) -> None:
    shutil.copy(SAMPLE, tmp_path / "layers.yaml")
    first = TestClient(
        create_app(tmp_path / "layers.yaml", files=files(tmp_path), warm=False)
    )
    made_ = make(first, CHAINS)
    again = TestClient(
        create_app(tmp_path / "layers.yaml", files=files(tmp_path), warm=False)
    )
    [listed] = again.get("/api/overrides").json()["rules"]
    assert listed["id"] == made_["id"] and listed["state"] == "active"
    handover = again.get("/api/handover").json()
    assert [(line["event"], line["rule"]["name"]) for line in handover["rules"]] == [
        ("made", "Daisy chains")
    ]
