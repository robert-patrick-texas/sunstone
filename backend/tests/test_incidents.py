from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sunstone.api import Files, create_app
from sunstone.incidents import (
    CloseIn,
    Entry,
    Incident,
    IncidentIn,
    IncidentNoteIn,
    IncidentRefused,
    IncidentStore,
    Member,
    Recorded,
    began,
    report,
    timeline,
)
from sunstone.layouts import DeviceCenter, LinksCenter, SiteCenter
from sunstone.live import (
    DeviceHistory,
    DeviceState,
    InterfaceState,
    NetworkState,
    StateEvent,
)
from sunstone.mockgen import PRESETS, generate, to_yaml
from sunstone.model import Topology
from sunstone.oncall import Notice, Page
from sunstone.problems import Ack, link_name

T0 = datetime(2026, 10, 27, 8, 0, tzinfo=UTC)
STEP = timedelta(minutes=5)


def at(steps: int) -> datetime:
    return T0 + STEP * steps


def event(steps: int, kind: str, name: str, planned: bool = False) -> StateEvent:
    field = (
        "link" if kind.startswith("link") or kind in ("busy", "congested") else "device"
    )
    return StateEvent.model_validate(
        {"at": at(steps), "kind": kind, field: name, "planned": planned}
    )


@pytest.fixture(scope="module")
def topology() -> Topology:
    return generate(PRESETS["small"], seed=1)


def problem_member(
    problem: str, devices: list[str], links: list[str], **extra: object
) -> Member:
    fields = {
        "problem": problem,
        "title": f"{problem} title",
        "kind": "outage",
        "target": DeviceCenter(kind="device", id=devices[0])
        if devices
        else LinksCenter(kind="links", ids=links),
        "devices": devices,
        "links": links,
        "lost": 0,
        "exposed": 0,
        "began": at(0),
        "joined_at": at(1),
        "joined_by": "Pat",
    }
    return Member.model_validate({**fields, **extra})


def test_a_problem_began_when_the_first_of_its_parts_went_wrong_and_stayed_so() -> None:
    events = [
        event(0, "down", "hou-a"),
        event(1, "busy", "L1"),
        event(2, "up", "hou-a"),
        event(3, "load-normal", "L1"),
        event(4, "down", "hou-a"),
        event(5, "loss", "hou-b"),
        event(6, "down", "hou-b"),
    ]
    assert began(events, ["hou-a", "hou-b"], [], at(10)) == at(4)
    # Only what happened by the moment counts.
    assert began(events, ["hou-a", "hou-b"], [], at(3)) is None
    assert began(events, ["hou-b"], [], at(10)) == at(5)
    assert began(events, [], ["L1"], at(10)) is None


def number_one(store: IncidentStore) -> Incident:
    found = store.get(1)
    assert found is not None
    return found


def test_an_incident_follows_its_problems_until_it_is_closed(tmp_path: Path) -> None:
    path = tmp_path / "incidents.json"
    store = IncidentStore(path)
    first = problem_member("down:L1", [], ["L1"])
    opened = store.open(
        IncidentIn(
            problem="down:L1", title="HOU circuit", by="Pat", note=" ticket 4411 "
        ),
        first,
        at(1),
    )
    assert (opened.number, opened.status, opened.began) == (1, "open", at(0))
    assert [n.text for n in opened.notes] == ["ticket 4411"]
    with pytest.raises(IncidentRefused, match="in incident 1 already"):
        store.open(IncidentIn(problem="down:L1", title="Again", by="Sam"), first, at(2))

    store.join(1, problem_member("down:L2", [], ["L2"], began=None))
    assert number_one(store).began is None
    assert store.clear({"down:L1"}, at(2)) == []
    assert [m.cleared_at for m in number_one(store).problems] == [None, at(2)]
    # A problem that comes back before the incident is closed is followed again.
    assert store.clear({"down:L1", "down:L2"}, at(3)) == []
    assert number_one(store).status == "open"
    assert store.clear(set(), at(4)) == [1]
    assert store.clear(set(), at(5)) == []
    cleared = store.get(1)
    assert cleared is not None
    assert (cleared.status, cleared.cleared_at) == ("cleared", at(4))

    closed = store.close(1, CloseIn(summary="Carrier fiber cut.", by="Sam"), at(6))
    assert closed.status == "closed"
    with pytest.raises(IncidentRefused, match="closed"):
        store.add_note(1, IncidentNoteIn(text="late", by="Lee"), at(7))
    # Closed, it no longer follows its problems, which can start another.
    assert store.clear({"down:L1"}, at(8)) == []
    assert store.get(1) == closed
    assert (
        store.open(
            IncidentIn(problem="down:L1", title="HOU circuit again", by="Lee"),
            first,
            at(9),
        ).number
        == 2
    )
    with pytest.raises(KeyError):
        store.join(3, first)

    assert IncidentStore(path).incidents() == store.incidents()


