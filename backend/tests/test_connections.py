"""What carries each connection, what it is for at the edge, the IDs it goes
by, and what discovery makes of circuits and links beyond our devices."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError
from test_discovery import AllUp, changes_client

from sunstone.cabling import Beyond, Cabling
from sunstone.changes import applied
from sunstone.discovery import (
    Capability,
    Discovery,
    Neighbor,
    NeighborTable,
    SimulatedDiscovery,
    Visibility,
    compare,
)
from sunstone.layers import Layers
from sunstone.mockgen import to_yaml
from sunstone.mocklayers import generate_layers
from sunstone.model import (
    Link,
    Sides,
    Topology,
    cabled,
    cid,
    fabric_roles,
    joins,
    link_roles,
    shows,
    tunnel_roles,
)
from sunstone.problems import link_name

AT = datetime(2026, 11, 8, 15, 0, tzinfo=UTC)


def edge_topology(**changes: object) -> Topology:
    """Two sites, a switch, and a link of each kind: circuits into the
    Internet and a research network, one between the sites, a cable, and a
    tenant's encryptor."""
    raw: dict = {
        "sites": [
            {"code": "A", "name": "A", "lat": 30, "lon": -97},
            {"code": "B", "name": "B", "lat": 31, "lon": -96},
        ],
        "devices": [
            {"name": "a-wan-01", "site": "A", "role": "wan-edge"},
            {"name": "b-wan-01", "site": "B", "role": "wan-edge"},
            {"name": "a-acc-01", "site": "A", "role": "access"},
        ],
        "transports": [
            {"name": "INET", "kind": "internet", "network": "black"},
            {"name": "REN", "kind": "research", "network": "black"},
        ],
        "networks": [{"name": "black", "boundary": "outside"}],
        "tenants": [{"name": "T"}],
        "externals": [{"name": "enc-1", "kind": "tenant", "tenant": "T"}],
        "links": [
            {
                "a": {"device": "a-wan-01", "interface": "Gi0/0/0"},
                "b": {"transport": "INET"},
                "speed_mbps": 1000,
                "kind": "wan",
                "circuit": {"provider": "Northwind Fiber", "circuit_id": "NO-1"},
                "enterprise_cid": "A-INET-01",
                "edges": ["transit", "egress"],
                "neighbors": "provider",
            },
            {
                "a": {"device": "a-wan-01", "interface": "Te0/1/0"},
                "b": {"transport": "REN"},
                "speed_mbps": 10000,
                "kind": "wan",
                "circuit": {"provider": "Prairie", "circuit_id": "PR-1"},
                "edges": ["peering"],
                "neighbors": "provider",
            },
            {
                "a": {"device": "b-wan-01", "interface": "Te0/1/0"},
                "b": {"transport": "REN"},
                "speed_mbps": 10000,
                "kind": "wan",
                "circuit": {"provider": "Prairie", "circuit_id": "PR-2"},
                "edges": ["open"],
                "neighbors": "provider",
            },
            {
                "a": {"device": "a-wan-01", "interface": "Te0/1/1"},
                "b": {"device": "b-wan-01", "interface": "Te0/1/1"},
                "speed_mbps": 10000,
                "kind": "wan",
                "circuit": {"provider": "Mesa", "circuit_id": "ME-1"},
                "enterprise_cid": "A-B-01",
            },
            {
                "a": {"device": "a-wan-01", "interface": "Gi0/0/2"},
                "b": {"device": "a-acc-01", "interface": "Gi0/0/0"},
                "speed_mbps": 1000,
                "enterprise_cid": "A-C0001",
            },
            {
                "a": {"device": "b-wan-01", "interface": "Gi0/0/0"},
                "b": {"transport": "INET"},
                "speed_mbps": 1000,
                "kind": "wan",
                "circuit": {"provider": "Bluebonnet", "circuit_id": "BL-1"},
            },
            {
                "a": {"device": "a-acc-01", "interface": "Gi0/0/1"},
                "b": {"external": "enc-1", "interface": "ciphertext"},
                "speed_mbps": 1000,
                "neighbors": "nothing",
            },
        ],
    }
    raw.update(changes)
    return Topology.model_validate(raw)


@pytest.fixture(scope="module")
def topology() -> Topology:
    return edge_topology()


def link(topology: Topology, near: str, interface: str) -> Link:
    return next(
        ln
        for ln in topology.links
        if (ln.a.device, ln.a.interface) == (near, interface)
    )


def row(interface: str, remote: str, port: str, *caps: Capability) -> Neighbor:
    return Neighbor(
        interface=interface,
        remote=remote,
        remote_port=port,
        protocol="cdp",
        capabilities=list(caps),
    )


