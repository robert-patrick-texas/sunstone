"""Named networks, transports, external nodes, tunnels, and fabrics."""

import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from sunstone.api import create_app
from sunstone.impact import Failures, Network
from sunstone.model import Topology, cabled
from sunstone.problems import LiveView, find_problems
from sunstone.simulate import SimulatedState

NOW = datetime(2026, 11, 7, 15, 0, tzinfo=UTC)


@pytest.fixture
def layered() -> dict:
    """A hub and a branch on the Internet only, with a tunnel between them,
    a fabric, a partner, and a tenant's encryptor."""
    return {
        "sites": [
            {"code": "DAL", "name": "Dallas", "lat": 32.8, "lon": -96.8},
            {"code": "HOU", "name": "Houston", "lat": 29.8, "lon": -95.4},
        ],
        "devices": [
            {"name": "dal-core-01", "site": "DAL", "role": "core"},
            {"name": "dal-wan-01", "site": "DAL", "role": "wan-edge"},
            {"name": "hou-wan-01", "site": "HOU", "role": "wan-edge"},
            {"name": "hou-sw-01", "site": "HOU", "role": "access"},
        ],
        "links": [
            {
                "a": {"device": "dal-core-01", "interface": "Te1/0/1"},
                "b": {"device": "dal-wan-01", "interface": "Te0/0/1"},
                "speed_mbps": 10000,
            },
            {
                "a": {"device": "dal-wan-01", "interface": "Gi0/0/0"},
                "b": {"transport": "INET"},
                "speed_mbps": 1000,
                "kind": "wan",
                "circuit": {"provider": "Lone Star Fiber", "circuit_id": "LS-1"},
            },
            {
                "a": {"device": "hou-wan-01", "interface": "Gi0/0/0"},
                "b": {"transport": "INET"},
                "speed_mbps": 500,
                "kind": "wan",
                "circuit": {"provider": "Gulf Coast Net", "circuit_id": "GC-2"},
                "carries": [{"network": "black", "vlan": 30}],
            },
            {
                "a": {"device": "hou-wan-01", "interface": "Gi0/0/2"},
                "b": {"device": "hou-sw-01", "interface": "Gi1/0/1"},
                "speed_mbps": 1000,
                "carries": [
                    {"network": "grey", "vlan": 200, "b": {"vlan": 400}},
                ],
            },
            {
                "a": {"device": "hou-sw-01", "interface": "Gi1/0/2"},
                "b": {"external": "alpha-hou-1", "interface": "black"},
                "speed_mbps": 1000,
                "carries": [{"network": "grey", "vlan": 400}],
            },
            {
                "a": {"device": "dal-wan-01", "interface": "Gi0/0/1"},
                "b": {"transport": "INET"},
                "speed_mbps": 1000,
                "kind": "wan",
                "circuit": {"provider": "Gulf Coast Net", "circuit_id": "GC-3"},
            },
        ],
        "networks": [
            {"name": "black", "boundary": "outside"},
            {"name": "grey"},
            {"name": "red-alpha", "tenant": "Alpha", "rides": ["grey"]},
            {"name": "partners"},
        ],
        "transports": [{"name": "INET", "kind": "internet", "network": "black"}],
        "externals": [
            {
                "name": "alpha-hou-1",
                "kind": "tenant",
                "tenant": "Alpha",
                "network": "red-alpha",
                "platform": "TACLANE",
            },
            {"name": "Acme Logistics", "kind": "partner"},
            {"name": "Nimbus Cloud", "kind": "service", "reached_over": ["INET"]},
        ],
        "tenants": [{"name": "Alpha"}],
        "tunnels": [
            {
                "name": "GREY-DAL-HOU",
                "network": "grey",
                "rides": "black",
                "technology": "GRE+IPsec",
                "a": {
                    "device": "dal-wan-01",
                    "interface": "Tunnel20",
                    "source": "Gi0/0/0",
                },
                "b": {
                    "device": "hou-wan-01",
                    "interface": "Tunnel20",
                    "source": "Loopback0",
                },
            },
            {
                "name": "Acme VPN",
                "network": "partners",
                "rides": "black",
                "a": {"device": "dal-wan-01", "interface": "Tunnel50"},
                "b": {"external": "Acme Logistics", "peer": "198.51.100.7"},
            },
        ],
        "fabrics": [
            {
                "name": "DMVPN-INET",
                "network": "grey",
                "rides": "black",
                "shape": "hub-spoke-dynamic",
                "members": [
                    {"device": "dal-wan-01", "interface": "Tunnel100", "role": "hub"},
                    {"device": "hou-wan-01", "interface": "Tunnel100", "role": "spoke"},
                ],
            }
        ],
        "terms": {"tenant": "Customer"},
    }


