"""HTTP API, plus the built web UI served from the same origin."""

import os
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi import Path as PathParam
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict

from sunstone.cabling import Cabling
from sunstone.changes import (
    Change,
    ChangeConflict,
    ChangeIn,
    ChangesError,
    ChangeSet,
    ChangeStore,
    PortNow,
    Review,
    applied,
    expected,
    new_change,
    ports,
)
from sunstone.discovery import (
    EXPECTABLE,
    Comparison,
    Finding,
    Fix,
    SimulatedDiscovery,
    expecting,
)
from sunstone.discovery_log import DiscoveryLog
from sunstone.handover import (
    Handover,
    HandoverList,
    HandoverStore,
    SignOff,
    SignOffIn,
    handover_id,
    last_change,
    next_change,
    outages,
    shift_changes,
    summary,
)
from sunstone.impact import Failures, Network, WhatIf
from sunstone.layouts import (
    MAX_NAME,
    Center,
    LayoutIn,
    LayoutStore,
    LayoutStoreFull,
    LayoutSummary,
    SavedLayout,
)
from sunstone.live import (
    DeviceHistory,
    EventLog,
    NetworkState,
    StateEvent,
    StateSource,
)
from sunstone.loader import load_topology
from sunstone.model import Topology
from sunstone.monitor import POLL, Monitor
from sunstone.oncall import (
    DEFAULT_URGENCY,
    Cover,
    CoverIn,
    Directory,
    HandoverTimes,
    OnCall,
    Ownership,
    Page,
    PageIn,
    RoutedProblem,
    RoutedProblemList,
    escalation,
    load_directory,
    on_call,
    ownership,
)
from sunstone.operations import (
    OperationsFull,
    OperationsStore,
    ShiftNote,
    ShiftNoteIn,
    Window,
    WindowIn,
    accounted_for,
    event_planned,
)
from sunstone.problems import Ack, AckIn
from sunstone.simulate import SimulatedState, monitored

NameParam = Annotated[str, PathParam(min_length=1, max_length=MAX_NAME)]
HANDOVER_GRACE = timedelta(minutes=1)


class VersionInfo(BaseModel):
    """Which release of Sunstone is serving."""

    version: str


class WhatIfQuestion(BaseModel):
    """Devices, sites, and links to suppose failed, and the moment whose live
    state to start from (none for the healthy network)."""

    model_config = ConfigDict(extra="forbid")

    failures: list[Center]
    at: datetime | None = None


@dataclass(frozen=True)
class Files:
    """Where the server keeps what people save, and the on-call directory;
    None for a file beside the topology, such as ``small.layouts.json`` for
    ``small.yaml``."""

    layouts: Path | None = None
    operations: Path | None = None
    """Maintenance windows, acknowledgements, pages, covers, and shift notes."""
    changes: Path | None = None
    """Fixes accepted into the documentation."""
    handovers: Path | None = None
    """Handovers saved at shift changes."""
    oncall: Path | None = None
    """Teams, rotations, and what they own. Beside the topology
    (``small.oncall.yaml``) it is optional; named here, it must exist."""

    def path(self, topology_path: Path, kind: str) -> Path:
        """The file for one kind of data.

        Args:
            topology_path: The topology file.
            kind: ``layouts``, ``operations``, ``changes``, ``handovers``, or
                ``oncall``.

        Returns:
            The file given for it, or one beside the topology.

        Raises:
            None
        """
        given = {
            "layouts": self.layouts,
            "operations": self.operations,
            "changes": self.changes,
            "handovers": self.handovers,
        }.get(kind, self.oncall)
        suffix = "yaml" if kind == "oncall" else "json"
        return given or topology_path.with_name(f"{topology_path.stem}.{kind}.{suffix}")


@dataclass(frozen=True)
class _Documented:
    """The network as documented now, with the changes accepted, and
    everything worked out from it."""

    topology: Topology
    network: Network
    owners: Ownership | None
    state: StateSource
    monitor: Monitor
    log: DiscoveryLog
    stop: threading.Event
    """Set to stop working ahead for this version of the documentation."""