def test_the_timeline_says_what_happened_in_order(
    topology: Topology, tmp_path: Path
) -> None:
    hou = sorted(d.name for d in topology.devices if d.site == "HOU")[:2]
    other = next(d.name for d in topology.devices if d.site != "HOU")
    circuit = next(ln for ln in topology.links if ln.kind == "wan")
    incident = IncidentStore(tmp_path / "i.json").open(
        IncidentIn(problem="outage:x", title="HOU cut off", by="Pat"),
        problem_member(
            "outage:x", hou, [circuit.id], began=at(2), joined_at=at(4), lost=5
        ),
        at(4),
    )
    incident = incident.model_copy(
        update={
            "problems": [incident.problems[0].model_copy(update={"cleared_at": at(10)})]
        }
    )
    recorded = Recorded(
        events=[
            event(-5, "loss", hou[0]),  # before the lead: left out
            event(0, "loss", hou[0]),
            event(2, "down", hou[0]),
            event(2, "down", hou[1], planned=True),
            event(2, "link-down", circuit.id),
            event(3, "down", other),  # not part of it
            event(10, "up", hou[0]),
            event(12, "up", hou[1]),  # after it cleared: left out
        ],
        acks=[Ack(problem="outage:x", by="Pat", note="calling the carrier", at=at(5))],
        pages=[Page(problem="outage:x", by="Pat", id="p1", team="noc", at=at(6))],
        notified={"p1": [Notice(to="primary", person="jordan", at=at(6))]},
        people={"jordan": "Jordan Ibarra"},
        teams={"noc": "NOC"},
    )
    entries = timeline(incident, recorded, [], topology, at(20))
    assert [(e.at, e.kind, e.text) for e in entries] == [
        (at(0), "event", f"{hou[0]} dropping packets"),
        (at(2), "event", f"2 devices ({hou[0]}, {hou[1]}) down"),
        (at(2), "event", f"{link_name(circuit)} down"),
        (at(4), "opened", "Pat opened the incident: HOU cut off"),
        (at(5), "ack", "Pat took on outage:x title: calling the carrier"),
        (at(6), "page", "Pat paged NOC"),
        (at(6), "notice", "Jordan Ibarra told, as NOC's primary"),
        (at(10), "event", f"{hou[0]} back up"),
        (at(10), "cleared", "outage:x title cleared"),
    ]
    down = entries[1]
    assert (down.target, down.planned) == (SiteCenter(kind="site", id="HOU"), False)

    made = report(incident, entries, "America/Chicago", at(20))
    assert made.acknowledged == entries[4] and made.paged == entries[5]
    assert made.message.subject == "Incident 1: HOU cut off (cleared, lasted 40 min)"
    text = made.message.text.splitlines()
    assert text[1] == "Began 03:10 Tue 27 Oct; opened by Pat at 03:20 Tue 27 Oct (CDT)."
    assert text[2] == "Acknowledged by Pat 15 min in; paged by Pat 20 min in."
    assert "- outage:x title (5 unreachable), cleared 03:50" in text
    assert "- 03:20 Pat opened the incident: HOU cut off" in text

    # What was kept stays in the timeline once the record it came from is gone.
    kept = [e for e in entries if e.kind in ("event", "ack", "page", "notice")]
    again = timeline(
        incident, Recorded(events=[], acks=[], pages=[]), kept, topology, at(20)
    )
    assert again == entries