def as_documented() -> dict[str, list[Neighbor]]:
    """What each device reports when everything shows what it says."""
    return {
        "a-wan-01": [
            row("Gi0/0/0", "northwind-ntu-1", "LAN1", "switch"),
            row("Te0/1/0", "prairie-ntu-1", "LAN1", "switch"),
            row("Te0/1/1", "b-wan-01", "Te0/1/1", "router"),
            row("Gi0/0/2", "a-acc-01", "Gi0/0/0", "switch"),
        ],
        "b-wan-01": [
            row("Te0/1/0", "prairie-ntu-2", "LAN1", "switch"),
            row("Te0/1/1", "a-wan-01", "Te0/1/1", "router"),
        ],
        "a-acc-01": [row("Gi0/0/0", "a-wan-01", "Gi0/0/2", "router")],
    }


def run(found: dict[str, list[Neighbor]]) -> Discovery:
    return Discovery(
        source="test",
        at=AT,
        tables=[NeighborTable(device=d, neighbors=n) for d, n in found.items()],
    )


def up(topology: Topology) -> Visibility:
    return Visibility.of(AllUp(topology).snapshot(AT))


class TestIds:
    def test_one_value_is_both_sides_but_only_the_a_side_into_a_transport(
        self, topology: Topology
    ) -> None:
        inet = link(topology, "a-wan-01", "Gi0/0/0")
        assert inet.enterprise_cid == Sides(a="A-INET-01", z=None)
        assert inet.circuit and inet.circuit.circuit_id == Sides(a="NO-1", z=None)
        between = link(topology, "a-wan-01", "Te0/1/1")
        assert between.enterprise_cid == Sides(a="A-B-01", z="A-B-01")

    def test_the_z_side_is_its_own_or_blank_only_when_said(self) -> None:
        raw = edge_topology().model_dump(mode="json", exclude_computed_fields=True)
        cable = raw["links"][4]
        cable["enterprise_cid"] = {"a": "A-C0001"}
        circuit = raw["links"][3]
        circuit["enterprise_cid"] = {"a": "A-B-01", "z": "B-A-01"}
        circuit["circuit"]["circuit_id"] = {"a": "ME-1 / LEC 12/KXFU/1", "z": ""}
        topology = Topology.model_validate(raw)
        assert topology.links[4].enterprise_cid == Sides(a="A-C0001", z="A-C0001")
        assert topology.links[3].enterprise_cid == Sides(a="A-B-01", z="B-A-01")
        assert topology.links[3].circuit
        assert topology.links[3].circuit.circuit_id.z is None

    def test_written_out_and_read_back_they_are_the_same(
        self, topology: Topology
    ) -> None:
        text = to_yaml(topology, "test")
        assert "enterprise_cid: A-INET-01\n" in text
        import yaml

        again = Topology.model_validate(yaml.safe_load(text))
        assert again.links == topology.links

    def test_a_circuit_is_named_by_the_enterprise_cid_else_the_carriers(
        self, topology: Topology
    ) -> None:
        assert link_name(link(topology, "a-wan-01", "Te0/1/1")) == "Circuit A-B-01"
        unnamed = link(topology, "a-wan-01", "Te0/1/0")
        assert (cid(unnamed), link_name(unnamed)) == ("PR-1", "Circuit PR-1")
        cable = link(topology, "a-wan-01", "Gi0/0/2")
        assert (cid(cable), link_name(cable)) == ("A-C0001", "a-wan-01 – a-acc-01")


