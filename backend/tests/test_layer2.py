"""Layer-2 services, MACsec, port channels, CDP over tunnels, and neighbors
seen over CDP, LLDP, or both."""

import copy
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError
from test_discovery import AllUp

from sunstone.cabling import Beyond, Cabling
from sunstone.changes import applied
from sunstone.discovery import (
    Discovery,
    Fix,
    Neighbor,
    NeighborTable,
    SimulatedDiscovery,
    Visibility,
    compare,
    visibility,
)
from sunstone.impact import Failures, Network
from sunstone.layers import Layers
from sunstone.loader import load_topology
from sunstone.mockgen import to_yaml
from sunstone.model import (
    Link,
    Topology,
    cabled,
    lag_members,
    sees_across,
    transport_hops,
)
from sunstone.simulate import SimulatedState, monitored
from sunstone.status import Statuses

AT = datetime(2026, 11, 8, 15, 0, tzinfo=UTC)
LAYERS = Path(__file__).parents[2] / "data" / "sample" / "layers.yaml"


def _circuit(near: str, port: str, transport: str, cid: str, **more: object) -> dict:
    return {
        "a": {"device": near, "interface": port},
        "b": {"transport": transport, **more},
        "speed_mbps": 1000,
        "kind": "wan",
        "circuit": {"provider": "Metro Co", "circuit_id": cid},
        "edges": ["transit"],
        "neighbors": "far-end",
    }


def metro_data() -> dict:
    """A hub and three branches on carrier Ethernet: an E-Tree rooted at the
    hub with two leaves, an E-LAN joining the hub and two branches, an
    E-Line with MACsec, a GRE tunnel, and a port channel at the hub."""
    return {
        "sites": [
            {"code": code, "name": code, "lat": 30 + i, "lon": -97}
            for i, code in enumerate(["DAL", "A", "B", "C"])
        ],
        "devices": [
            {"name": "dal-core-01", "site": "DAL", "role": "core"},
            {"name": "dal-core-02", "site": "DAL", "role": "core"},
            {"name": "dal-wan-01", "site": "DAL", "role": "wan-edge"},
            {"name": "a-wan-01", "site": "A", "role": "wan-edge"},
            {"name": "b-wan-01", "site": "B", "role": "wan-edge"},
            {"name": "c-wan-01", "site": "C", "role": "wan-edge"},
        ],
        "networks": [
            {"name": "metro", "boundary": "outside", "anchors": ["DAL"]},
            {"name": "corp", "anchors": ["DAL"]},
        ],
        "transports": [
            {
                "name": "Tree",
                "kind": "private-wan",
                "network": "metro",
                "service": "e-tree",
            },
            {
                "name": "Lan",
                "kind": "private-wan",
                "network": "metro",
                "service": "e-lan",
            },
        ],
        "links": [
            {
                "a": {"device": "dal-core-01", "interface": "Te1/0/1"},
                "b": {"device": "dal-wan-01", "interface": "Te0/0/1"},
                "speed_mbps": 10000,
            },
            *(
                {
                    "a": {
                        "device": "dal-core-01",
                        "interface": f"Hu1/0/{i}",
                        "lag": "Port-channel1",
                    },
                    "b": {
                        "device": "dal-core-02",
                        "interface": f"Hu1/0/{i}",
                        "lag": "Port-channel1",
                    },
                    "speed_mbps": 100000,
                    "enterprise_cid": f"DAL-C000{i}",
                }
                for i in (1, 2)
            ),
            _circuit("dal-wan-01", "Gi0/0/1", "Tree", "T-1", role="root"),
            _circuit("a-wan-01", "Gi0/0/1", "Tree", "T-2"),
            _circuit("b-wan-01", "Gi0/0/1", "Tree", "T-3"),
            _circuit("dal-wan-01", "Gi0/0/2", "Lan", "L-1"),
            _circuit("b-wan-01", "Gi0/0/2", "Lan", "L-2"),
            _circuit("c-wan-01", "Gi0/0/2", "Lan", "L-3"),
            {
                "a": {"device": "dal-wan-01", "interface": "Te0/1/0"},
                "b": {"device": "c-wan-01", "interface": "Te0/1/0"},
                "speed_mbps": 10000,
                "kind": "wan",
                "circuit": {
                    "provider": "Metro Co",
                    "circuit_id": "E-1",
                    "service": "e-line",
                    "technology": "VPWS",
                },
                "carries": [{"network": "metro"}],
                # The carrier passes nothing of ours, but LLDP and CDP run
                # inside the MACsec on it.
                "neighbors": "far-end",
            },
        ],
        "tunnels": [
            {
                "name": "SEC-1",
                "network": "corp",
                "rides": "metro",
                "kind": "macsec",
                "neighbors": "inside",
                "a": {"device": "dal-wan-01", "interface": "Te0/1/0"},
                "b": {"device": "c-wan-01", "interface": "Te0/1/0"},
            },
            {
                "name": "GRE-1",
                "network": "corp",
                "rides": "metro",
                "technology": "GRE",
                "a": {"device": "dal-wan-01", "interface": "Tunnel1", "source": "Lo0"},
                "b": {"device": "a-wan-01", "interface": "Tunnel1", "source": "Lo0"},
            },
        ],
        "lags": [
            {
                "a": {"device": "dal-core-01", "interface": "Port-channel1"},
                "b": {"device": "dal-core-02", "interface": "Port-channel1"},
                "enterprise_cid": "DAL-PO01",
            }
        ],
    }


