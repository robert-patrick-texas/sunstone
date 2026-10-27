from collections import Counter
from collections.abc import Collection
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sunstone.api import Files, create_app
from sunstone.cabling import Cabling
from sunstone.discovery import (
    Discovery,
    Neighbor,
    NeighborTable,
    SimulatedDiscovery,
    Visibility,
    compare,
)
from sunstone.discovery_log import DiscoveryLog
from sunstone.live import DeviceHistory, DeviceState, InterfaceState, NetworkState
from sunstone.mockgen import PRESETS, generate, to_yaml
from sunstone.model import Link, Topology
from sunstone.problems import short_interface

AT = datetime(2026, 10, 27, 15, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def topology() -> Topology:
    return generate(PRESETS["small"], seed=1)


class AllUp:
    """Live state with every device watched and up, and some links down."""

    retention = timedelta(hours=24)

    def __init__(self, topology: Topology, down: frozenset[str] = frozenset()) -> None:
        self.topology = topology
        self.down = down

    def snapshot(self, now: datetime) -> NetworkState:
        return NetworkState(
            source="test",
            generated_at=now,
            positions=[],
            devices=[
                DeviceState(
                    device=d.name,
                    status="up",
                    observed_at=now,
                    stale=False,
                    reachability=[],
                )
                for d in self.topology.devices
            ],
            interfaces=[
                InterfaceState(
                    device=end.device,
                    interface=end.interface,
                    oper="down" if ln.id in self.down else "up",
                    in_pct=1,
                    out_pct=1,
                    observed_at=now,
                    stale=False,
                )
                for ln in self.topology.links
                for end in (ln.a, ln.b)
            ],
        )

    def events(self, since: datetime, until: datetime) -> list:
        return []

    def history(
        self, device: str, since: datetime, until: datetime
    ) -> DeviceHistory | None:
        return None


def tables(topology: Topology, skip: Collection[str] = ()) -> dict[str, list[Neighbor]]:
    """Every device's table, reporting exactly the documented links, spelled
    the different ways devices spell them."""
    found: dict[str, list[Neighbor]] = {d.name: [] for d in topology.devices}
    for ln in topology.links:
        if ln.id in skip:
            continue
        for here, there in ((ln.a, ln.b), (ln.b, ln.a)):
            found[here.device].append(
                Neighbor(
                    interface=here.interface,
                    remote=there.device.upper() + ".net.example",
                    remote_port=short_interface(there.interface),
                    protocol="lldp",
                )
            )
    return found


def run(found: dict[str, list[Neighbor]]) -> Discovery:
    return Discovery(
        source="test",
        at=AT,
        tables=[NeighborTable(device=d, neighbors=n) for d, n in found.items()],
    )


def uplink(topology: Topology, n: int = 0) -> Link:
    roles = {d.name: d.role for d in topology.devices}
    return [
        ln
        for ln in topology.links
        if {roles[ln.a.device], roles[ln.b.device]} == {"access", "distribution"}
    ][n]


class TestCompare:
    def test_tables_matching_the_documentation_confirm_every_link(
        self, topology: Topology
    ) -> None:
        result = compare(topology, run(tables(topology)))
        assert result.confirmed == len(topology.links)
        assert result.links == {}
        assert result.findings == []

    def test_a_link_no_one_reports_is_not_seen_unless_it_is_down(
        self, topology: Topology
    ) -> None:
        link = uplink(topology)
        found = run(tables(topology, skip={link.id}))
        result = compare(topology, found, Visibility.of(AllUp(topology).snapshot(AT)))
        assert result.links == {link.id: "not-seen"}
        [finding] = result.findings
        assert (finding.kind, finding.link) == ("not-seen", link.id)
        assert "neither end reports it" in finding.detail
        down = Visibility.of(AllUp(topology, frozenset({link.id})).snapshot(AT))
        assert compare(topology, found, down).links == {link.id: "down"}
        assert compare(topology, found, down).findings == []

    def test_a_link_no_answering_device_can_see_is_unchecked(
        self, topology: Topology
    ) -> None:
        link = uplink(topology)
        found = tables(topology)
        for device in (link.a.device, link.b.device):
            del found[device]
        result = compare(topology, run(found))
        assert result.links[link.id] == "unchecked"
        assert all(f.kind != "not-seen" for f in result.findings)

    def test_a_cable_on_another_port_or_device_is_a_mismatch(
        self, topology: Topology
    ) -> None:
        moved, rewired = uplink(topology, 0), uplink(topology, 3)
        found = tables(topology, skip={moved.id, rewired.id})
        found[moved.a.device].append(
            Neighbor(
                interface=moved.a.interface,
                remote=moved.b.device,
                remote_port="TenGigabitEthernet1/0/99",
                protocol="cdp",
            )
        )
        found[rewired.a.device].append(
            Neighbor(
                interface=rewired.a.interface,
                remote="lab-sw-01",
                remote_port="Gi0/1",
                protocol="cdp",
                platform="WS-C2960X-24TS",
            )
        )
        result = compare(topology, run(found))
        assert result.links == {moved.id: "mismatch", rewired.id: "mismatch"}
        kinds = {f.link: f.kind for f in result.findings}
        assert kinds == {moved.id: "wrong-port", rewired.id: "wrong-neighbor"}
        wrong = next(f for f in result.findings if f.kind == "wrong-neighbor")
        assert "lab-sw-01 Gi0/1 (WS-C2960X-24TS, not in the topology)" in wrong.detail

    def test_cables_no_one_documented_are_found_once(self, topology: Topology) -> None:
        found = tables(topology)
        a, b = "dal-acc-01", "dal-acc-02"
        found[a].append(
            Neighbor(
                interface="Gi1/0/48", remote=b, remote_port="Gi1/0/48", protocol="lldp"
            )
        )
        found[b].append(
            Neighbor(
                interface="GigabitEthernet1/0/48",
                remote=a,
                remote_port="GigabitEthernet1/0/48",
                protocol="cdp",
            )
        )
        found[a].append(
            Neighbor(
                interface="Gi1/0/47",
                remote="lab-sw-02",
                remote_port="Gi0/1",
                protocol="cdp",
            )
        )
        result = compare(topology, run(found))
        assert [(f.kind, f.devices) for f in result.findings] == [
            ("undocumented", [a, b]),
            ("unknown-device", [a]),
        ]

    def test_a_device_that_sees_nothing_is_one_finding(
        self, topology: Topology
    ) -> None:
        found = tables(topology)
        device = "hou-acc-01"
        found[device] = []
        # It does not advertise either, so its neighbors do not see it.
        for name, rows in found.items():
            found[name] = [n for n in rows if not n.remote.lower().startswith(device)]
        result = compare(
            topology, run(found), Visibility.of(AllUp(topology).snapshot(AT))
        )
        assert [(f.kind, f.devices) for f in result.findings] == [
            ("no-neighbors", [device])
        ]
        theirs = {
            ln.id for ln in topology.links if device in (ln.a.device, ln.b.device)
        }
        assert result.links == dict.fromkeys(sorted(theirs), "not-seen")


def drifted(topology: Topology) -> Cabling:
    """The topology cabled with drift, every device watched."""
    return Cabling(topology, watched={d.name for d in topology.devices})


def lab_in(cabling: Cabling) -> datetime:
    """A moment when the lab switch is plugged in."""
    [lab] = [c for c in cabling.extra if c.temporary]
    hours = (AT + timedelta(hours=3 * k) for k in range(16))
    return next(at for at in hours if cabling.in_place(lab.link.id, at))


class TestSimulated:
    def test_every_kind_of_disagreement_is_seeded_and_found(
        self, topology: Topology
    ) -> None:
        state = AllUp(topology)
        cabling = drifted(topology)
        at = lab_in(cabling)
        found = SimulatedDiscovery(topology, cabling, state).discover(at)
        result = compare(topology, found, Visibility.of(state.snapshot(at)))
        assert Counter(f.kind for f in result.findings) == {
            "wrong-neighbor": 1,
            "wrong-port": 1,
            "not-seen": 1,
            "undocumented": 1,
            "unknown-device": 1,
            "no-neighbors": 1,
        }
        assert set(result.links.values()) == {"mismatch", "not-seen"}
        # The cables to draw: each one seen other than as documented.
        assert sorted(s.finding.split(":")[0] for s in result.seen) == [
            "undocumented",
            "unknown-device",
            "wrong-neighbor",
            "wrong-port",
        ]
        lab = next(s for s in result.seen if not s.known)
        assert (lab.b.device, lab.platform) == ("lab-sw-01", "WS-C2960X-24TS")

    def test_the_lab_switch_comes_and_goes(self, topology: Topology) -> None:
        state = AllUp(topology)
        cabling = drifted(topology)
        discovery = SimulatedDiscovery(topology, cabling, state)
        [lab] = [c for c in cabling.extra if c.temporary]
        seen = []
        for k in range(16):
            at = AT + timedelta(hours=3 * k)
            found = compare(
                topology, discovery.discover(at), Visibility.of(state.snapshot(at))
            )
            unknown = any(f.kind == "unknown-device" for f in found.findings)
            assert unknown == cabling.in_place(lab.link.id, at)
            seen.append(unknown)
        assert True in seen and False in seen

    def test_the_same_seed_gives_the_same_disagreements(
        self, topology: Topology
    ) -> None:
        state = AllUp(topology)
        first = SimulatedDiscovery(topology, drifted(topology), state).discover(AT)
        again = SimulatedDiscovery(topology, drifted(topology), state).discover(
            AT + timedelta(minutes=15)
        )
        assert first.tables == again.tables

    def test_down_links_and_devices_are_not_reported(self, topology: Topology) -> None:
        link = uplink(topology, 5)
        state = AllUp(topology, frozenset({link.id}))
        found = SimulatedDiscovery(topology, drifted(topology), state).discover(AT)
        result = compare(topology, found, Visibility.of(state.snapshot(AT)))
        assert result.links.get(link.id) == "down"
        assert all(f.link != link.id for f in result.findings)


@pytest.fixture(scope="module")
def log(topology: Topology) -> DiscoveryLog:
    state = AllUp(topology)
    log = DiscoveryLog(
        topology, SimulatedDiscovery(topology, drifted(topology), state), state
    )
    log.warm()
    return log


class TestLog:
    def test_a_finding_seen_all_day_was_seen_before_history_and_still_is(
        self, log: DiscoveryLog
    ) -> None:
        now = datetime.now(UTC)
        result = log.comparison(now)
        wrong = next(f for f in result.findings if f.kind == "wrong-neighbor")
        assert (wrong.first_seen, wrong.last_seen) == (None, None)
        assert result.history_from is not None
        assert now - result.history_from >= timedelta(hours=23, minutes=45)

    def test_a_lab_switch_is_seen_for_a_while_then_gone(
        self, log: DiscoveryLog
    ) -> None:
        now = datetime.now(UTC)
        step = log.source.interval
        runs = [log.run_of(now) - step * k for k in range(95, -1, -1)]
        lab = [
            any(f.kind == "unknown-device" for f in log.comparison(r).findings)
            for r in runs
        ]
        # The last run that shows it, followed by one that does not.
        last = (
            next(i for i in range(len(runs) - 1, 0, -1) if lab[i - 1] and not lab[i])
            - 1
        )
        gone = log.comparison(runs[last + 1]).gone
        [unplugged] = [f for f in gone if f.kind == "unknown-device"]
        assert unplugged.last_seen == runs[last]
        shown = next(
            f for f in log.comparison(runs[last]).findings if f.kind == "unknown-device"
        )
        assert shown.last_seen == runs[last]
        # Plugged in at a three-hour block's start, or before history.
        assert shown.first_seen is None or shown.first_seen.hour % 3 == 0

    def test_without_history_everything_was_seen_before_it(
        self, topology: Topology
    ) -> None:
        state = AllUp(topology)
        log = DiscoveryLog(
            topology, SimulatedDiscovery(topology, drifted(topology), state), state
        )
        now = datetime.now(UTC)
        result = log.comparison(now)
        assert result.history_from == log.run_of(now)
        assert all(
            f.first_seen is None and f.last_seen is None for f in result.findings
        )
        assert result.gone == []
        log.forget()
        assert log.comparison(now).history_from == log.run_of(now)


def test_the_api_compares_the_latest_run_once(
    topology: Topology, tmp_path: Path
) -> None:
    path = tmp_path / "small.yaml"
    path.write_text(to_yaml(topology, "test"), encoding="utf-8")
    files = Files(operations=tmp_path / "ops.json", layouts=tmp_path / "l.json")
    client = TestClient(create_app(path, files=files, warm=False))
    first = client.get("/api/discovery").json()
    assert first["source"] == "simulated"
    assert first["confirmed"] > 0
    assert first["polled"]
    assert client.get("/api/discovery").json() == first
    hour_ago = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    earlier = client.get("/api/discovery", params={"at": hour_ago}).json()
    assert earlier["at"] < first["at"]
    too_old = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    assert client.get("/api/discovery", params={"at": too_old}).status_code == 422