def create_app(
    topology_path: Path,
    web_dir: Path | None = None,
    files: Files | None = None,
    state_source: StateSource | None = None,
    warm: bool = True,
) -> FastAPI:
    """Build the app around one topology file, loaded once at startup.

    The documentation served is the topology file with the fixes accepted
    into it applied, and everything follows it; accepting or reverting one
    works everything out again.

    Args:
        topology_path: Topology YAML file to serve.
        web_dir: Built frontend to serve at ``/``, or None for API only
            (the Vite dev server serves the UI during development).
        files: Where saved layouts, operations, changes, and handovers go,
            and the on-call directory is, or None for files beside the
            topology.
        state_source: Where live state comes from, or None for simulated
            state (there are no real sources yet), which acts out planned
            maintenance and follows the simulated network's real cabling.
            Discovery is simulated either way, answering for the devices
            this source finds up. A source given is kept when the
            documentation changes; the simulated one is made again.
        warm: Work out the day's events and the present moment in the
            background at startup, and each new moment as it begins while
            anyone is watching, so viewers do not wait; and save each
            handover as its shift changes, rather than when next asked for.

    Returns:
        The FastAPI application.

    Raises:
        TopologyError: If the topology file is missing or invalid.
        OperationsError: If the operations file exists but cannot be read.
        ChangesError: If the changes file exists but cannot be read, or its
            changes no longer apply to the topology file.
        HandoverError: If the saved handovers file exists but cannot be read.
        DirectoryError: If the on-call directory is invalid, or was named
            and is missing.
    """
    base = load_topology(topology_path)
    files = files or Files()
    oncall_path = files.path(topology_path, "oncall")
    directory: Directory | None = (
        load_directory(oncall_path, base)
        if files.oncall or oncall_path.exists()
        else None
    )
    times = directory.handovers if directory else None
    handovers = HandoverStore(files.path(topology_path, "handovers"))
    store = LayoutStore(files.path(topology_path, "layouts"))
    changes = ChangeStore(files.path(topology_path, "changes"))
    try:
        topology = applied(base, [c.fix for c in changes.changes()])
    except ChangeConflict as e:
        raise ChangesError(
            f"{changes.path}: a change no longer applies to {topology_path.name}: {e}"
        ) from e
    operations = OperationsStore(
        files.path(topology_path, "operations"), Network(topology)
    )
    # The simulated network is cabled a little differently from its
    # documentation, and stays so however the documentation changes.
    cabling = Cabling(base, watched=set(monitored(base)))

    def build(documented: Topology) -> _Documented:
        """Work out everything that follows the documentation."""
        network = Network(documented)
        real = cabling.documenting(documented)
        state = state_source or SimulatedState(
            documented, plans=operations, cabling=real
        )
        return _Documented(
            topology=documented,
            network=network,
            owners=ownership(directory, documented) if directory else None,
            state=state,
            monitor=Monitor(network, state),
            log=DiscoveryLog(
                documented, SimulatedDiscovery(documented, real, state), state
            ),
            stop=threading.Event(),
        )

    def start(d: _Documented) -> None:
        """Work ahead in the background, unless asked not to: the day's events
        and the present first, then discovery's day, then each new moment
        and run as it comes."""
        if not warm:
            return

        def warm_up() -> None:
            d.monitor.warm()
            d.log.warm()

        threading.Thread(target=warm_up, name="warm", daemon=True).start()
        threading.Thread(
            target=d.monitor.keep_ahead, args=(d.stop,), name="ahead", daemon=True
        ).start()
        threading.Thread(
            target=d.log.keep_up, args=(d.stop,), name="discovery", daemon=True
        ).start()
        if times is not None:
            threading.Thread(
                target=keep_handing_over,
                args=(times, d.stop),
                name="handover",
                daemon=True,
            ).start()

    def keep_handing_over(times: HandoverTimes, stop: threading.Event) -> None:
        """Save each handover as its shift changes, those missed first."""
        while not stop.is_set():
            hand_over()
            now = datetime.now(UTC)
            if stop.wait((next_change(times, now) - now).total_seconds() + 1):
                return

    docs = build(topology)

    def document(changed: list[Change]) -> None:
        """Keep a new change set and follow the documentation it makes."""
        nonlocal docs
        fresh = build(applied(base, [c.fix for c in changed]))
        changes.save(changed)
        operations.network = fresh.network
        old, docs = docs, fresh
        old.stop.set()
        start(fresh)

    app = FastAPI(title="Sunstone")
    # Topology and state run to megabytes for large networks and compress well.
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    @app.get("/api/version")
    def get_version() -> VersionInfo:
        """Return the version serving, which self-update waits for after a restart."""
        return VersionInfo(version=version("sunstone"))

    @app.get("/api/topology")
    def get_topology() -> Topology:
        """Return the whole topology, as documented with the changes accepted."""
        return docs.topology

    def in_history(at: datetime, now: datetime) -> datetime:
        """Check that a requested moment is one the source keeps."""
        if at.tzinfo is None:
            raise HTTPException(
                422, "Give the time with a zone, as in 2026-10-27T15:00Z"
            )
        retention = docs.state.retention
        if not now - retention <= at <= now:
            hours = retention.total_seconds() / 3600
            raise HTTPException(
                422, f"The time must be within the last {hours:g} hours"
            )
        return at

    def moment_at(d: _Documented, at: datetime | None) -> datetime:
        """The moment asked for, or the present one."""
        return d.monitor.now() if at is None else in_history(at, datetime.now(UTC))

    @app.get("/api/state", response_model=NetworkState)
    def get_state(request: Request, at: datetime | None = None) -> Response:
        """Return the state of everything monitored, as of now or an earlier moment.

        The present is rounded down to the polling interval, and each moment
        is served from one cached, already compressed copy.
        """
        d = docs
        when = moment_at(d, at)
        moment = d.monitor.moment(when)
        if at is None:
            # Acknowledgements last until their problem clears.
            present = {p.id for p in moment.problems.problems}
            operations.clear(present, when)
        if "gzip" in request.headers.get("accept-encoding", ""):
            return Response(
                moment.gzipped,
                media_type="application/json",
                headers={"Content-Encoding": "gzip", "Vary": "Accept-Encoding"},
            )
        return Response(moment.body, media_type="application/json")

    @app.get("/api/problems")
    def get_problems(at: datetime | None = None) -> RoutedProblemList:
        """Return the problems in the state as of now or an earlier moment,
        with the maintenance that accounts for each, who is on it, the team
        that owns it, and where its page stands.

        Pass the ``generated_at`` of the state being shown, so the two match.
        """
        d = docs
        return routed(d, moment_at(d, at))

    def routed(d: _Documented, when: datetime) -> RoutedProblemList:
        """The problems at a moment, each with the maintenance that accounts
        for it, who is on it, the team that owns it, and its page."""
        found = d.monitor.moment(when).problems
        windows = [w for w in operations.windows() if w.start <= when < w.end]
        # The present is rounded down; acknowledgements made since still count.
        now = datetime.now(UTC)
        as_of = now if now - when < POLL else when
        acks = {a.problem: a for a in operations.acks() if a.active(as_of)}
        pages = {pg.problem: pg for pg in operations.pages() if pg.active(as_of)}
        covers = operations.covers()
        problems = []
        for p in found.problems:
            team_id = d.owners.owner(p.target) if d.owners else None
            team = directory.team(team_id) if directory and team_id else None
            page = pages.get(p.id)
            ack = acks.get(p.id)
            routed = {
                "planned": accounted_for(p, windows, d.network),
                "ack": ack,
                "team": team_id,
                "urgency": (
                    directory.urgency_of(p.kind)
                    if directory
                    else DEFAULT_URGENCY[p.kind]
                ),
                "paging": escalation(page, team, ack, covers, as_of)
                if page and team
                else None,
            }
            problems.append(RoutedProblem.model_validate({**dict(p), **routed}))
        return RoutedProblemList(at=found.at, problems=problems)

    @app.post("/api/impact")
    def post_impact(question: WhatIfQuestion) -> WhatIf:
        """Return what failing some devices, sites, and links would do."""
        d = docs
        before = (
            None if question.at is None else d.monitor.moment(moment_at(d, question.at))
        )
        failures = d.network.failures_of(question.failures)
        return d.network.what_if(failures, before.failures if before else None)

    @app.get("/api/events")
    def get_events() -> EventLog:
        """Return the changes the source saw over its whole history."""
        d = docs
        now = datetime.now(UTC)
        since = now - d.state.retention
        return EventLog(since=since, until=now, events=events_of(d, since, now))

    def events_of(d: _Documented, since: datetime, now: datetime) -> list[StateEvent]:
        """The source's events, each marked planned if maintenance accounts for it."""
        events = d.state.events(since, now)
        work = {at: operations.planned_at(at) for at in {e.at for e in events}}
        return [
            e.model_copy(update={"planned": event_planned(e, work[e.at], d.network)})
            for e in events
        ]

    @app.get("/api/handover")
    def get_handover(hours: Annotated[int, Query(ge=1, le=24)] = 12) -> Handover:
        """Return what the incoming shift needs to know about the last hours:
        what is wrong now and who is on it, outages that began or ended,
        pages and acknowledgements made, maintenance done, open, and coming,
        fixes recorded, discovery findings first seen, who is on call, and
        the notes written since the last shift change."""
        now = datetime.now(UTC)
        return handover_of(docs, now - timedelta(hours=hours), now, live=True)

    def handover_of(
        d: _Documented, since: datetime, until: datetime, live: bool
    ) -> Handover:
        """The handover of a span ending now, or at a shift change, as
        everything stood then."""
        events = events_of(d, datetime.now(UTC) - d.state.retention, until)
        when = d.monitor.now() if live else until
        problems = routed(d, when).problems
        if live:
            # Acknowledgements and pages last until their problem clears.
            operations.clear({p.id for p in problems}, when)

        def made[T: (Ack, Page)](records: list[T]) -> list[T]:
            """Those made in the span, newest first, as they stood at its end."""
            return [
                r.model_copy(update={"cleared_at": None})
                if r.cleared_at and r.cleared_at > until
                else r
                for r in records[::-1]
                if since <= r.at <= until
            ]

        # Now, the notes for the next shift change; at one, those since the last.
        start = last_change(times, until) if live and times else since
        found = discovered(d, until).findings
        return Handover(
            id=None if live else handover_id(until),
            since=since,
            until=until,
            timezone=times.timezone if times else "UTC",
            notes=[n for n in operations.notes() if start <= n.at < until],
            problems=problems,
            outages=outages(events, d.topology, since),
            pages=made(operations.pages()),
            acks=made(operations.acks()),
            windows=[
                w
                for w in operations.windows()
                if w.end > since and w.start < until + (until - since)
            ],
            changes=[c for c in changes.changes() if since <= c.at <= until][::-1],
            findings=[
                f for f in found if f.first_seen and since <= f.first_seen <= until
            ],
            oncall=on_call(directory, until, operations.covers())
            if directory
            else None,
        )

    def hand_over() -> None:
        """Save the handover of each shift change not saved yet, from the
        change before it, while history still covers that whole shift."""
        if times is None:
            return
        with handovers.lock:
            d = docs
            now = datetime.now(UTC)
            # Saved just after the change, a shift as long as history is
            # lacks only the moments it began.
            begins = now - d.state.retention - HANDOVER_GRACE
            for at in shift_changes(times, begins, now):
                since = last_change(times, at)
                if since >= begins and handovers.get(handover_id(at)) is None:
                    handovers.save(handover_of(d, since, at, live=False))

    def current(now: datetime) -> str | None:
        """The id of the handover the shift on now took over with, if saved."""
        if times is None:
            return None
        found = handovers.get(handover_id(last_change(times, now)))
        return found.id if found else None

    @app.get("/api/handovers")
    def list_handovers() -> HandoverList:
        """Return the handovers saved at shift changes, latest first, which
        one the shift on now took over with, and when the shift changes next."""
        hand_over()
        now = datetime.now(UTC)
        return HandoverList(
            next=next_change(times, now) if times else None,
            timezone=times.timezone if times else None,
            current=current(now),
            handovers=[summary(h) for h in handovers.handovers()],
        )

    @app.get("/api/handovers/{handover_id}")
    def get_saved_handover(handover_id: str) -> Handover:
        """Return a handover saved at a shift change, as it was then, with
        the notes the outgoing shift wrote."""
        hand_over()
        found = handovers.get(handover_id)
        if found is None:
            raise HTTPException(404, f"No handover {handover_id!r}")
        return found

    @app.post("/api/handovers/{handover_id}/sign-off", status_code=201)
    def sign_off(handover_id: str, sign: SignOffIn) -> Handover:
        """Sign for the handover the shift on now took over with, having read
        it, saying who took over; it can be signed for once."""
        hand_over()
        now = datetime.now(UTC)
        with handovers.lock:
            found = handovers.get(handover_id)
            if found is None:
                raise HTTPException(404, f"No handover {handover_id!r}")
            if found.signed:
                raise HTTPException(409, f"{found.signed.by} signed for it already")
            if handover_id != current(now):
                raise HTTPException(
                    409, "Only the handover of the shift on now can be signed for"
                )
            return handovers.sign(handover_id, SignOff(**sign.model_dump(), at=now))

    @app.post("/api/shift-notes", status_code=201)
    def add_note(note: ShiftNoteIn) -> ShiftNote:
        """Write a note for the next shift; it goes with the next handover."""
        try:
            return operations.add_note(note, datetime.now(UTC))
        except OperationsFull as e:
            raise HTTPException(409, str(e)) from e

    @app.delete("/api/shift-notes/{note_id}", status_code=204)
    def withdraw_note(note_id: str) -> None:
        """Withdraw a note that has not been handed over yet."""
        found = next((n for n in operations.notes() if n.id == note_id), None)
        if found is None:
            raise HTTPException(404, f"No note {note_id!r}")
        if times is not None and found.at < last_change(times, datetime.now(UTC)):
            raise HTTPException(409, "That note has been handed over already")
        operations.delete_note(note_id)

    @app.get("/api/discovery")
    def get_discovery(at: datetime | None = None) -> Comparison:
        """Return the discovery run in effect now, or at an earlier moment,
        compared with the documented links, with when each finding was seen,
        and the findings marked expected set aside.

        Runs come every 15 minutes, and each is compared once for every viewer.
        """
        now = datetime.now(UTC)
        return discovered(docs, now if at is None else in_history(at, now))

    @app.get("/api/history/{device}")
    def get_history(device: str) -> DeviceHistory:
        """Return one device's readings over the source's whole history."""
        now = datetime.now(UTC)
        state = docs.state
        history = state.history(device, now - state.retention, now)
        if history is None:
            raise HTTPException(404, f"{device!r} is not monitored")
        return history

    def check_targets(window: WindowIn) -> None:
        """Refuse a window naming devices, sites, or links that do not exist."""
        network = docs.network
        unknown = [
            t.id if t.kind != "links" else ", ".join(t.ids)
            for t in window.targets
            if (t.kind == "device" and t.id not in network.number)
            or (t.kind == "site" and t.id not in network.devices_of)
            or (t.kind == "links" and not set(t.ids) <= network.links.keys())
        ]
        if unknown:
            raise HTTPException(422, f"Not in the topology: {'; '.join(unknown)}")

    def changed_plans() -> None:
        """Planned work changes what the simulator shows, so start afresh."""
        d = docs
        d.monitor.forget()
        d.log.forget()
        if warm:
            threading.Thread(target=d.log.warm, name="rewarm", daemon=True).start()

    @app.get("/api/maintenance")
    def list_windows() -> list[Window]:
        """List maintenance windows, earliest first."""
        return operations.windows()

    @app.post("/api/maintenance", status_code=201)
    def add_window(window: WindowIn) -> Window:
        """Plan a maintenance window."""
        check_targets(window)
        try:
            saved = operations.save_window(window)
        except OperationsFull as e:
            raise HTTPException(409, str(e)) from e
        changed_plans()
        return saved

    @app.put("/api/maintenance/{window_id}")
    def change_window(window_id: str, window: WindowIn) -> Window:
        """Change a maintenance window."""
        check_targets(window)
        try:
            saved = operations.save_window(window, window_id)
        except KeyError as e:
            raise HTTPException(404, f"No maintenance window {window_id!r}") from e
        changed_plans()
        return saved

    @app.delete("/api/maintenance/{window_id}", status_code=204)
    def delete_window(window_id: str) -> None:
        """Delete a maintenance window."""
        if not operations.delete_window(window_id):
            raise HTTPException(404, f"No maintenance window {window_id!r}")
        changed_plans()

    @app.post("/api/acks", status_code=201)
    def acknowledge(ack: AckIn) -> Ack:
        """Acknowledge a problem there is now, with a note."""
        monitor = docs.monitor
        present = {p.id: p for p in monitor.moment(monitor.now()).problems.problems}
        if ack.problem not in present:
            raise HTTPException(404, f"No problem {ack.problem!r} now")
        title = present[ack.problem].title
        return operations.acknowledge(ack, datetime.now(UTC), title)

    @app.delete("/api/acks", status_code=204)
    def unacknowledge(problem: str) -> None:
        """Withdraw a problem's acknowledgement."""
        if not operations.unacknowledge(problem):
            raise HTTPException(404, f"{problem!r} is not acknowledged")

    def need_directory() -> tuple[Directory, Ownership]:
        """The on-call directory and who owns what, or a 404 saying where it goes."""
        owners = docs.owners
        if directory is None or owners is None:
            raise HTTPException(
                404,
                f"No on-call directory: put one at {oncall_path.name}, "
                "or give --oncall",
            )
        return directory, owners

    @app.get("/api/oncall")
    def get_oncall(at: datetime | None = None) -> OnCall:
        """Return who is on call for every team, now or at an earlier moment,
        and how to reach them and the carriers."""
        found, _ = need_directory()
        now = datetime.now(UTC)
        when = now if at is None else in_history(at, now)
        return on_call(found, when, operations.covers())

    @app.get("/api/ownership")
    def get_ownership() -> Ownership:
        """Return the team that owns each site, device, and link."""
        _, found = need_directory()
        return found

    @app.post("/api/pages", status_code=201)
    def add_page(page: PageIn) -> Page:
        """Page the team that owns a problem there is now.

        Nothing is sent: the page is recorded, and escalates on paper.
        """
        _, found = need_directory()
        monitor = docs.monitor
        present = {p.id: p for p in monitor.moment(monitor.now()).problems.problems}
        problem = present.get(page.problem)
        if problem is None:
            raise HTTPException(404, f"No problem {page.problem!r} now")
        team = found.owner(problem.target)
        if team is None:
            raise HTTPException(
                409, "No team owns this: add a route for it to the on-call directory"
            )
        return operations.page(page, team, datetime.now(UTC), problem.title)

    @app.delete("/api/pages", status_code=204)
    def withdraw_page(problem: str) -> None:
        """Withdraw a problem's page."""
        if not operations.unpage(problem):
            raise HTTPException(404, f"{problem!r} has not been paged")

    @app.post("/api/covers", status_code=201)
    def add_cover(cover: CoverIn) -> Cover:
        """Put someone on call in place of a team's primary for a while."""
        found, _ = need_directory()
        if found.team(cover.team) is None:
            raise HTTPException(422, f"No team {cover.team!r}")
        if cover.person not in {p.id for p in found.people}:
            raise HTTPException(422, f"No person {cover.person!r}")
        try:
            return operations.save_cover(cover)
        except OperationsFull as e:
            raise HTTPException(409, str(e)) from e

    @app.delete("/api/covers/{cover_id}", status_code=204)
    def delete_cover(cover_id: str) -> None:
        """Delete a cover."""
        if not operations.delete_cover(cover_id):
            raise HTTPException(404, f"No cover {cover_id!r}")

    @app.get("/api/changes")
    def get_changes() -> ChangeSet:
        """Return every fix accepted into the documentation, newest first."""
        return ChangeSet(changes=changes.changes()[::-1])

    def discovered(d: _Documented, at: datetime) -> Comparison:
        """The comparison in effect at a moment, with expected findings set aside."""
        return expecting(d.log.comparison(at), expected(changes.changes()), d.topology)

    def offered(d: _Documented, finding: str, expect: bool) -> tuple[Finding, Fix]:
        """A finding of the latest discovery run, and the fix it offers, or
        the change that marks it expected."""
        found = next(
            (f for f in discovered(d, datetime.now(UTC)).findings if f.id == finding),
            None,
        )
        if found is None:
            raise HTTPException(404, f"No finding {finding!r} in the latest run")
        if expect:
            if found.kind not in EXPECTABLE:
                raise HTTPException(
                    409, f"{found.title}: the documentation is wrong, so fix it"
                )
            return found, Fix(kind="expect", summary=f"Expect {found.title}")
        if found.fix is None:
            raise HTTPException(409, f"Discovery offers no fix for {found.title}")
        return found, found.fix

    @app.get("/api/review")
    def get_review(finding: str, expect: bool = False) -> Review:
        """Return what accepting the fix a finding of the latest discovery run
        offers would do now: to the ports involved, to redundancy, and to the
        problems there are. Or, to mark it expected, what Live reads now on
        the ports it is about."""
        d = docs
        found, fix = offered(d, finding, expect)
        now = d.monitor.now()
        readings = {
            (i.device, i.interface): i for i in d.state.snapshot(now).interfaces
        }
        if expect:
            about = [(p.device, p.interface) for p in [*found.documented, *found.seen]]
            if found.kind == "no-neighbors":
                device = found.devices[0]
                about = [
                    (e.device, e.interface)
                    for ln in d.network.links_of.get(device, [])
                    for e in (ln.a, ln.b)
                    if e.device == device
                ]
            return Review(
                finding=found,
                removes=[],
                adds=[],
                exposed={},
                restored=[],
                cut_off=[],
                cleared=[],
                raised=[],
                involved=[
                    PortNow(
                        device=dev,
                        interface=ifname,
                        reading=readings.get((dev, ifname)),
                    )
                    for dev, ifname in dict.fromkeys(about)
                    if dev in d.network.number
                ],
            )
        try:
            would = build(applied(d.topology, [fix]))
        except ChangeConflict as e:
            raise HTTPException(409, str(e)) from e
        old, new = ports(fix.before), ports(fix.after)
        was, will = d.network.reach(Failures()), would.network.reach(Failures())
        before = {p.title for p in d.monitor.moment(now).problems.problems}
        after = {p.title for p in would.monitor.moment(now).problems.problems}
        return Review(
            finding=found,
            removes=[
                PortNow(
                    device=dev, interface=ifname, reading=readings.get((dev, ifname))
                )
                for dev, ifname in old
                if (dev, ifname) not in new
            ],
            adds=[
                PortNow(
                    device=dev, interface=ifname, reading=readings.get((dev, ifname))
                )
                for dev, ifname in new
                if (dev, ifname) not in old
            ],
            exposed={
                k: list(v)
                for k, v in sorted(will.fragile.items())
                if k not in was.fragile
            },
            restored=sorted(k for k in was.fragile if k not in will.fragile),
            cut_off=sorted(was.reached - will.reached),
            cleared=sorted(before - after),
            raised=sorted(after - before),
        )

    @app.post("/api/changes", status_code=201)
    def accept_fix(change: ChangeIn) -> Change:
        """Accept the fix a finding of the latest discovery run offers into
        the documentation, which everything then follows; or mark the
        finding expected, which changes no link."""
        with changes.lock:
            found, fix = offered(docs, change.finding, change.expect)
            accepted = new_change(found, fix, change, datetime.now(UTC))
            if fix.kind == "expect":
                changes.save([*changes.changes(), accepted])
                return accepted
            try:
                document([*changes.changes(), accepted])
            except ChangeConflict as e:
                raise HTTPException(409, str(e)) from e
            return accepted

    @app.delete("/api/changes/{change_id}", status_code=204)
    def revert_change(change_id: str) -> None:
        """Take a fix back out of the documentation, or withdraw an expectation."""
        with changes.lock:
            kept = [c for c in changes.changes() if c.id != change_id]
            gone = [c for c in changes.changes() if c.id == change_id]
            if not gone:
                raise HTTPException(404, f"No change {change_id!r}")
            if gone[0].fix.kind == "expect":
                changes.save(kept)
                return
            try:
                document(kept)
            except ChangeConflict as e:
                raise HTTPException(
                    409, f"A later change depends on it; revert that first ({e})"
                ) from e

    @app.get("/api/layouts")
    def list_layouts() -> list[LayoutSummary]:
        """List saved layouts, most recently saved first."""
        return store.summaries()

    @app.get("/api/layouts/{name}")
    def get_layout(name: NameParam) -> SavedLayout:
        """Return one saved layout."""
        layout = store.get(name)
        if layout is None:
            raise HTTPException(404, f"No saved layout named {name!r}")
        return layout

    @app.put("/api/layouts/{name}")
    def put_layout(name: NameParam, layout: LayoutIn) -> SavedLayout:
        """Save a layout, replacing any with the same name."""
        try:
            return store.put(name, layout)
        except LayoutStoreFull as e:
            raise HTTPException(409, str(e)) from e

    @app.delete("/api/layouts/{name}", status_code=204)
    def delete_layout(name: NameParam) -> None:
        """Delete a saved layout."""
        if not store.delete(name):
            raise HTTPException(404, f"No saved layout named {name!r}")

    if web_dir is not None:
        app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")
    # Once everything it calls is defined.
    start(docs)
    return app