@pytest.fixture(scope="module")
def metro() -> Topology:
    return Topology.model_validate(metro_data())


def at(topology: Topology, device: str, interface: str) -> Link:
    return next(
        ln
        for ln in topology.links
        if (ln.a.device, ln.a.interface) == (device, interface)
    )


class TestModel:
    def test_an_e_tree_s_circuits_are_roots_or_leaves(self, metro: Topology) -> None:
        root = at(metro, "dal-wan-01", "Gi0/0/1")
        leaf = at(metro, "a-wan-01", "Gi0/0/1")
        other = at(metro, "b-wan-01", "Gi0/0/1")
        transports = {t.name: t for t in metro.transports}
        assert sees_across(root, leaf, transports)
        assert not sees_across(leaf, other, transports)
        # On an E-LAN, every pair.
        lan = at(metro, "b-wan-01", "Gi0/0/2")
        assert sees_across(lan, at(metro, "c-wan-01", "Gi0/0/2"), transports)

    def test_a_leaf_reaches_its_own_corner_and_only_the_roots_reach_it(
        self, metro: Topology
    ) -> None:
        hops = transport_hops(metro.links, metro.transports)
        root, leaf = (
            at(metro, "dal-wan-01", "Gi0/0/1"),
            at(metro, "a-wan-01", "Gi0/0/1"),
        )
        corner = f"transport:Tree~{leaf.id}"
        assert hops[leaf.id] == [("a-wan-01", corner)]
        assert ("dal-wan-01", corner) in hops[root.id]
        assert ("dal-wan-01", "transport:Tree") in hops[root.id]
        assert hops[at(metro, "c-wan-01", "Gi0/0/2").id] == [
            ("c-wan-01", "transport:Lan")
        ]

    def test_a_port_channel_has_its_members_and_a_cid_of_its_own(
        self, metro: Topology
    ) -> None:
        [lag] = metro.lags
        assert lag.id == "dal-core-01:Port-channel1--dal-core-02:Port-channel1"
        members = lag_members(lag, metro.links)
        assert [m.enterprise_cid.a for m in members if m.enterprise_cid] == [
            "DAL-C0001",
            "DAL-C0002",
        ]
        assert lag.enterprise_cid and lag.enterprise_cid.a == "DAL-PO01"

    def test_one_member_is_still_a_port_channel(self) -> None:
        data = metro_data()
        data["links"] = [
            ln for ln in data["links"] if ln["a"]["interface"] != "Hu1/0/2"
        ]
        topology = Topology.model_validate(data)
        assert len(lag_members(topology.lags[0], topology.links)) == 1

    def test_neighbors_read_one_value_or_several(self, metro: Topology) -> None:
        assert at(metro, "dal-wan-01", "Te0/1/0").neighbors == ["far-end"]
        data = metro_data()
        data["links"][-1]["neighbors"] = ["provider", "far-end"]
        assert Topology.model_validate(data).links[-1].neighbors == [
            "provider",
            "far-end",
        ]


