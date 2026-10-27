from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sunstone.api import Files, create_app
from sunstone.layouts import LinksCenter, SiteCenter
from sunstone.mockgen import (
    PRESETS,
    directory_yaml,
    generate,
    generate_directory,
    to_yaml,
)
from sunstone.model import Topology
from sunstone.oncall import (
    Cover,
    DirectoryError,
    Match,
    Page,
    Rotation,
    Step,
    Team,
    describe,
    escalation,
    load_directory,
    ownership,
    shift,
)
from sunstone.problems import Ack

# 2026-01-05 is a Monday; 09:00 in Chicago is 15:00 UTC in winter.
MONDAY = datetime(2026, 1, 5, 15, 0, tzinfo=UTC)
T0 = datetime(2026, 10, 27, 15, 0, tzinfo=UTC)


def team(people: tuple[str, ...] = ("a", "b", "c"), **extra: object) -> Team:
    rotation = Rotation(
        people=list(people),
        starts=date(2026, 1, 5),
        timezone="America/Chicago",
        handoff="09:00",
    )
    return Team.model_validate(
        {"id": "net", "name": "Network", "rotation": rotation, "manager": "m", **extra}
    )


def cover(person: str, start: datetime, end: datetime) -> Cover:
    return Cover(
        team="net",
        person=person,
        start=start,
        end=end,
        by="Pat",
        id=f"{person}-{start:%H%M}",
        saved_at=start,
    )


def page(at: datetime = T0, cleared_at: datetime | None = None) -> Page:
    return Page(
        problem="outage:x", by="Sam", id="p1", team="net", at=at, cleared_at=cleared_at
    )


def ack(at: datetime) -> Ack:
    return Ack(problem="outage:x", by="Lee", at=at)


@pytest.fixture(scope="module")
def topology() -> Topology:
    return generate(PRESETS["small"], seed=1)


class TestShift:
    def test_turns_go_round_at_the_local_handoff(self) -> None:
        first = shift(team(), MONDAY, [])
        assert (first.primary, first.secondary) == ("a", "b")
        assert first.since == MONDAY
        assert first.until == MONDAY + timedelta(days=7)
        assert shift(team(), MONDAY + timedelta(days=7), []).primary == "b"
        assert shift(team(), MONDAY + timedelta(days=21), []).primary == "a"
        # A minute before the first handoff, the turn before it.
        assert shift(team(), MONDAY - timedelta(minutes=1), []).primary == "c"

    def test_handoff_stays_at_local_time_across_summer_time(self) -> None:
        # Clocks went forward on 8 March 2026, so 09:00 is 14:00 UTC from then.
        handoff = datetime(2026, 3, 9, 14, 0, tzinfo=UTC)
        assert shift(team(), handoff, []).since == handoff
        before = shift(team(), handoff - timedelta(minutes=1), [])
        assert before.until == handoff
        assert before.until - before.since == timedelta(days=7, hours=-1)

    def test_one_person_has_no_secondary(self) -> None:
        assert shift(team(("a",)), MONDAY, []).secondary is None

    def test_a_cover_takes_the_primary_turn(self) -> None:
        covering = cover("z", MONDAY + timedelta(hours=1), MONDAY + timedelta(hours=3))
        during = shift(team(), MONDAY + timedelta(hours=2), [covering])
        assert (during.primary, during.secondary) == ("z", "a")
        assert during.cover == covering.id
        assert (during.since, during.until) == (covering.start, covering.end)
        # Before it, the turn ends when the cover starts.
        assert shift(team(), MONDAY, [covering]).until == covering.start
        after = shift(team(), MONDAY + timedelta(hours=4), [covering])
        assert after.primary == "a"

    def test_the_secondary_covering_keeps_the_secondary(self) -> None:
        covering = cover("a", MONDAY, MONDAY + timedelta(hours=1))
        during = shift(team(), MONDAY, [covering])
        assert (during.primary, during.secondary) == ("a", "b")