def app_from_env() -> FastAPI:
    """App factory for uvicorn, configured by the CLI through the environment.

    Uvicorn's reloader re-imports the app in a fresh process, so settings
    travel in ``SUNSTONE_TOPOLOGY``, ``SUNSTONE_WEB_DIR``,
    ``SUNSTONE_LAYOUTS``, ``SUNSTONE_OPERATIONS``, ``SUNSTONE_CHANGES``,
    ``SUNSTONE_HANDOVERS``, and ``SUNSTONE_ONCALL`` rather than as arguments.

    Returns:
        The FastAPI application.

    Raises:
        KeyError: If ``SUNSTONE_TOPOLOGY`` is not set.
        TopologyError: If the topology file is missing or invalid.
        ChangesError: If the changes no longer apply to the topology file.
        HandoverError: If the saved handovers file cannot be read.
        DirectoryError: If the on-call directory is invalid, or was named
            and is missing.
    """
    web_dir = os.environ.get("SUNSTONE_WEB_DIR")
    layouts = os.environ.get("SUNSTONE_LAYOUTS")
    operations = os.environ.get("SUNSTONE_OPERATIONS")
    changes = os.environ.get("SUNSTONE_CHANGES")
    handovers = os.environ.get("SUNSTONE_HANDOVERS")
    oncall = os.environ.get("SUNSTONE_ONCALL")
    return create_app(
        Path(os.environ["SUNSTONE_TOPOLOGY"]),
        Path(web_dir) if web_dir else None,
        Files(
            layouts=Path(layouts) if layouts else None,
            operations=Path(operations) if operations else None,
            changes=Path(changes) if changes else None,
            handovers=Path(handovers) if handovers else None,
            oncall=Path(oncall) if oncall else None,
        ),
    )
