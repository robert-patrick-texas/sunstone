from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from sunstone.api import create_app
from sunstone.loader import TopologyError, load_topology


def test_load_topology(topology_file: Path) -> None:
    assert [d.name for d in load_topology(topology_file).devices] == ["r1", "r2"]


def test_missing_file_names_the_path(tmp_path: Path) -> None:
    with pytest.raises(TopologyError, match="nope.yaml"):
        load_topology(tmp_path / "nope.yaml")


def test_bad_yaml_names_the_path(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("sites: [", encoding="utf-8")
    with pytest.raises(TopologyError, match="bad.yaml"):
        load_topology(path)


def test_invalid_topology_names_the_path_and_problem(
    tmp_path: Path, topology_data: dict
) -> None:
    topology_data["devices"][0]["site"] = "HOU"
    path = tmp_path / "invalid.yaml"
    path.write_text(yaml.safe_dump(topology_data), encoding="utf-8")
    with pytest.raises(TopologyError, match=r"(?s)invalid\.yaml.*unknown site 'HOU'"):
        load_topology(path)


def test_api_serves_topology(topology_file: Path) -> None:
    response = TestClient(create_app(topology_file)).get("/api/topology")
    assert response.status_code == 200
    body = response.json()
    assert [s["code"] for s in body["sites"]] == ["DAL"]
    assert body["links"][0]["id"] == "r1:Te1/0/1--r2:Te1/0/49"


def test_api_serves_web_dir(topology_file: Path, tmp_path: Path) -> None:
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<p>sunstone</p>", encoding="utf-8")
    client = TestClient(create_app(topology_file, web))
    assert client.get("/").text == "<p>sunstone</p>"
    assert client.get("/api/topology").status_code == 200