class TestEscalation:
    def test_steps_come_due_in_turn(self) -> None:
        paging = escalation(page(), team(), None, [], T0 + timedelta(minutes=20))
        assert [(n.to, n.at) for n in paging.notified] == [
            ("primary", T0),
            ("secondary", T0 + timedelta(minutes=15)),
        ]
        assert paging.next is not None
        assert (paging.next.to, paging.next.person) == ("manager", "m")
        assert paging.stopped is None

    def test_an_acknowledgement_stops_it(self) -> None:
        acked = ack(T0 + timedelta(minutes=10))
        paging = escalation(page(), team(), acked, [], T0 + timedelta(minutes=40))
        assert [n.to for n in paging.notified] == ["primary"]
        assert (paging.next, paging.stopped) == (None, "acknowledged")

    def test_clearing_stops_it(self) -> None:
        cleared = page(cleared_at=T0 + timedelta(minutes=20))
        paging = escalation(cleared, team(), None, [], T0 + timedelta(hours=1))
        assert [n.to for n in paging.notified] == ["primary", "secondary"]
        assert (paging.next, paging.stopped) == (None, "cleared")

    def test_replaying_shows_it_as_it_stood(self) -> None:
        # Cleared later, but at T0 + 5 minutes no one knew that yet.
        cleared = page(cleared_at=T0 + timedelta(minutes=20))
        paging = escalation(cleared, team(), None, [], T0 + timedelta(minutes=5))
        assert paging.stopped is None
        assert paging.next is not None and paging.next.to == "secondary"

    def test_steps_with_no_one_to_tell_are_skipped(self) -> None:
        alone = team(("a",), manager=None)
        paging = escalation(page(), alone, None, [], T0 + timedelta(hours=1))
        assert [n.to for n in paging.notified] == ["primary"]
        assert paging.next is None

    def test_each_step_tells_whoever_is_on_when_it_comes_due(self) -> None:
        covering = cover("z", T0 + timedelta(minutes=10), T0 + timedelta(hours=1))
        paging = escalation(
            page(), team(), None, [covering], T0 + timedelta(minutes=20)
        )
        first, second = paging.notified
        # The secondary at T0 + 15 minutes is whoever "z" covers for.
        assert first.person != "z"
        assert second.person == first.person

    def test_escalation_must_start_at_once_and_go_in_order(self) -> None:
        with pytest.raises(ValueError, match="starts at 0 minutes"):
            team(escalation=[Step(after_min=5, to="primary")])
        with pytest.raises(ValueError, match="in order"):
            team(
                escalation=[
                    Step(after_min=0, to="primary"),
                    Step(after_min=30, to="secondary"),
                    Step(after_min=15, to="manager"),
                ]
            )


class TestOwnership:
    def test_the_first_matching_route_owns_each_item(self, topology: Topology) -> None:
        directory = generate_directory(topology, seed=1)
        owners = ownership(directory, topology)
        assert len(owners.devices) == len(topology.devices)
        assert len(owners.links) == len(topology.links)
        assert owners.sites == {
            "DAL": "datacenter",
            "IAD": "datacenter",
            "HOU": "network-central",
            "AUS": "network-central",
            "SAT": "network-central",
        }
        assert owners.devices["hou-acc-01"] == "network-central"
        wan = next(ln for ln in topology.links if ln.kind == "wan")
        assert owners.links[wan.id] == "wan"

    def test_a_target_is_owned_by_its_first_owned_part(
        self, topology: Topology
    ) -> None:
        owners = ownership(generate_directory(topology, seed=1), topology)
        wan = next(ln for ln in topology.links if ln.kind == "wan")
        assert owners.owner(LinksCenter(kind="links", ids=["nope", wan.id])) == "wan"
        assert owners.owner(SiteCenter(kind="site", id="HOU")) == "network-central"

    @pytest.mark.parametrize(
        ("match", "words"),
        [
            (Match(kinds=["wan"]), "WAN links"),
            (Match(sites=["DAL", "IAD"]), "Everything at DAL, IAD"),
            (Match(roles=["core"], regions=["South"]), "Core devices in South"),
            (Match(providers=["Mesa Carrier"]), "Circuits from Mesa Carrier"),
            (Match(), "Everything else"),
        ],
    )
    def test_routes_are_described_in_words(self, match: Match, words: str) -> None:
        assert describe(match) == words