def _set(path: list, value: object) -> Callable[[dict], None]:
    def change(data: dict) -> None:
        here = data
        for key in path[:-1]:
            here = here[key]
        here[path[-1]] = value

    return change


def _no_root(data: dict) -> None:
    data["links"][3]["b"].pop("role")


def _leaf_to_leaf(data: dict) -> None:
    data["tunnels"].append(
        {
            "name": "SEC-9",
            "network": "corp",
            "rides": "metro",
            "kind": "macsec",
            "a": {"device": "a-wan-01", "interface": "Gi0/0/1"},
            "b": {"device": "b-wan-01", "interface": "Gi0/0/1"},
        }
    )


def _across_two_services(data: dict) -> None:
    data["tunnels"].append(
        {
            "name": "SEC-9",
            "network": "corp",
            "rides": "metro",
            "kind": "macsec",
            "a": {"device": "dal-wan-01", "interface": "Gi0/0/1"},
            "b": {"device": "c-wan-01", "interface": "Gi0/0/2"},
        }
    )


def _twice(data: dict) -> None:
    again = copy.deepcopy(data["tunnels"][0])
    again["name"] = "SEC-9"
    again["a"], again["b"] = again["b"], again["a"]
    data["tunnels"].append(again)


def _lag_elsewhere(data: dict) -> None:
    data["links"][2]["b"]["lag"] = "Port-channel2"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (_no_root, "'Tree' is an E-Tree with no root"),
        (
            _set(["links", 6, "b", "role"], "root"),
            "is a root, but 'Lan' is not an E-Tree",
        ),
        (
            _set(["transports", 1, "service"], None),
            "a routed transport's far end is the provider's network",
        ),
        (
            _set(["links", 6, "circuit", "service"], "e-line"),
            "is an E-Line, which is point to point",
        ),
        (
            _set(["links", 9, "neighbors"], ["nothing", "far-end"]),
            "and something besides",
        ),
        (_set(["links", 9, "neighbors"], ["far-end", "far-end"]), "names neighbors"),
        (_set(["tunnels", 0, "a", "interface"], "Te0/1/9"), "which no link uses"),
        (_set(["tunnels", 0, "a", "source"], "Lo0"), "it has no source"),
        (_leaf_to_leaf, "between two leaves of 'Tree'"),
        (_across_two_services, "neither one link nor one layer-2 transport"),
        (_twice, "is listed 2 times"),
        (_set(["tunnels", 1, "a", "interface"], "Te0/1/0"), "which is cabled"),
        (_lag_elsewhere, "whose far end is not in dal-core-02:Port-channel1"),
        (
            _set(["lags", 0, "a", "interface"], "Port-channel7"),
            "has no member links",
        ),
        (_set(["tunnels", 1, "neighbors"], "inside"), "which only MACsec does"),
    ],
)
def test_what_does_not_fit_is_rejected(
    change: Callable[[dict], None], message: str
) -> None:
    data = metro_data()
    change(data)
    with pytest.raises(ValidationError, match=message):
        Topology.model_validate(data)


