import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from sunstone.api import Files, create_app
from sunstone.layouts import LayoutIn, LayoutStore, LayoutStoreError, LayoutStoreFull

LAYOUT = {
    "settings": {
        "scope": "path",
        "layout": "force",
        "grouped": True,
        "hops": 2,
        "path": {"from": "r1", "to": "r2"},
        "expanded": ["DAL"],
    },
    "positions": {"r1": {"x": 1.5, "y": -2}, "r2": {"x": 10, "y": 20}},
}


@pytest.fixture
def store(tmp_path: Path) -> LayoutStore:
    return LayoutStore(tmp_path / "layouts.json")


def layout() -> LayoutIn:
    return LayoutIn.model_validate(LAYOUT)


def test_store_round_trips_and_persists(store: LayoutStore) -> None:
    saved = store.put("Core view", layout())
    assert store.get("Core view") == saved
    assert LayoutStore(store.path).get("Core view") == saved
    assert saved.settings.path is not None
    assert saved.settings.path.start == "r1"


def test_file_keeps_the_browser_field_names(store: LayoutStore) -> None:
    store.put("Core view", layout())
    [stored] = json.loads(store.path.read_text(encoding="utf-8"))
    assert stored["settings"]["path"] == {"from": "r1", "to": "r2"}


def test_saving_a_name_again_replaces_it(store: LayoutStore) -> None:
    store.put("Core view", layout())
    store.put("Core view", layout())
    assert [s.name for s in store.summaries()] == ["Core view"]


def test_summaries_are_newest_first(store: LayoutStore) -> None:
    store.put("first", layout())
    store.put("second", layout())
    summaries = store.summaries()
    assert [s.name for s in summaries] == ["second", "first"]
    assert [s.nodes for s in summaries] == [2, 2]


def test_delete(store: LayoutStore) -> None:
    store.put("Core view", layout())
    assert store.delete("Core view") is True
    assert store.get("Core view") is None
    assert store.delete("Core view") is False


def test_a_missing_file_holds_nothing(store: LayoutStore) -> None:
    assert store.summaries() == []
    assert store.get("anything") is None


def test_a_corrupt_file_is_reported_with_its_path(store: LayoutStore) -> None:
    store.path.write_text("{", encoding="utf-8")
    with pytest.raises(LayoutStoreError, match="layouts.json"):
        store.summaries()


def test_saving_leaves_no_temporary_file(store: LayoutStore) -> None:
    store.put("Core view", layout())
    assert [p.name for p in store.path.parent.iterdir()] == ["layouts.json"]


def test_the_store_is_bounded(
    store: LayoutStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sunstone.layouts.MAX_LAYOUTS", 2)
    store.put("a", layout())
    store.put("b", layout())
    with pytest.raises(LayoutStoreFull):
        store.put("c", layout())
    store.put("a", layout())  # replacing is still allowed


@pytest.mark.parametrize("name", ["", " leading", "trailing ", "x" * 65])
def test_bad_names_are_rejected(store: LayoutStore, name: str) -> None:
    with pytest.raises(ValidationError):
        store.put(name, layout())


def test_saved_data_defaults_to_files_beside_the_topology() -> None:
    topology = Path("data/sample/small.yaml")
    assert Files().path(topology, "layouts") == Path("data/sample/small.layouts.json")
    assert Files().path(topology, "operations") == Path(
        "data/sample/small.operations.json"
    )
    given = Files(layouts=Path("/tmp/x.json"))
    assert given.path(topology, "layouts") == Path("/tmp/x.json")


def test_api_saves_lists_opens_and_deletes(topology_file: Path, tmp_path: Path) -> None:
    client = TestClient(
        create_app(topology_file, files=Files(layouts=tmp_path / "l.json"))
    )
    assert client.get("/api/layouts").json() == []

    saved = client.put("/api/layouts/Core view", json=LAYOUT)
    assert saved.status_code == 200
    assert saved.json()["settings"]["path"] == {"from": "r1", "to": "r2"}

    listed = client.get("/api/layouts").json()
    assert [(s["name"], s["scope"], s["nodes"]) for s in listed] == [
        ("Core view", "path", 2)
    ]
    opened = client.get("/api/layouts/Core view").json()
    assert opened["positions"]["r1"] == {"x": 1.5, "y": -2.0}

    assert client.delete("/api/layouts/Core view").status_code == 204
    assert client.get("/api/layouts/Core view").status_code == 404
    assert client.delete("/api/layouts/Core view").status_code == 404


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d["settings"].update(scope="everything"),
        lambda d: d["settings"].update(hops=9),
        lambda d: d["settings"].update(colour="blue"),
        lambda d: d["positions"].update(r3={"x": 1}),
    ],
)
def test_api_rejects_bad_layouts(topology_file: Path, tmp_path: Path, change) -> None:
    client = TestClient(
        create_app(topology_file, files=Files(layouts=tmp_path / "l.json"))
    )
    body = json.loads(json.dumps(LAYOUT))
    change(body)
    assert client.put("/api/layouts/bad", json=body).status_code == 422


def test_api_rejects_long_names(topology_file: Path, tmp_path: Path) -> None:
    client = TestClient(
        create_app(topology_file, files=Files(layouts=tmp_path / "l.json"))
    )
    assert client.put(f"/api/layouts/{'x' * 65}", json=LAYOUT).status_code == 422


def test_api_reports_a_full_store_as_a_conflict(
    topology_file: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sunstone.layouts.MAX_LAYOUTS", 1)
    client = TestClient(
        create_app(topology_file, files=Files(layouts=tmp_path / "l.json"))
    )
    assert client.put("/api/layouts/a", json=LAYOUT).status_code == 200
    assert client.put("/api/layouts/b", json=LAYOUT).status_code == 409
