from collections import Counter

import yaml

from sunstone.mockgen import PRESETS, generate, to_yaml
from sunstone.model import Topology


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
        sites = {site_of[link.a.device], site_of[link.b.device]}
        if sites != {"DAL", "IAD"}:
            hub_neighbors.update(sites - {"DAL", "IAD"})
    assert hub_neighbors == {"HOU": 2, "AUS": 2, "SAT": 2}


def test_yaml_round_trips() -> None:
    topology = generate(PRESETS["small"], seed=1)
    reloaded = yaml.safe_load(to_yaml(topology, "test"))
    assert Topology.model_validate(reloaded) == topology