class TestLoading:
    def test_the_generated_directory_loads_back(
        self, topology: Topology, tmp_path: Path
    ) -> None:
        directory = generate_directory(topology, seed=1)
        path = tmp_path / "small.oncall.yaml"
        path.write_text(directory_yaml(directory, "test"), encoding="utf-8")
        assert load_directory(path, topology) == directory

    def test_every_reference_is_checked(
        self, topology: Topology, tmp_path: Path
    ) -> None:
        path = tmp_path / "bad.oncall.yaml"
        path.write_text(
            """
people: [{id: pat, name: Pat}]
teams:
- {id: net, name: Network, manager: boss,
   rotation: {people: [pat, nobody], starts: 2026-01-05}}
routes: [{team: net}, {team: ghost}]
""",
            encoding="utf-8",
        )
        with pytest.raises(DirectoryError) as e:
            load_directory(path, topology)
        for name in ("'boss'", "'nobody'", "'ghost'"):
            assert name in str(e.value)

    def test_routes_and_carriers_must_be_in_the_topology(
        self, topology: Topology, tmp_path: Path
    ) -> None:
        path = tmp_path / "bad.oncall.yaml"
        path.write_text(
            """
people: [{id: pat, name: Pat}]
teams: [{id: net, name: Network, rotation: {people: [pat], starts: 2026-01-05}}]
routes:
- {team: net, match: {sites: [XYZ], regions: [Atlantis], providers: [Acme]}}
carriers: [{provider: Acme, phone: '1'}]
""",
            encoding="utf-8",
        )
        with pytest.raises(DirectoryError) as e:
            load_directory(path, topology)
        assert str(e.value).count("in the topology") == 4

    def test_times_and_zones_are_checked(
        self, topology: Topology, tmp_path: Path
    ) -> None:
        path = tmp_path / "bad.oncall.yaml"
        # Unquoted, 10:00 is the number 600 to YAML.
        path.write_text(
            """
people: [{id: pat, name: Pat}]
teams:
- {id: net, name: Network,
   rotation: {people: [pat], starts: 2026-01-05, handoff: 10:00, timezone: Mars/Base}}
routes: [{team: net}]
""",
            encoding="utf-8",
        )
        with pytest.raises(DirectoryError) as e:
            load_directory(path, topology)
        assert "handoff" in str(e.value)
        assert "Mars/Base" in str(e.value)


def make_client(topology: Topology, tmp_path: Path, oncall: bool = True) -> TestClient:
    path = tmp_path / "small.yaml"
    path.write_text(to_yaml(topology, "test"), encoding="utf-8")
    if oncall:
        directory = generate_directory(topology, seed=1)
        (tmp_path / "small.oncall.yaml").write_text(
            directory_yaml(directory, "test"), encoding="utf-8"
        )
    files = Files(operations=tmp_path / "ops.json", layouts=tmp_path / "l.json")
    return TestClient(create_app(path, files=files, warm=False))