class TestRoles:
    def test_roles_are_as_documented_or_implied_by_the_far_end(
        self, topology: Topology
    ) -> None:
        externals = {e.name: e for e in topology.externals}

        def roles(near: str, interface: str) -> tuple[tuple[str, ...], str]:
            return tuple(link_roles(link(topology, near, interface), externals))

        assert roles("a-wan-01", "Gi0/0/0") == (("transit", "egress"), "declared")
        assert roles("a-wan-01", "Te0/1/1") == (("transit",), "implied")
        assert roles("a-wan-01", "Gi0/0/2") == ((), "implied")
        assert roles("a-acc-01", "Gi0/0/1") == (("access",), "implied")
        # Routing policy decides a circuit into a transport: TBD until said.
        assert roles("b-wan-01", "Gi0/0/0") == ((), "tbd")

    def test_tunnels_and_fabrics_between_our_devices_are_transit(self) -> None:
        layers = generate_layers(1)
        externals = {e.name: e for e in layers.externals}
        by_name = {t.name: t for t in layers.tunnels}
        assert tunnel_roles(by_name["DCI-1"], externals).edges == ("transit",)
        assert tunnel_roles(by_name["Acme VPN"], externals).edges == ("interconnect",)
        assert fabric_roles(layers.fabrics[0]) == (("transit",), "implied")

    def test_what_a_port_shows_defaults_to_the_far_end_between_our_devices(
        self, topology: Topology
    ) -> None:
        assert shows(link(topology, "a-wan-01", "Te0/1/1")) == "far-end"
        assert shows(link(topology, "b-wan-01", "Gi0/0/0")) is None
        assert shows(link(topology, "a-acc-01", "Gi0/0/1")) == "nothing"

    def test_a_transport_joins_only_circuits_for_transit_or_tbd(
        self, topology: Topology
    ) -> None:
        def far(near: str, interface: str) -> str:
            ln = link(topology, near, interface)
            return next(
                e.b for e in Layers(topology).link_edges("black") if e.id == ln.id
            )

        assert joins(link(topology, "a-wan-01", "Gi0/0/0"))
        assert far("a-wan-01", "Gi0/0/0") == "transport:INET"
        # TBD: as before roles were documented.
        assert far("b-wan-01", "Gi0/0/0") == "transport:INET"
        # Peering and open circuits reach the research network, but carry
        # nothing of ours between our sites across it.
        assert not joins(link(topology, "a-wan-01", "Te0/1/0"))
        assert far("a-wan-01", "Te0/1/0").startswith("transport:REN~")
        assert far("a-wan-01", "Te0/1/0") != far("b-wan-01", "Te0/1/0")

    @pytest.mark.parametrize(
        ("index", "change", "message"),
        [
            (0, {"neighbors": "far-end"}, "say provider or nothing"),
            (4, {"neighbors": "provider"}, "but has no circuit"),
            (0, {"edges": ["egress", "egress"]}, "names edge 'egress' twice"),
        ],
    )
    def test_what_cannot_be_is_refused(
        self, index: int, change: dict, message: str
    ) -> None:
        raw = edge_topology().model_dump(mode="json", exclude_computed_fields=True)
        raw["links"][index].update(change)
        with pytest.raises(ValidationError, match=message):
            Topology.model_validate(raw)


class TestDiscoveryAcrossCircuits:
    def test_everything_showing_what_it_says_has_no_findings(
        self, topology: Topology
    ) -> None:
        result = compare(topology, run(as_documented()), up(topology))
        assert result.findings == []
        checks = {
            ln.a.device + " " + ln.a.interface: result.links.get(ln.id, "confirmed")
            for ln in topology.links
        }
        assert checks == {
            "a-wan-01 Gi0/0/0": "provider",
            "a-wan-01 Te0/1/0": "provider",
            "b-wan-01 Te0/1/0": "provider",
            "a-wan-01 Te0/1/1": "confirmed",
            "a-wan-01 Gi0/0/2": "confirmed",
            "b-wan-01 Gi0/0/0": "unstated",
            "a-acc-01 Gi0/0/1": "nothing",
        }

    def test_our_devices_seeing_each_other_across_peering_cross_the_boundary(
        self, topology: Topology
    ) -> None:
        found = as_documented()
        found["a-wan-01"][1] = row("Te0/1/0", "b-wan-01", "Te0/1/0", "router")
        found["b-wan-01"][0] = row("Te0/1/0", "a-wan-01", "Te0/1/0", "router")
        result = compare(topology, run(found), up(topology))
        assert [(f.kind, f.title) for f in result.findings] == [
            ("boundary", "a-wan-01 sees b-wan-01 across REN"),
            ("boundary", "b-wan-01 sees a-wan-01 across REN"),
        ]
        assert "Circuit PR-1 is a peering edge" in result.findings[0].detail
        assert all(f.fix is None for f in result.findings)
        # Drawn once, not once for each end.
        assert len(result.seen) == 1

    def test_our_device_on_a_transit_or_tbd_circuit_is_only_on_the_wrong_port(
        self, topology: Topology
    ) -> None:
        found = as_documented()
        found["a-wan-01"][0] = row("Gi0/0/0", "a-acc-01", "Gi0/0/9", "switch")
        found["b-wan-01"].append(row("Gi0/0/0", "a-acc-01", "Gi0/0/8", "switch"))
        result = compare(topology, run(found), up(topology))
        assert {f.kind for f in result.findings} == {"wrong-neighbor"}

    def test_a_circuit_up_yet_showing_nothing_offers_to_document_it(
        self, topology: Topology
    ) -> None:
        found = as_documented()
        found["a-wan-01"] = [n for n in found["a-wan-01"] if n.interface != "Te0/1/1"]
        found["b-wan-01"] = [n for n in found["b-wan-01"] if n.interface != "Te0/1/1"]
        result = compare(topology, run(found), up(topology))
        [finding] = result.findings
        assert (finding.kind, finding.title) == (
            "shows",
            "Circuit A-B-01 shows nothing",
        )
        assert "documented as showing the far end" in finding.detail
        assert finding.fix and finding.fix.kind == "document"
        fixed = applied(topology, [finding.fix])
        assert link(fixed, "a-wan-01", "Te0/1/1").neighbors == "nothing"
        again = compare(fixed, run(found), up(fixed))
        assert again.findings == []
        assert again.links[finding.link or ""] == "nothing"

    def test_a_circuit_that_does_not_say_is_offered_what_it_shows(
        self, topology: Topology
    ) -> None:
        found = as_documented()
        found["b-wan-01"].append(row("Gi0/0/0", "bluebonnet-ntu-1", "LAN1", "switch"))
        found["a-wan-01"] = [n for n in found["a-wan-01"] if n.interface != "Gi0/0/0"]
        result = compare(topology, run(found), up(topology))
        by_link = {f.link: f for f in result.findings}
        unsaid = by_link[link(topology, "b-wan-01", "Gi0/0/0").id]
        assert unsaid.title == "Circuit BL-1 shows the provider's equipment"
        assert unsaid.detail.endswith("it does not say what it shows")
        assert unsaid.fix and unsaid.fix.after
        assert unsaid.fix.after.neighbors == "provider"
        missing = by_link[link(topology, "a-wan-01", "Gi0/0/0").id]
        assert missing.title == "Circuit A-INET-01 shows nothing"
        assert result.links[unsaid.link or ""] == "differs"

    def test_phones_and_printers_are_endpoints_a_switch_is_a_finding(
        self, topology: Topology
    ) -> None:
        found = as_documented()
        found["a-acc-01"] += [
            row("Gi1/0/10", "SEP0040ABCD1234", "Port 1", "phone"),
            row("Gi1/0/11", "prn-1", "Port 1", "host"),
            row("Gi1/0/12", "lab-sw-01", "Gi0/1", "switch"),
        ]
        result = compare(topology, run(found), up(topology))
        assert result.endpoints == {"a-acc-01": 2}
        assert [f.kind for f in result.findings] == ["unknown-device"]

    def test_our_device_across_an_access_edge_crosses_the_boundary(
        self, topology: Topology
    ) -> None:
        found = as_documented()
        found["a-acc-01"].append(row("Gi0/0/1", "b-wan-01", "Gi0/0/7", "router"))
        result = compare(topology, run(found), up(topology))
        [finding] = result.findings
        assert finding.kind == "boundary"
        assert "is an access edge" in finding.detail


