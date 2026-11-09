"""Priorities on cables and circuits, and resources with a status of their own."""

from collections.abc import Callable
from typing import Any

import pytest
from pydantic import ValidationError
from test_status import NOW, groups, red_handoffs, topology, view, whole

from sunstone.across import Across
from sunstone.handover import Handover, outages
from sunstone.impact import Failures, Network
from sunstone.live import StateEvent, TunnelState
from sunstone.model import Topology, ratings
from sunstone.oncall import RoutedProblem
from sunstone.problems import find_problems
from sunstone.status import ResourceStatus, Statuses, resources_needing

__all__ = ["topology"]  # the fixture, shared with the status tests

AB = "a-wan-01:p2"  # the cable between sites A and B, in Texas
INET_D1 = "d-wan-01:i1"


def changed(topology: Topology, edit: Callable[[dict[str, Any]], None]) -> Topology:
    """The topology with its data edited."""
    data = topology.model_dump(exclude={"links": {"__all__": {"id"}}})
    edit(data)
    return Topology.model_validate(data)


def at(data: dict[str, Any], a_end: str) -> dict[str, Any]:
    """A link's data by its A end, as ``device:port``."""
    return next(
        link
        for link in data["links"]
        if f"{link['a']['device']}:{link['a']['interface']}" == a_end
    )


def rated(topology: Topology, a_end: str, priority: str) -> Topology:
    """The topology with one link's own priority set."""
    return changed(topology, lambda d: at(d, a_end).update(priority=priority))


def link_id(topology: Topology, a_end: str) -> str:
    return next(
        x.id for x in topology.links if f"{x.a.device}:{x.a.interface}" == a_end
    )


# Ratings


def test_ratings_default_by_role_and_who_answers(topology: Topology) -> None:
    t = red_handoffs(topology)
    r = ratings(t)
    tenant = r[link_id(t, "a-wan-01:r1")]
    assert tenant == ("low", "default", "access", "T")
    assert r[link_id(t, AB)] == ("medium", "default", "internal", None)
    assert r[link_id(t, INET_D1)] == ("medium", "default", "tbd", None)


def test_ratings_from_devices_far_ends_links_and_the_table(topology: Topology) -> None:
    def edit(d: dict[str, Any]) -> None:
        next(x for x in d["devices"] if x["name"] == "d-wan-01")["priority"] = "high"
        next(x for x in d["externals"] if x["name"] == "r-a")["priority"] = "medium"
        at(d, "a-wan-01:p3")["priority"] = "ignored"
        d["priorities"] = {"internal": "low"}

    t = changed(red_handoffs(topology), edit)
    r = ratings(t)
    assert r[link_id(t, "d-wan-01:i1")][:3] == ("high", "device", "d-wan-01")
    assert r[link_id(t, "c-wan-01:p3")][:3] == ("high", "device", "d-wan-01")
    # The far end's, while the party downstream still answers first.
    assert r[link_id(t, "a-wan-01:r1")] == ("medium", "device", "r-a", "T")
    assert r[link_id(t, "a-wan-01:p3")][:2] == ("ignored", "link")
    assert r[link_id(t, AB)][:3] == ("low", "default", "internal")


def test_the_highest_default_of_several_roles(topology: Topology) -> None:
    t = changed(
        red_handoffs(topology),
        lambda d: at(d, "a-wan-01:r1").update(edges=["access", "transit"]),
    )
    assert ratings(t)[link_id(t, "a-wan-01:r1")] == (
        "medium",
        "default",
        "transit",
        None,
    )


# Status


def test_a_low_cable_down_degrades_its_sites_only(topology: Topology) -> None:
    w = whole(rated(topology, AB, "low"), cut={AB})
    assert w.status == "operational"
    assert groups(w) == {"A": "degraded", "B": "degraded"}


def test_an_ignored_circuit_down_degrades_nothing(topology: Topology) -> None:
    t = rated(topology, INET_D1, "ignored")
    assert whole(topology, cut={INET_D1}).status == "degraded"
    w = whole(t, cut={INET_D1})
    assert (w.status, w.groups) == ("operational", [])


def test_low_and_ignored_do_not_change_reach(topology: Topology) -> None:
    t = rated(rated(topology, AB, "ignored"), "b-wan-01:p2", "ignored")
    w = whole(t, cut={AB, "b-wan-01:p2"})
    assert groups(w)["B"] == "offline"
    assert w.status == "degraded"


# Problems


def test_an_ignored_link_raises_no_problem(topology: Topology) -> None:
    t = rated(topology, INET_D1, "ignored")
    found = find_problems(Network(t), view(t, cut={INET_D1}))
    assert [p.id for p in found] == []
    assert [
        p.kind for p in find_problems(Network(topology), view(topology, cut={INET_D1}))
    ] == ["link-down"]