class TestApi:
    def test_who_is_on_call_and_who_owns_what(
        self, topology: Topology, tmp_path: Path
    ) -> None:
        client = make_client(topology, tmp_path)
        oncall = client.get("/api/oncall").json()
        teams = {t["id"]: t for t in oncall["teams"]}
        assert list(teams) == ["wan", "datacenter", "network-central", "noc"]
        assert teams["wan"]["owns"] == ["WAN links"]
        assert teams["wan"]["now"]["until"] == teams["wan"]["next"]["since"]
        assert {p["id"] for p in oncall["people"]} >= {
            t["now"]["primary"] for t in teams.values()
        }
        assert len(oncall["carriers"]) >= 1
        owners = client.get("/api/ownership").json()
        assert owners["sites"]["HOU"] == "network-central"

    def test_problems_are_routed_paged_and_escalate(
        self, topology: Topology, tmp_path: Path
    ) -> None:
        client = make_client(topology, tmp_path)
        state = client.get("/api/state").json()
        problems = client.get("/api/problems", params={"at": state["generated_at"]})
        problem = problems.json()["problems"][0]
        assert problem["team"] is not None
        assert problem["urgency"] in ("high", "low")
        assert problem["paging"] is None

        sent = {"problem": problem["id"], "by": "Sam", "link": "/?live=1"}
        made = client.post("/api/pages", json=sent)
        assert made.status_code == 201
        assert made.json()["team"] == problem["team"]
        paged = next(
            p
            for p in client.get("/api/problems").json()["problems"]
            if p["id"] == problem["id"]
        )
        on = {t["id"]: t for t in client.get("/api/oncall").json()["teams"]}
        first = paged["paging"]["notified"][0]
        assert first["to"] == "primary"
        assert first["person"] == on[problem["team"]]["now"]["primary"]
        assert paged["paging"]["next"]["to"] == "secondary"

        # Acknowledging stops escalation.
        ack = {"problem": problem["id"], "by": "Lee"}
        assert client.post("/api/acks", json=ack).status_code == 201
        acked = next(
            p
            for p in client.get("/api/problems").json()["problems"]
            if p["id"] == problem["id"]
        )
        assert acked["paging"]["stopped"] == "acknowledged"
        assert acked["paging"]["next"] is None

        assert (
            client.delete("/api/pages", params={"problem": problem["id"]}).status_code
            == 204
        )
        assert (
            client.delete("/api/pages", params={"problem": problem["id"]}).status_code
            == 404
        )
        missing = client.post("/api/pages", json={**sent, "problem": "outage:nowhere"})
        assert missing.status_code == 404

    def test_a_cover_changes_who_is_on_call(
        self, topology: Topology, tmp_path: Path
    ) -> None:
        client = make_client(topology, tmp_path)
        now = datetime.now(UTC)
        cover_in = {
            "team": "wan",
            "person": "sam-chen",
            "start": (now - timedelta(minutes=5)).isoformat(),
            "end": (now + timedelta(hours=2)).isoformat(),
            "by": "Pat",
        }
        made = client.post("/api/covers", json=cover_in)
        assert made.status_code == 201
        wan = next(
            t for t in client.get("/api/oncall").json()["teams"] if t["id"] == "wan"
        )
        assert wan["now"]["primary"] == "sam-chen"
        assert wan["now"]["cover"] == made.json()["id"]
        assert client.delete(f"/api/covers/{made.json()['id']}").status_code == 204
        assert client.delete(f"/api/covers/{made.json()['id']}").status_code == 404
        assert (
            client.post("/api/covers", json={**cover_in, "team": "ghost"}).status_code
            == 422
        )
        assert (
            client.post(
                "/api/covers", json={**cover_in, "person": "nobody"}
            ).status_code
            == 422
        )
        backwards = {**cover_in, "end": cover_in["start"]}
        assert client.post("/api/covers", json=backwards).status_code == 422

    def test_without_a_directory_routing_is_off(
        self, topology: Topology, tmp_path: Path
    ) -> None:
        client = make_client(topology, tmp_path, oncall=False)
        assert client.get("/api/oncall").status_code == 404
        assert client.get("/api/ownership").status_code == 404
        problem = client.get("/api/problems").json()["problems"][0]
        assert problem["team"] is None

    def test_a_named_directory_must_exist(
        self, topology: Topology, tmp_path: Path
    ) -> None:
        path = tmp_path / "small.yaml"
        path.write_text(to_yaml(topology, "test"), encoding="utf-8")
        with pytest.raises(DirectoryError):
            create_app(path, files=Files(oncall=tmp_path / "missing.yaml"), warm=False)