class LinksDown:
    """Live state with every device up and some links down."""

    retention = timedelta(hours=24)

    def __init__(self, topology: Topology, down: frozenset[str]) -> None:
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


def incidents_client(topology: Topology, tmp_path: Path) -> TestClient:
    path = tmp_path / "small.yaml"
    path.write_text(to_yaml(topology, "test"), encoding="utf-8")
    files = Files(
        operations=tmp_path / "ops.json",
        layouts=tmp_path / "l.json",
        changes=tmp_path / "changes.json",
        handovers=tmp_path / "handovers.json",
        incidents=tmp_path / "incidents.json",
    )
    sites = {d.name: d.site for d in topology.devices}
    inside = [ln for ln in topology.links if sites[ln.a.device] == sites[ln.b.device]]
    first = inside[0]
    second = next(ln for ln in inside if sites[ln.a.device] != sites[first.a.device])
    source = LinksDown(topology, frozenset({first.id, second.id}))
    return TestClient(create_app(path, files=files, state_source=source, warm=False))


def test_incidents_are_opened_noted_joined_and_closed(
    topology: Topology, tmp_path: Path
) -> None:
    client = incidents_client(topology, tmp_path)
    one, two, *_ = client.get("/api/problems").json()["problems"]
    opening = {"problem": one["id"], "title": "Circuits down", "by": "Pat"}
    assert (
        client.post("/api/incidents", json={**opening, "problem": "nope"}).status_code
        == 404
    )
    made = client.post("/api/incidents", json={**opening, "note": "carrier called"})
    assert made.status_code == 201
    incident = made.json()
    assert (incident["number"], incident["status"]) == (1, "open")
    assert [e["kind"] for e in incident["timeline"]] == ["opened", "note"]
    assert incident["message"]["subject"].startswith("Incident 1: Circuits down (")
    again = client.post("/api/incidents", json=opening)
    assert (again.status_code, again.json()["detail"]) == (
        409,
        "That problem is in incident 1 already",
    )

    problems = {p["id"]: p for p in client.get("/api/problems").json()["problems"]}
    assert (problems[one["id"]]["incident"], problems[two["id"]]["incident"]) == (
        1,
        None,
    )
    joined = client.post(
        "/api/incidents/1/problems", json={"problem": two["id"], "by": "Sam"}
    )
    assert [m["problem"] for m in joined.json()["problems"]] == [one["id"], two["id"]]
    note = client.post(
        "/api/incidents/1/notes", json={"text": "both on one carrier", "by": "Sam"}
    )
    assert note.status_code == 201
    listed = client.get("/api/incidents").json()["incidents"]
    assert [(i["number"], i["problems"]) for i in listed] == [
        (1, [one["id"], two["id"]])
    ]
    handover = client.get("/api/handover").json()
    assert [(i["number"], i["status"]) for i in handover["incidents"]] == [(1, "open")]
    assert (
        "\nIncidents (1)\n- 1 Circuits down: open since " in handover["message"]["text"]
    )

    closed = client.post(
        "/api/incidents/1/close", json={"summary": "Fiber cut.", "by": "Sam"}
    )
    assert (closed.json()["status"], closed.json()["closed"]["by"]) == ("closed", "Sam")
    assert (
        client.post(
            "/api/incidents/1/notes", json={"text": "x", "by": "Sam"}
        ).status_code
        == 409
    )
    assert client.get("/api/incidents/2").status_code == 404
    assert client.get("/api/problems").json()["problems"][0]["incident"] is None

    restarted = incidents_client(topology, tmp_path)
    kept = restarted.get("/api/incidents/1").json()
    assert (kept["closed"]["summary"], kept["timeline"][-1]["kind"]) == (
        "Fiber cut.",
        "closed",
    )


def test_an_entry_keeps_where_to_look() -> None:
    entry = Entry(
        at=at(0),
        kind="event",
        text="x down",
        target=DeviceCenter(kind="device", id="x"),
    )
    assert Entry.model_validate_json(entry.model_dump_json()) == entry