class TestReach:
    def test_leaves_reach_each_other_only_through_a_root(self, metro: Topology) -> None:
        network = Network(metro)
        reach = network.reach(Failures())
        assert {"a-wan-01", "b-wan-01", "c-wan-01"} <= reach.reached
        # The root's router is named as the one device a leaf depends on;
        # the E-Tree itself never is.
        assert reach.fragile["a-wan-01"][-1] == "dal-wan-01"
        # With the root's circuit down, A is cut off, though B, another leaf,
        # is still reached over the E-LAN: leaves do not reach each other.
        root = at(metro, "dal-wan-01", "Gi0/0/1")
        impact = network.impact(Failures(links=frozenset([root.id])))
        assert impact.cut_off == ["a-wan-01"]

    def test_a_leaf_with_no_root_reached_is_offline_in_its_network(
        self, metro: Topology
    ) -> None:
        root = at(metro, "dal-wan-01", "Gi0/0/1")
        report = Statuses(metro).of(AT, set(), {root.id}, [])
        metro_status = next(n for n in report.networks if n.network == "metro")
        offline = {g.id for g in metro_status.groups if g.status == "offline"}
        assert "A" in offline
        assert "B" not in offline

    def test_macsec_is_up_while_the_links_it_is_on_are(self, metro: Topology) -> None:
        layers = Layers(metro)
        eline = at(metro, "dal-wan-01", "Te0/1/0")
        assert layers.tunnels_up(set(), set())["SEC-1"]
        assert not layers.tunnels_up(set(), {eline.id})["SEC-1"]
        assert not layers.tunnels_up({"c-wan-01"}, set())["SEC-1"]

    def test_macsec_across_a_layer_2_service_rides_both_circuits(self) -> None:
        data = metro_data()
        data["tunnels"].append(
            {
                "name": "SEC-2",
                "network": "corp",
                "rides": "metro",
                "kind": "macsec",
                "a": {"device": "dal-wan-01", "interface": "Gi0/0/2"},
                "b": {"device": "b-wan-01", "interface": "Gi0/0/2"},
            }
        )
        topology = Topology.model_validate(data)
        layers = Layers(topology)
        far = at(topology, "b-wan-01", "Gi0/0/2")
        assert layers.secured["SEC-2"] == (
            at(topology, "dal-wan-01", "Gi0/0/2").id,
            far.id,
        )
        assert not layers.tunnels_up(set(), {far.id})["SEC-2"]


def row(
    interface: str,
    remote: str,
    port: str,
    protocol: str = "cdp",
    **more: object,
) -> Neighbor:
    return Neighbor.model_validate(
        {
            "interface": interface,
            "remote": remote,
            "remote_port": port,
            "protocol": protocol,
            "capabilities": ["router"],
            **more,
        }
    )


def run(found: dict[str, list[Neighbor]]) -> Discovery:
    return Discovery(
        source="test",
        at=AT,
        tables=[NeighborTable(device=d, neighbors=n) for d, n in found.items()],
    )


def up(topology: Topology) -> Visibility:
    return Visibility.of(AllUp(topology).snapshot(AT))