def test_a_layered_topology_loads(layered: dict) -> None:
    topology = Topology.model_validate(layered)
    ids = [ln.id for ln in topology.links]
    assert "dal-wan-01:Gi0/0/0--transport:INET" in ids
    assert "external:alpha-hou-1:black--hou-sw-01:Gi1/0/2" in ids
    assert topology.terms == {"tenant": "Customer"}


def test_numbers_belong_to_each_end(layered: dict) -> None:
    grey = Topology.model_validate(layered).links[3].carries[0]
    assert (grey.vlan, grey.b and grey.b.vlan) == (200, 400)


def test_files_without_layers_still_load(topology_data: dict) -> None:
    topology = Topology.model_validate(topology_data)
    assert (topology.networks, topology.tunnels, topology.terms) == ([], [], {})


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (
            lambda d: d["links"][1]["b"].update(transport="MPLS"),
            "unknown transport 'MPLS'",
        ),
        (
            lambda d: d["links"][1].update(kind="lan"),
            "into a transport is not kind wan",
        ),
        (
            lambda d: d["links"][4]["b"].update(external="bravo-1"),
            "unknown external 'bravo-1'",
        ),
        (
            lambda d: d["links"][3]["carries"][0].update(network="gray"),
            "names unknown network 'gray'",
        ),
        (
            lambda d: d["links"][2]["carries"][0].update(network="grey"),
            "carries 'grey', not the transport's network",
        ),
        (lambda d: d["externals"][0].pop("tenant"), "a tenant's but names no tenant"),
        (lambda d: d["networks"][2].update(tenant="Bravo"), "unknown tenant 'Bravo'"),
        (lambda d: d["tunnels"][0].update(rides="grey"), "rides its own network"),
        (
            lambda d: d["tunnels"][0]["a"].update(interface="Gi0/0/0"),
            "uses dal-wan-01:Gi0/0/0, which is cabled",
        ),
        (
            lambda d: d["tunnels"][0]["b"].update(source="Gi0/0/2"),
            "leaves hou-wan-01:Gi0/0/2, which does not carry 'black'",
        ),
        (
            lambda d: d["fabrics"][0]["members"][0].update(interface="Tunnel20"),
            "tunnel interface dal-wan-01:Tunnel20 is used 2 times",
        ),
        (
            lambda d: d["fabrics"][0]["members"][0].update(role="spoke"),
            "at least one hub",
        ),
        (
            lambda d: d["fabrics"][0].update(shape="full-mesh"),
            "full-mesh: its members are peers",
        ),
        (
            lambda d: d["networks"][0].update(rides=["red-alpha"]),
            "network 'black' rides itself",
        ),
        (lambda d: d["networks"].append({"name": "grey"}), "duplicate network name"),
        (lambda d: d["terms"].update(customer="Tenant"), "terms"),
    ],
)
def test_invalid_layers_are_rejected(layered: dict, change, message) -> None:
    change(layered)
    with pytest.raises(ValidationError, match=message):
        Topology.model_validate(layered)


