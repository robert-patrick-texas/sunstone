from datetime import UTC, datetime
from pathlib import Path

import pytest

from sunstone.changes import (
    Change,
    ChangeConflict,
    ChangesError,
    ChangeStore,
    applied,
)
from sunstone.discovery import Fix
from sunstone.model import Endpoint, Link, Topology


@pytest.fixture
def topology(topology_data: dict) -> Topology:
    """The minimal topology, with a third device to cable to."""
    topology_data["devices"].append({"name": "r3", "site": "DAL", "role": "access"})
    return Topology.model_validate(topology_data)


def link(a: str, b: str) -> Link:
    """A link between two ``device:interface`` ends."""
    ends = [Endpoint(device=e.split(":")[0], interface=e.split(":")[1]) for e in (a, b)]
    return Link(a=ends[0], b=ends[1], speed_mbps=10_000)


def test_fixes_move_add_and_retire_links_in_turn(topology: Topology) -> None:
    [first] = topology.links
    moved = link("r1:Te1/0/1", "r2:Te1/0/50")
    added = link("r2:Te1/0/49", "r3:Te1/0/1")
    fixes = [
        Fix(kind="move", summary="Move it", before=first, after=moved),
        Fix(kind="add", summary="Add it", after=added),
    ]
    assert [ln.id for ln in applied(topology, fixes).links] == [moved.id, added.id]
    retired = [*fixes, Fix(kind="retire", summary="Retire it", before=moved)]
    assert [ln.id for ln in applied(topology, retired).links] == [added.id]
    # Neither touches what it starts from.
    assert topology.links == [first]


def test_a_fix_that_no_longer_fits_is_a_conflict(topology: Topology) -> None:
    [first] = topology.links
    gone = link("r1:Te1/0/9", "r3:Te1/0/9")
    with pytest.raises(ChangeConflict, match="no longer documented"):
        applied(topology, [Fix(kind="retire", summary="Retire it", before=gone)])
    # A second link on a port already in use.
    clash = link("r1:Te1/0/1", "r3:Te1/0/1")
    with pytest.raises(ChangeConflict, match="r1:Te1/0/1 is used by 2 links"):
        applied(topology, [Fix(kind="add", summary="Add it", after=clash)])
    assert applied(topology, []).links == [first]


def test_the_change_set_is_kept_without_link_ids(
    topology: Topology, tmp_path: Path
) -> None:
    [first] = topology.links
    change = Change(
        id="c1",
        finding="not-seen:x",
        title="r1 – r2 not seen",
        fix=Fix(kind="retire", summary="Retire it", before=first),
        note="Gone since the refit",
        by="Pat",
        at=datetime(2026, 10, 27, 15, tzinfo=UTC),
    )
    path = tmp_path / "changes.json"
    ChangeStore(path).save([change])
    assert '"id": "c1"' in path.read_text() and first.id not in path.read_text()
    assert ChangeStore(path).changes() == [change]
    path.write_text("{", encoding="utf-8")
    with pytest.raises(ChangesError, match="changes.json"):
        ChangeStore(path)