class TestDiscovery:
    def test_one_device_over_cdp_and_lldp_is_one_neighbor(self) -> None:
        data = metro_data()
        data["devices"][1]["mgmt_ip"] = "10.1.0.2"
        topology = Topology.model_validate(data)
        found = run(
            {
                "dal-core-01": [
                    # NX-OS: the serial after the name over CDP; over LLDP,
                    # the name with a domain, or no system name at all.
                    row("Hu1/0/1", "dal-core-02(FDO21120U8N)", "HundredGigE1/0/1"),
                    row("Hu1/0/1", "dal-core-02.net.example", "Hu1/0/1", "lldp"),
                    row("Hu1/0/2", "dal-core-02(FDO21120U8N)", "HundredGigE1/0/2"),
                    row(
                        "Hu1/0/2",
                        "00a6.ca12.3456",
                        "Hu1/0/2",
                        "lldp",
                        chassis_id="00a6.ca12.3456",
                    ),
                ],
                "dal-core-02": [
                    # Found by its management address alone.
                    row(
                        "Hu1/0/1",
                        "00a6.ca12.9999",
                        "Hu1/0/1",
                        "lldp",
                        chassis_id="00a6.ca12.9999",
                        mgmt_address="10.1.0.2",
                    ),
                ],
            }
        )
        c = compare(topology, found, up(topology))
        members = [at(topology, "dal-core-01", f"Hu1/0/{i}").id for i in (1, 2)]
        assert all(m not in c.links for m in members)
        assert not [f for f in c.findings if f.kind == "unknown-device"]

    def test_two_names_on_one_port_are_two_neighbors(self, metro: Topology) -> None:
        found = run(
            {
                "dal-core-01": [
                    row("Hu1/0/1", "dal-core-02", "Hu1/0/1"),
                    row("Hu1/0/1", "lab-sw-9", "Gi0/1", "lldp"),
                ]
            }
        )
        c = compare(metro, found, up(metro))
        member = at(metro, "dal-core-01", "Hu1/0/1")
        assert [f.kind for f in c.findings if f.link == member.id] == ["wrong-neighbor"]

    def test_a_port_sees_several_of_ours_across_an_e_lan(self, metro: Topology) -> None:
        found = run(
            {
                "dal-wan-01": [
                    row("Gi0/0/2", "b-wan-01", "Gi0/0/2"),
                    row("Gi0/0/2", "c-wan-01", "Gi0/0/2"),
                    row("Gi0/0/1", "a-wan-01", "Gi0/0/1"),
                    row("Gi0/0/1", "b-wan-01", "Gi0/0/1"),
                ],
                "b-wan-01": [row("Gi0/0/2", "c-wan-01", "Gi0/0/2")],
            }
        )
        c = compare(metro, found, up(metro))
        for near, port in [
            ("dal-wan-01", "Gi0/0/2"),
            ("b-wan-01", "Gi0/0/2"),
            ("c-wan-01", "Gi0/0/2"),
            ("dal-wan-01", "Gi0/0/1"),
            ("a-wan-01", "Gi0/0/1"),
            ("b-wan-01", "Gi0/0/1"),
        ]:
            assert at(metro, near, port).id not in c.links
        transports = {"transport:Tree", "transport:Lan"}
        assert not [
            f for f in c.findings if f.link and f.link.split("--")[1] in transports
        ]

    def test_two_leaves_that_see_each_other_are_one_finding(
        self, metro: Topology
    ) -> None:
        found = run(
            {
                "a-wan-01": [
                    row("Gi0/0/1", "dal-wan-01", "Gi0/0/1"),
                    row("Gi0/0/1", "b-wan-01", "Gi0/0/1"),
                ],
                "b-wan-01": [row("Gi0/0/1", "a-wan-01", "Gi0/0/1")],
            }
        )
        c = compare(metro, found, up(metro))
        [leak] = [f for f in c.findings if f.kind == "leaf"]
        assert leak.title == "a-wan-01 sees b-wan-01 across Tree"
        assert "whose leaves reach only its roots" in leak.detail
        assert leak.fix is None
        assert c.links[at(metro, "a-wan-01", "Gi0/0/1").id] == "mismatch"

    def test_macsec_is_vouched_for_only_where_lldp_and_cdp_run_inside_it(
        self, metro: Topology
    ) -> None:
        found = run({"dal-wan-01": [row("Te0/1/0", "c-wan-01", "Te0/1/0")]})
        c = compare(metro, found, up(metro))
        assert at(metro, "dal-wan-01", "Te0/1/0").id not in c.links
        assert c.tunnels["SEC-1"] == "confirmed"
        # Not seen inside it, while up: its circuit's finding.
        quiet = compare(metro, run({"dal-wan-01": []}), up(metro))
        assert quiet.tunnels["SEC-1"] == "not-seen"
        # Alongside it, in clear, the far end proves the circuit, not the
        # encryption; and not said, discovery cannot tell either.
        for shown in ("alongside", "none", None):
            data = metro_data()
            data["tunnels"][0]["neighbors"] = shown
            beside = Topology.model_validate(data)
            assert compare(beside, found, up(beside)).tunnels["SEC-1"] == "not-inside"

    def test_the_link_says_what_its_port_shows_with_macsec_or_without(self) -> None:
        # The NTU answers LLDP in clear beside MACsec, and the far end is
        # seen too: documented as showing nothing, it is a finding.
        data = metro_data()
        data["links"][-1]["neighbors"] = "nothing"
        data["tunnels"][0]["neighbors"] = "alongside"
        topology = Topology.model_validate(data)
        found = run(
            {
                "dal-wan-01": [
                    row("Te0/1/0", "metro-ntu-1a", "LAN1", "lldp"),
                    row("Te0/1/0", "c-wan-01", "Te0/1/0"),
                ]
            }
        )
        link = at(topology, "dal-wan-01", "Te0/1/0")
        c = compare(topology, found, up(topology))
        [finding] = [f for f in c.findings if f.link == link.id]
        assert finding.title.endswith("shows the provider's equipment and the far end")
        assert finding.fix and finding.fix.after
        assert finding.fix.after.neighbors == ["provider", "far-end"]

    def test_cdp_over_a_tunnel_is_compared_where_it_runs(self, metro: Topology) -> None:
        confirmed = run({"dal-wan-01": [row("Tunnel1", "a-wan-01", "Tunnel1")]})
        c = compare(metro, confirmed, up(metro))
        assert c.tunnels["GRE-1"] == "confirmed"
        assert not [f for f in c.findings if f.tunnel]
        # Where CDP does not run over it, nothing is a finding.
        quiet = compare(metro, run({"dal-wan-01": [], "a-wan-01": []}), up(metro))
        assert quiet.tunnels["GRE-1"] == "quiet"
        assert not [f for f in quiet.findings if f.tunnel]
        moved = run({"dal-wan-01": [row("Tunnel1", "a-wan-01", "Tunnel11")]})
        [finding] = [f for f in compare(metro, moved, up(metro)).findings if f.tunnel]
        assert finding.kind == "wrong-port"
        assert finding.title == "GRE-1 on another tunnel interface"
        assert finding.detail == (
            "Documented to a-wan-01 Tunnel1; dal-wan-01 Tunnel1 sees a-wan-01 "
            "Tunnel11 over CDP"
        )
        assert finding.fix is None

    def test_a_port_showing_two_kinds_is_checked_for_both(self) -> None:
        data = metro_data()
        eline = data["links"][-1]
        eline["neighbors"] = ["provider", "far-end"]
        data["tunnels"] = data["tunnels"][1:]
        topology = Topology.model_validate(data)
        link = at(topology, "dal-wan-01", "Te0/1/0")
        both = run(
            {
                "dal-wan-01": [
                    row("Te0/1/0", "metro-ntu-1a", "LAN1", "lldp"),
                    row("Te0/1/0", "c-wan-01", "Te0/1/0"),
                ]
            }
        )
        assert link.id not in compare(topology, both, up(topology)).links
        # An NTU that sends no system name is not taken for our far end.
        unnamed = run(
            {
                "dal-wan-01": [
                    row(
                        "Te0/1/0",
                        "00a6.0000.0001",
                        "LAN1",
                        "lldp",
                        chassis_id="00a6.0000.0001",
                    ),
                    row("Te0/1/0", "c-wan-01", "Te0/1/0"),
                ]
            }
        )
        assert link.id not in compare(topology, unnamed, up(topology)).links
        only = run({"dal-wan-01": [row("Te0/1/0", "metro-ntu-1a", "LAN1", "lldp")]})
        c = compare(topology, only, up(topology))
        [finding] = [f for f in c.findings if f.link == link.id]
        assert finding.title.endswith("shows the provider's equipment")
        assert "documented as showing the provider's equipment and the far end" in (
            finding.detail
        )
        assert finding.fix and finding.fix.after
        assert finding.fix.after.neighbors == ["provider"]


