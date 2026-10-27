"""HTTP API, plus the built web UI served from the same origin."""

import os
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi import Path as PathParam
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict

from sunstone.impact import Network, WhatIf
from sunstone.layouts import (
    MAX_NAME,
    Center,
    LayoutIn,
    LayoutStore,
    LayoutStoreFull,
    LayoutSummary,
    SavedLayout,
)
from sunstone.live import DeviceHistory, EventLog, NetworkState, StateSource
from sunstone.loader import load_topology
from sunstone.model import Topology
from sunstone.monitor import POLL, Monitor
from sunstone.operations import (
    OperationsFull,
    OperationsStore,
    Window,
    WindowIn,
    accounted_for,
    event_planned,
)
from sunstone.problems import Ack, AckIn, ProblemList
from sunstone.simulate import SimulatedState

NameParam = Annotated[str, PathParam(min_length=1, max_length=MAX_NAME)]


class WhatIfQuestion(BaseModel):
    """Devices, sites, and links to suppose failed, and the moment whose live
    state to start from (none for the healthy network)."""

    model_config = ConfigDict(extra="forbid")

    failures: list[Center]
    at: datetime | None = None


@dataclass(frozen=True)
class Files:
    """Where the server keeps what people save; None for a file beside the
    topology, such as ``small.layouts.json`` for ``small.yaml``."""

    layouts: Path | None = None
    operations: Path | None = None
    """Maintenance windows and acknowledgements."""

    def path(self, topology_path: Path, kind: str) -> Path:
        """The file for one kind of saved data.

        Args:
            topology_path: The topology file.
            kind: ``layouts`` or ``operations``.

        Returns:
            The file given for it, or one beside the topology.

        Raises:
            None
        """
        given = self.layouts if kind == "layouts" else self.operations
        return given or topology_path.with_name(f"{topology_path.stem}.{kind}.json")


