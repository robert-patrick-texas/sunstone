from datetime import UTC, datetime, timedelta

import pytest

from sunstone.cabling import Cabling
from sunstone.discovery import Visibility
from sunstone.impact import Network
from sunstone.mockgen import PRESETS, generate
from sunstone.model import Topology
from sunstone.monitor import Monitor
from sunstone.simulate import SimulatedState, monitored

AT = datetime(2026, 10, 27, 15, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def topology() -> Topology:
    return generate(PRESETS["small"], seed=1)


@pytest.fixture(scope="module")
def cabling(topology: Topology) -> Cabling:
    return Cabling(topology, watched=set(monitored(topology)))


def test_without_drift_the_cables_are_as_documented(topology: Topology) -> None:
    exact = Cabling(topology)
    assert [(c.a, c.b) for c in exact.cables] == [(ln.a, ln.b) for ln in topology.links]
    assert exact.dangling == []
    assert (exact.hidden, exact.silent, exact.extra) == (set(), set(), [])


def test_drift_is_seeded_once_of_each_kind_and_stays_put(
    topology: Topology, cabling: Cabling
) -> None:
    assert [len(cabling.hidden), len(cabling.moved), len(cabling.rewired)] == [1, 1, 1]
    assert len(cabling.silent) == 1
    assert [c.platform is not None for c in cabling.extra] == [False, True]
    again = Cabling(topology, watched=set(monitored(topology)))
    assert again.cables == cabling.cables
    # The moved and rewired links each leave a documented port without a cable.
    assert len(cabling.dangling) == 2


def test_live_state_follows_the_real_cables(
    topology: Topology, cabling: Cabling
) -> None:
    state = SimulatedState(topology, cabling=cabling)
    readings = {(i.device, i.interface): i for i in state.snapshot(AT).interfaces}
    watched = state.watched
    for end, _ in cabling.dangling:
        if end.device in watched:
            reading = readings[(end.device, end.interface)]
            assert (reading.oper, reading.in_pct, reading.out_pct) == ("down", 0, 0)
    for cable in [*(c for c in cabling.cables if not c.documented), *cabling.extra]:
        for end in (cable.a, cable.b):
            if end.device in watched:
                assert (end.device, end.interface) in readings
    # As documented, the same ports carry the same traffic.
    plain = SimulatedState(topology)
    before = {(i.device, i.interface): i for i in plain.snapshot(AT).interfaces}
    moved_away = {(e.device, e.interface) for e, _ in cabling.dangling}
    for key, reading in before.items():
        if key not in moved_away:
            assert readings[key] == reading


def test_a_link_cabled_elsewhere_reads_down_and_costs_redundancy(
    topology: Topology, cabling: Cabling
) -> None:
    state = SimulatedState(topology, cabling=cabling)
    monitor = Monitor(Network(topology), state)
    problems = monitor.moment(AT).problems.problems
    uncabled = {link.id for _, link in cabling.dangling}
    down = {
        p.target.ids[0]
        for p in problems
        if p.kind == "link-down" and p.target.kind == "links"
    }
    # Unless a fault at that moment takes one of its devices down too.
    assert uncabled & down


def test_a_device_on_a_rewired_uplink_stays_reachable(
    topology: Topology, cabling: Cabling
) -> None:
    state = SimulatedState(topology, cabling=cabling)
    [(link_id, (documented, _))] = cabling.rewired.items()
    link = next(ln for ln in topology.links if ln.id == link_id)
    access = link.b.device if link.a.device == documented else link.a.device
    assert access in state.adjacent
    assert any(
        far == cabling.rewired[link_id][1].device for far, _ in state.adjacent[access]
    )


def test_the_simulator_says_who_is_up_as_its_snapshot_would(
    topology: Topology, cabling: Cabling
) -> None:
    state = SimulatedState(topology, cabling=cabling)
    for hours in range(0, 24, 3):
        at = AT - timedelta(hours=hours)
        assert state.visibility(at) == Visibility.of(state.snapshot(at))