@pytest.fixture(scope="module")
def sample() -> Topology:
    return load_topology(LAYERS)


class TestSample:
    def test_it_has_carrier_ethernet_macsec_and_port_channels(
        self, sample: Topology
    ) -> None:
        services = {t.name: t.service for t in sample.transports if t.service}
        assert services == {"Mesa E-LAN": "e-lan", "Harbor E-Tree": "e-tree"}
        macsec = sorted(t.name for t in sample.tunnels if t.kind == "macsec")
        assert macsec == [
            "DCI-MACSEC-1",
            "DCI-MACSEC-2",
            "MACSEC-AUS-SAT",
            "MACSEC-DAL-AUS",
            "MACSEC-DAL-FTW",
            "MACSEC-DAL-SAT",
        ]
        assert sorted(
            lag.enterprise_cid.a for lag in sample.lags if lag.enterprise_cid
        ) == [
            "AUS-SAT-PO01",
            "DAL-IAD-PO01",
        ]

    def test_discovery_finds_the_drift_across_layer_2(self, sample: Topology) -> None:
        watched = set(monitored(sample))
        cabling = Cabling(cabled(sample), watched=watched)
        beyond = Beyond(sample, watched=watched)
        state = SimulatedState(sample, cabling=cabling)
        source = SimulatedDiscovery(sample, cabling, state, beyond)
        seen = visibility(state, AT)
        c = compare(sample, source.discover(AT, seen), seen)
        assert beyond.leaked
        leaks = [f for f in c.findings if f.kind == "leaf"]
        assert [sorted(f.devices) for f in leaks] == [
            sorted(ln.a.device for ln in beyond.leaked)
        ]
        moved = [f for f in c.findings if f.tunnel]
        assert [f.kind for f in moved] == ["wrong-port"]
        assert sum(v == "confirmed" for v in c.tunnels.values()) >= 6
        # Nexus cores report each neighbor over CDP and LLDP: still one each.
        # The only neighbors not in the topology are IP phones that say they
        # are a bridge too.
        unknown = [f for f in c.findings if f.kind == "unknown-device"]
        assert all("IP Phone" in (f.detail or "") for f in unknown)