def test_high_problems_come_first(topology: Topology) -> None:
    cut = {"c-wan-01:p3", "d-wan-01:i1", "d-wan-01:i2", AB}
    plain = find_problems(Network(topology), view(topology, cut=cut))
    assert [(p.kind, p.priority) for p in plain] == [
        ("outage", "medium"),
        ("link-down", "medium"),
    ]
    t = rated(topology, AB, "high")
    found = find_problems(Network(t), view(t, cut=cut))
    assert [(p.kind, p.priority) for p in found] == [
        ("link-down", "high"),
        ("outage", "medium"),
    ]


def test_a_high_device_puts_its_outage_first(topology: Topology) -> None:
    def edit(d: dict[str, Any]) -> None:
        next(x for x in d["devices"] if x["name"] == "d-wan-01")["priority"] = "high"
        at(d, "c-wan-01:p3")["priority"] = "medium"

    t = changed(topology, edit)
    cut = {"c-wan-01:p3", "d-wan-01:i1", "d-wan-01:i2"}
    found = find_problems(Network(t), view(t, down={"b-acc-02"}, cut=cut))
    assert [(p.id, p.priority) for p in found][0] == ("outage:d-wan-01", "high")


def test_a_downstream_link_says_who_answers(topology: Topology) -> None:
    t = red_handoffs(topology)
    found = find_problems(Network(t), view(t, cut={"a-wan-01:r1"}))
    assert [(p.priority, p.responsible) for p in found] == [("low", "T")]


# Resources


@pytest.fixture
def resourced(topology: Topology) -> Topology:
    """The topology with CIDs on its circuits, an Internet circuit at C too,
    a fabric over black, and resources: the ways out, blue's tunnel, the
    fabric, and all three."""

    def edit(d: dict[str, Any]) -> None:
        d["links"].append(
            {**at(d, "a-wan-01:i1"), "a": {"device": "c-wan-01", "interface": "i1"}}
        )
        for a_end, cid in (
            ("a-wan-01:i1", "A-INET"),
            (INET_D1, "D-INET-1"),
            ("d-wan-01:i2", "D-INET-2"),
        ):
            at(d, a_end)["enterprise_cid"] = cid
        at(d, AB)["enterprise_cid"] = {"a": "A-B", "z": "B-A"}
        d["fabrics"] = [
            {
                "name": "F",
                "network": "blue",
                "rides": "black",
                "shape": "hub-spoke",
                "members": [
                    {"device": "a-wan-01", "interface": "Tunnel9", "role": "hub"},
                    {"device": "c-wan-01", "interface": "Tunnel9", "role": "spoke"},
                    {"device": "d-wan-01", "interface": "Tunnel9", "role": "spoke"},
                ],
            }
        ]
        d["resources"] = [
            {"name": "Way out", "circuits": ["A-INET", "D-INET-1", "D-INET-2"]},
            {"name": "Blue", "tunnels": ["BLUE-A-D"], "circuits": ["B-A"]},
            {"name": "Fabric", "fabrics": ["F"]},
            {"name": "All", "resources": ["Way out", "Blue", "Fabric"]},
        ]

    return changed(topology, edit)


def resources(
    t: Topology,
    down: set[str] | None = None,
    cut: set[str] | None = None,
    tunnels: list[TunnelState] | None = None,
) -> dict[str, ResourceStatus]:
    report = Statuses(t).report(NOW, view(t, down or set(), cut or set(), tunnels))
    return {r.name: r for r in report.resources}


def brief(found: dict[str, ResourceStatus]) -> dict[str, tuple[str, list[str]]]:
    return {n: (r.status, r.reasons) for n, r in found.items()}


def test_resources_are_operational_with_everything_up(resourced: Topology) -> None:
    found = resources(resourced)
    assert {n: r.status for n, r in found.items()} == dict.fromkeys(
        ["Way out", "Blue", "Fabric", "All"], "operational"
    )
    blue = found["Blue"].members
    assert [(m.kind, m.name, m.link) for m in blue] == [
        ("circuit", "B-A", link_id(resourced, AB)),
        ("tunnel", "BLUE-A-D", None),
    ]


def test_a_member_down_degrades_and_all_down_is_offline(resourced: Topology) -> None:
    found = brief(resources(resourced, cut={INET_D1}))
    assert found["Way out"] == ("degraded", ["D-INET-1 down"])
    assert found["All"] == ("degraded", ["Way out degraded"])
    found = brief(resources(resourced, cut={"a-wan-01:i1", INET_D1, "d-wan-01:i2"}))
    assert found["Way out"] == (
        "offline",
        ["A-INET down", "D-INET-1 down", "D-INET-2 down"],
    )


