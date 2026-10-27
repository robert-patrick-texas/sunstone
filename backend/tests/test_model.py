import pytest
from pydantic import ValidationError

from sunstone.model import Link, Topology

SECOND_LINK_ON_R1_TE1 = {
    "a": {"device": "r1", "interface": "Te1/0/1"},
    "b": {"device": "r2", "interface": "Te1/0/50"},
    "speed_mbps": 10000,
}


def test_valid_topology_loads(topology_data: dict) -> None:
    topology = Topology.model_validate(topology_data)
    assert topology.links[0].kind == "lan"


def test_link_id_ignores_end_order() -> None:
    a = {"device": "r1", "interface": "Te1/0/1"}
    b = {"device": "r2", "interface": "Te1/0/49"}
    forward = Link.model_validate({"a": a, "b": b, "speed_mbps": 1})
    backward = Link.model_validate({"a": b, "b": a, "speed_mbps": 1})
    assert forward.id == backward.id == "r1:Te1/0/1--r2:Te1/0/49"


def test_link_id_is_serialized(topology_data: dict) -> None:
    dumped = Topology.model_validate(topology_data).model_dump()
    assert dumped["links"][0]["id"] == "r1:Te1/0/1--r2:Te1/0/49"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d["sites"].append(dict(d["sites"][0])), "duplicate site code"),
        (lambda d: d["devices"].append(dict(d["devices"][0])), "duplicate device"),
        (lambda d: d["devices"][0].update(site="HOU"), "unknown site 'HOU'"),
        (lambda d: d["links"][0]["b"].update(device="r9"), "unknown device 'r9'"),
        (lambda d: d["links"][0]["b"].update(device="r1"), "a device to itself"),
        (
            lambda d: d["links"].append(SECOND_LINK_ON_R1_TE1),
            "interface r1:Te1/0/1 is used by 2 links",
        ),
        (lambda d: d["devices"][0].update(rol="core"), "Extra inputs"),
        (lambda d: d["devices"][0].update(role="spine"), "role"),
    ],
)
def test_invalid_topology_is_rejected(topology_data: dict, change, message) -> None:
    change(topology_data)
    with pytest.raises(ValidationError, match=message):
        Topology.model_validate(topology_data)


def test_every_problem_is_reported(topology_data: dict) -> None:
    topology_data["devices"][0]["site"] = "HOU"
    topology_data["links"][0]["b"]["device"] = "r9"
    with pytest.raises(ValidationError) as excinfo:
        Topology.model_validate(topology_data)
    assert "unknown site 'HOU'" in str(excinfo.value)
    assert "unknown device 'r9'" in str(excinfo.value)