def test_samples_are_written_as_they_read(tmp_path: Path) -> None:
    sample = load_topology(LAYERS)
    text = to_yaml(sample, "test")
    data = yaml.safe_load(text)
    assert all("id" not in lag for lag in data["lags"])
    shown = [ln["neighbors"] for ln in data["links"] if "neighbors" in ln]
    assert "provider" in shown
    assert ["provider", "far-end"] in shown
    path = tmp_path / "again.yaml"
    path.write_text(text)
    assert load_topology(path) == sample


def test_retiring_a_channel_s_last_member_retires_the_channel(
    metro: Topology,
) -> None:
    members = lag_members(metro.lags[0], metro.links)
    fixes = [Fix(kind="retire", summary="Retire it", before=m) for m in members]
    assert applied(metro, fixes[:1]).lags == metro.lags
    assert applied(metro, fixes).lags == []


def test_a_circuit_seen_only_from_the_far_end_is_checked_on_what_was_seen() -> None:
    # Only the far end answers: the NTU on our port could only show in our
    # own table, so its absence is no finding.
    data = metro_data()
    data["links"][6]["neighbors"] = ["provider", "far-end"]
    topology = Topology.model_validate(data)
    found = run({"b-wan-01": [row("Gi0/0/2", "dal-wan-01", "Gi0/0/2")]})
    c = compare(topology, found, up(topology))
    circuit = at(topology, "dal-wan-01", "Gi0/0/2")
    assert circuit.id not in c.links
    assert not [f for f in c.findings if f.link == circuit.id]