class TestSimulated:
    def test_the_layered_sample_shows_drift_across_its_circuits(self) -> None:
        layers = generate_layers(1)
        everyone = {d.name for d in layers.devices}
        beyond = Beyond(layers, watched=everyone)
        assert beyond.bridged
        assert {ln.a.device for ln in beyond.bridged} == {"dal-wan-01", "iad-wan-01"}
        assert beyond.filtered and beyond.real[beyond.filtered] == "nothing"
        assert beyond.unsaid and beyond.real[beyond.unsaid] == "provider"
        cabling = Cabling(cabled(layers))
        discovery = SimulatedDiscovery(layers, cabling, AllUp(layers), beyond)
        result = compare(layers, discovery.discover(AT), up(layers))
        kinds = [f.kind for f in result.findings]
        assert kinds[:2] == ["boundary", "boundary"]
        titles = {f.title for f in result.findings if f.kind == "shows"}
        assert "Circuit TPA-INET-01 shows the provider's equipment" in titles
        assert sum(result.endpoints.values()) > 0
        assert result.links.get(beyond.filtered) == "not-seen"

    def test_without_drift_it_is_exactly_as_documented(self) -> None:
        layers = generate_layers(1)
        beyond = Beyond(layers)
        assert (beyond.filtered, beyond.unsaid, beyond.bridged) == (None, None, None)
        assert beyond.endpoints == []


def test_documenting_what_a_circuit_shows_is_reviewed_and_accepted(
    tmp_path: Path,
) -> None:
    topology = edge_topology()
    client = changes_client(topology, tmp_path)
    shown = {
        f["title"]: f
        for f in client.get("/api/discovery").json()["findings"]
        if f["kind"] == "shows"
    }
    finding = shown["Circuit A-B-01 shows nothing"]
    review = client.get("/api/review", params={"finding": finding["id"]}).json()
    assert (review["removes"], review["adds"]) == ([], [])
    assert [p["device"] for p in review["involved"]] == ["a-wan-01", "b-wan-01"]
    accepted = client.post(
        "/api/changes",
        json={"finding": finding["id"], "by": "Pat", "note": "Mesa filters LLDP"},
    )
    assert accepted.status_code == 201
    links = client.get("/api/topology").json()["links"]
    circuit = next(ln for ln in links if ln["id"] == finding["link"])
    assert circuit["neighbors"] == "nothing"
    comparison = client.get("/api/discovery").json()
    assert finding["id"] not in {f["id"] for f in comparison["findings"]}
    assert comparison["links"][finding["link"]] == "nothing"