def test_cables_leave_out_circuits_into_transports(layered: dict) -> None:
    topology = Topology.model_validate(layered)
    assert [ln.id for ln in cabled(topology).links] == [
        topology.links[0].id,
        topology.links[3].id,
    ]
    plain = Topology.model_validate({**layered, "links": layered["links"][:1]})
    assert cabled(plain) is plain


def test_the_core_is_reached_across_a_transport(layered: dict) -> None:
    network = Network(Topology.model_validate(layered))
    assert network.reach(Failures()).reached == {
        "dal-core-01",
        "dal-wan-01",
        "hou-wan-01",
        "hou-sw-01",
    }
    # One Internet circuit each way: HOU hangs on the devices at either end
    # of them, but the Internet itself is never named as one it depends on.
    assert network.reach(Failures()).fragile["hou-sw-01"] == (
        "dal-core-01",
        "dal-wan-01",
        "hou-wan-01",
    )
    hou_circuit = Topology.model_validate(layered).links[2].id
    impact = network.impact(Failures(links=frozenset([hou_circuit])))
    assert impact.cut_off == ["hou-sw-01", "hou-wan-01"]


def test_circuits_into_transports_are_monitored_and_reach_on(layered: dict) -> None:
    simulated = SimulatedState(Topology.model_validate(layered))
    # The branch is reached only across the Internet: if it were not, it
    # would never be up.
    up = 0
    for step in range(48):
        state = simulated.snapshot(NOW + timedelta(minutes=30 * step))
        if next(d for d in state.devices if d.device == "hou-wan-01").status == "up":
            up += 1
            readings = {(i.device, i.interface) for i in state.interfaces}
            assert ("hou-wan-01", "Gi0/0/0") in readings
    assert up > 0


def test_a_circuit_into_a_transport_down_is_a_problem(layered: dict) -> None:
    topology = Topology.model_validate(layered)
    network = Network(topology)
    hou_circuit = topology.links[2]
    state = SimulatedState(topology).snapshot(NOW)
    downed = state.model_copy(
        update={
            "interfaces": [
                i.model_copy(update={"oper": "down"})
                if (i.device, i.interface) == ("hou-wan-01", "Gi0/0/0")
                else i
                for i in state.interfaces
            ]
        }
    )
    problems = find_problems(network, LiveView(downed))
    cut = next(p for p in problems if p.kind == "outage")
    assert (cut.title, cut.target.model_dump()) == (
        "HOU cut off",
        {"kind": "site", "id": "HOU"},
    )
    assert cut.detail == "2 devices · 1 circuit GC-2 down"
    assert cut.impact is not None
    assert cut.impact.failed.links == [hou_circuit.id]


def test_the_api_serves_the_layered_sample(tmp_path: Path) -> None:
    sample = Path(__file__).parents[2] / "data" / "sample" / "layers.yaml"
    path = tmp_path / "layers.yaml"
    shutil.copy(sample, path)
    shutil.copy(sample.with_suffix(".oncall.yaml"), tmp_path / "layers.oncall.yaml")
    client = TestClient(create_app(path, warm=False))
    topology = client.get("/api/topology").json()
    assert all(topology[k] for k in ("transports", "tunnels", "fabrics", "networks"))
    for url in (
        "/api/state",
        "/api/problems",
        "/api/events",
        "/api/discovery",
        "/api/handover",
        "/api/ownership",
        "/api/oncall",
    ):
        assert client.get(url).status_code == 200, url
    owners = client.get("/api/ownership").json()["links"]
    assert owners["hou-wsw-01:GigabitEthernet0/0/0--transport:INET"] == "wan"
    circuit = "dal-wan-01:GigabitEthernet0/0/0--transport:INET"
    what_if = client.post(
        "/api/impact", json={"failures": [{"kind": "links", "ids": [circuit]}]}
    )
    # The hub's other circuit carries on.
    assert what_if.status_code == 200
    assert what_if.json()["impact"]["cut_off"] == []