def test_a_circuit_whose_device_is_down_or_cut_off_cannot_be_used(
    resourced: Topology,
) -> None:
    # In a snapshot, a device down takes its links down with it; a "what
    # if" fails the device alone.
    found = brief(resources(resourced, down={"d-wan-01"}))
    assert found["Way out"] == ("degraded", ["D-INET-1 down", "D-INET-2 down"])
    report = Statuses(resourced).of(NOW, {"d-wan-01"}, set(), [])
    assert report.resources[0].reasons == [
        "D-INET-1: d-wan-01 down",
        "D-INET-2: d-wan-01 down",
    ]
    # D's circuits are up, but with A's and C's down nothing joins it to
    # the core.
    cut = {"c-wan-01:p3", "a-wan-01:i1", "c-wan-01:i1"}
    found = brief(resources(resourced, cut=cut))
    assert found["Way out"] == (
        "offline",
        ["A-INET down", "D-INET-1 cut off", "D-INET-2 cut off"],
    )


def test_tunnels_and_fabrics_count_by_their_state(resourced: Topology) -> None:
    down = [
        TunnelState(tunnel="BLUE-A-D", network="blue", status="down"),
        TunnelState(tunnel="F:c-wan-01~a-wan-01", network="blue", status="down"),
    ]
    found = brief(resources(resourced, tunnels=down))
    assert found["Blue"] == ("degraded", ["BLUE-A-D down"])
    assert found["Fabric"] == ("degraded", ["F: 1 of 2 tunnels down"])
    assert found["All"] == ("degraded", ["Blue degraded", "Fabric degraded"])
    down.append(
        TunnelState(tunnel="F:d-wan-01~a-wan-01", network="blue", status="down")
    )
    assert brief(resources(resourced, tunnels=down))["Fabric"] == (
        "offline",
        ["F: all 2 tunnels down"],
    )


def test_a_resource_counts_whatever_its_members_priorities(
    resourced: Topology,
) -> None:
    t = rated(resourced, INET_D1, "ignored")
    assert brief(resources(t, cut={INET_D1}))["Way out"][0] == "degraded"


def test_what_if_lists_the_resources_it_changes(resourced: Topology) -> None:
    across = Across(Network(resourced), Statuses(resourced))
    gone = Failures(links=frozenset([link_id(resourced, INET_D1)]))
    found = across.what_if(gone, None)
    assert [(r.name, r.before, r.after.status) for r in found.resources] == [
        ("Way out", "operational", "degraded"),
        ("All", "operational", "degraded"),
    ]


# The loader


def test_the_loader_rejects_resources_that_do_not_add_up(topology: Topology) -> None:
    def edit(d: dict[str, Any]) -> None:
        at(d, "a-wan-01:i1")["enterprise_cid"] = "X-1"
        at(d, INET_D1)["enterprise_cid"] = "X-1"
        d["resources"] = [
            {"name": "Empty"},
            {"name": "Odd", "circuits": ["NOPE", "X-1"], "tunnels": ["T", "T"]},
            {"name": "Loop", "resources": ["Round"], "fabrics": ["F"]},
            {"name": "Round", "resources": ["Loop", "Gone"]},
            {"name": "Empty", "tunnels": ["BLUE-A-D"]},
        ]

    with pytest.raises(ValidationError) as e:
        changed(topology, edit)
    message = str(e.value)
    for expected in (
        "duplicate resource name 'Empty'",
        "resource 'Empty' has no members",
        "resource 'Odd' names unknown circuit 'NOPE'",
        "resource 'Odd' names circuit 'X-1', which 2 links have",
        "resource 'Odd' names unknown tunnel 'T'",
        "resource 'Odd' names tunnel 'T' twice",
        "resource 'Loop' names unknown fabric 'F'",
        "resource 'Round' names unknown resource 'Gone'",
        "resource 'Loop' is inside itself",
        "resource 'Round' is inside itself",
    ):
        assert expected in message


def test_the_loader_rejects_unknown_priorities(topology: Topology) -> None:
    with pytest.raises(ValidationError):
        rated(topology, AB, "off")
    with pytest.raises(ValidationError):
        changed(topology, lambda d: d.update(priorities={"wan": "low"}))


def test_the_handover_lists_resources_and_marks_high_problems(
    resourced: Topology,
) -> None:
    t = rated(resourced, INET_D1, "high")
    found = find_problems(Network(t), view(t, cut={INET_D1}))
    report = Statuses(t).report(NOW, view(t, cut={INET_D1}))
    handover = Handover(
        since=NOW,
        until=NOW,
        problems=[RoutedProblem.model_validate(dict(p)) for p in found],
        resources=resources_needing(report),
        outages=[],
        pages=[],
        acks=[],
        windows=[],
        changes=[],
        findings=[],
        oncall=None,
    )
    text = handover.message.text
    assert "- High · Circuit D-INET-1 down · d-wan-01 i1 ↔ INET" in text
    assert "Resources (2 not as they should be)" in text
    assert "- Way out degraded: D-INET-1 down" in text


def test_the_handover_leaves_ignored_links_out_of_its_outages(
    topology: Topology,
) -> None:
    t = rated(topology, INET_D1, "ignored")
    events = [
        StateEvent(at=NOW, kind="link-down", link=link_id(t, a_end))
        for a_end in (INET_D1, AB)
    ]
    assert [o.title for o in outages(events, t, NOW)] == ["a-wan-01 – b-wan-01 down"]
