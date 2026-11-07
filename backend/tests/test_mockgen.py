from collections import Counter

import yaml

from sunstone.impact import Failures, Network
from sunstone.mockgen import PRESETS, generate, to_yaml
from sunstone.mocklayers import generate_layers
from sunstone.model import Topology, TransportEnd, device_b


def test_small_preset_is_about_fifty_devices() -> None:
    topology = generate(PRESETS["small"], seed=1)
    assert len(topology.sites) == 5
    assert 40 <= len(topology.devices) <= 70


def test_large_preset_is_about_three_thousand_devices() -> None:
    topology = generate(PRESETS["large"], seed=1)
    assert len(topology.sites) == 63
    assert 2500 <= len(topology.devices) <= 3500


def test_same_seed_gives_same_topology() -> None:
    assert generate(PRESETS["small"], seed=7) == generate(PRESETS["small"], seed=7)


def test_every_branch_reaches_both_hubs() -> None:
    topology = generate(PRESETS["small"], seed=1)
    site_of = {d.name: d.site for d in topology.devices}
    hub_neighbors: Counter[str] = Counter()
    for link in topology.links:
        if link.kind != "wan":
            continue
        sites = {site_of[link.a.device], site_of[device_b(link).device]}
        if sites != {"DAL", "IAD"}:
            hub_neighbors.update(sites - {"DAL", "IAD"})
    assert hub_neighbors == {"HOU": 2, "AUS": 2, "SAT": 2}


def test_yaml_round_trips() -> None:
    topology = generate(PRESETS["small"], seed=1)
    reloaded = yaml.safe_load(to_yaml(topology, "test"))
    assert Topology.model_validate(reloaded) == topology


def test_the_large_preset_has_the_internet_and_a_dmvpn_fabric() -> None:
    topology = generate(PRESETS["large"], seed=1)
    into = [ln for ln in topology.links if ln.b == TransportEnd(transport="INET")]
    assert len(into) == len(topology.sites)
    [fabric] = topology.fabrics
    roles = Counter(m.role for m in fabric.members)
    assert roles == {"hub": 2, "spoke": len(topology.sites) - 2}


def test_the_layered_sample_has_each_example() -> None:
    topology = generate_layers(seed=1)
    reach = Network(topology).reach(Failures()).reached
    assert reach == {d.name for d in topology.devices}
    networks = {n.name for n in topology.networks}
    assert {"black", "blue", "blue2", "grey", "red-alpha", "red-bravo"} <= networks
    # Houston: four Internet circuits from three providers on two switches.
    houston = [
        ln
        for ln in topology.links
        if ln.a.device.startswith("hou-wsw") and isinstance(ln.b, TransportEnd)
    ]
    assert len(houston) == 4
    assert len({ln.circuit.provider for ln in houston if ln.circuit}) == 3
    # Grey rides blue, blue2, and black directly, tunnel by tunnel.
    assert {t.rides for t in topology.tunnels if t.network == "grey"} == {
        "blue",
        "blue2",
        "black",
    }
    # Tampa's trunk carries grey and black, in their VLANs.
    trunk = next(
        ln
        for ln in topology.links
        if ln.a.device == "tpa-wsw-01" and ln.a.interface == "GigabitEthernet0/0/2"
    )
    assert [(c.network, c.vlan) for c in trunk.carries] == [
        ("grey", 200),
        ("black", 30),
    ]
    # Two sites have both tenants' encryptors.
    sites_of = Counter(
        e.name.split("-")[1] for e in topology.externals if e.kind == "tenant"
    )
    assert sorted(s for s, n in sites_of.items() if n == 2) == ["atl", "tpa"]


def test_the_layered_sample_round_trips() -> None:
    topology = generate_layers(seed=1)
    reloaded = yaml.safe_load(to_yaml(topology, "test"))
    assert Topology.model_validate(reloaded) == topology