def create_app(
    topology_path: Path,
    web_dir: Path | None = None,
    files: Files | None = None,
    state_source: StateSource | None = None,
    warm: bool = True,
) -> FastAPI:
    """Build the app around one topology file, loaded once at startup.

    Args:
        topology_path: Topology YAML file to serve.
        web_dir: Built frontend to serve at ``/``, or None for API only
            (the Vite dev server serves the UI during development).
        files: Where saved layouts, maintenance windows, and
            acknowledgements go, or None for files beside the topology.
        state_source: Where live state comes from, or None for simulated
            state (there are no real sources yet), which acts out planned
            maintenance.
        warm: Work out the day's events and the present moment in the
            background at startup, and each new moment as it begins while
            anyone is watching, so viewers do not wait.

    Returns:
        The FastAPI application.

    Raises:
        TopologyError: If the topology file is missing or invalid.
        OperationsError: If the operations file exists but cannot be read.
    """
    topology = load_topology(topology_path)
    files = files or Files()
    store = LayoutStore(files.path(topology_path, "layouts"))
    network = Network(topology)
    operations = OperationsStore(files.path(topology_path, "operations"), network)
    state = state_source or SimulatedState(topology, plans=operations)
    monitor = Monitor(network, state)
    if warm:
        threading.Thread(target=monitor.warm, name="warm", daemon=True).start()
        never = threading.Event()
        threading.Thread(
            target=monitor.keep_ahead, args=(never,), name="ahead", daemon=True
        ).start()
    app = FastAPI(title="Sunstone")
    # Topology and state run to megabytes for large networks and compress well.
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    @app.get("/api/topology")
    def get_topology() -> Topology:
        """Return the whole topology."""
        return topology

    def in_history(at: datetime, now: datetime) -> datetime:
        """Check that a requested moment is one the source keeps."""
        if at.tzinfo is None:
            raise HTTPException(
                422, "Give the time with a zone, as in 2026-10-27T15:00Z"
            )
        if not now - state.retention <= at <= now:
            hours = state.retention.total_seconds() / 3600
            raise HTTPException(
                422, f"The time must be within the last {hours:g} hours"
            )
        return at

    def moment_at(at: datetime | None) -> datetime:
        """The moment asked for, or the present one."""
        return monitor.now() if at is None else in_history(at, datetime.now(UTC))

    @app.get("/api/state", response_model=NetworkState)
    def get_state(request: Request, at: datetime | None = None) -> Response:
        """Return the state of everything monitored, as of now or an earlier moment.

        The present is rounded down to the polling interval, and each moment
        is served from one cached, already compressed copy.
        """
        when = moment_at(at)
        moment = monitor.moment(when)
        if at is None:
            # Acknowledgements last until their problem clears.
            present = {p.id for p in moment.problems.problems}
            operations.clear_acks(present, when)
        if "gzip" in request.headers.get("accept-encoding", ""):
            return Response(
                moment.gzipped,
                media_type="application/json",
                headers={"Content-Encoding": "gzip", "Vary": "Accept-Encoding"},
            )
        return Response(moment.body, media_type="application/json")

    @app.get("/api/problems")
    def get_problems(at: datetime | None = None) -> ProblemList:
        """Return the problems in the state as of now or an earlier moment,
        with the maintenance that accounts for each and who is on it.

        Pass the ``generated_at`` of the state being shown, so the two match.
        """
        when = moment_at(at)
        found = monitor.moment(when).problems
        windows = [w for w in operations.windows() if w.start <= when < w.end]
        # The present is rounded down; acknowledgements made since still count.
        now = datetime.now(UTC)
        as_of = now if now - when < POLL else when
        acks = {a.problem: a for a in operations.acks() if a.active(as_of)}
        problems = [
            p.model_copy(
                update={
                    "planned": accounted_for(p, windows, network),
                    "ack": acks.get(p.id),
                }
            )
            for p in found.problems
        ]
        return ProblemList(at=found.at, problems=problems)

    @app.post("/api/impact")
    def post_impact(question: WhatIfQuestion) -> WhatIf:
        """Return what failing some devices, sites, and links would do."""
        before = None if question.at is None else monitor.moment(moment_at(question.at))
        failures = network.failures_of(question.failures)
        return network.what_if(failures, before.failures if before else None)

    @app.get("/api/events")
    def get_events() -> EventLog:
        """Return the changes the source saw over its whole history."""
        now = datetime.now(UTC)
        since = now - state.retention
        events = state.events(since, now)
        work = {at: operations.planned_at(at) for at in {e.at for e in events}}
        events = [
            e.model_copy(update={"planned": event_planned(e, work[e.at], network)})
            for e in events
        ]
        return EventLog(since=since, until=now, events=events)

    @app.get("/api/history/{device}")
    def get_history(device: str) -> DeviceHistory:
        """Return one device's readings over the source's whole history."""
        now = datetime.now(UTC)
        history = state.history(device, now - state.retention, now)
        if history is None:
            raise HTTPException(404, f"{device!r} is not monitored")
        return history

    def check_targets(window: WindowIn) -> None:
        """Refuse a window naming devices, sites, or links that do not exist."""
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
        monitor.forget()

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
        when = monitor.now()
        present = {p.id for p in monitor.moment(when).problems.problems}
        if ack.problem not in present:
            raise HTTPException(404, f"No problem {ack.problem!r} now")
        return operations.acknowledge(ack, datetime.now(UTC))

    @app.delete("/api/acks", status_code=204)
    def unacknowledge(problem: str) -> None:
        """Withdraw a problem's acknowledgement."""
        if not operations.unacknowledge(problem):
            raise HTTPException(404, f"{problem!r} is not acknowledged")

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
    return app


def app_from_env() -> FastAPI:
    """App factory for uvicorn, configured by the CLI through the environment.

    Uvicorn's reloader re-imports the app in a fresh process, so settings
    travel in ``SUNSTONE_TOPOLOGY``, ``SUNSTONE_WEB_DIR``,
    ``SUNSTONE_LAYOUTS``, and ``SUNSTONE_OPERATIONS`` rather than as
    arguments.

    Returns:
        The FastAPI application.

    Raises:
        KeyError: If ``SUNSTONE_TOPOLOGY`` is not set.
        TopologyError: If the topology file is missing or invalid.
    """
    web_dir = os.environ.get("SUNSTONE_WEB_DIR")
    layouts = os.environ.get("SUNSTONE_LAYOUTS")
    operations = os.environ.get("SUNSTONE_OPERATIONS")
    return create_app(
        Path(os.environ["SUNSTONE_TOPOLOGY"]),
        Path(web_dir) if web_dir else None,
        Files(
            layouts=Path(layouts) if layouts else None,
            operations=Path(operations) if operations else None,
        ),
    )
