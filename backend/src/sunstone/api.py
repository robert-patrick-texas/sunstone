"""HTTP API, plus the built web UI served from the same origin."""

import os
import threading
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
from sunstone.monitor import Monitor
from sunstone.problems import ProblemList
from sunstone.simulate import SimulatedState

NameParam = Annotated[str, PathParam(min_length=1, max_length=MAX_NAME)]


class WhatIfQuestion(BaseModel):
    """Devices, sites, and links to suppose failed, and the moment whose live
    state to start from (none for the healthy network)."""

    model_config = ConfigDict(extra="forbid")

    failures: list[Center]
    at: datetime | None = None


def default_layouts_path(topology_path: Path) -> Path:
    """Where a topology's saved layouts go unless told otherwise.

    Args:
        topology_path: The topology file, such as ``data/sample/small.yaml``.

    Returns:
        A file beside it, such as ``data/sample/small.layouts.json``.

    Raises:
        None
    """
    return topology_path.with_name(f"{topology_path.stem}.layouts.json")


def create_app(
    topology_path: Path,
    web_dir: Path | None = None,
    layouts_path: Path | None = None,
    state_source: StateSource | None = None,
    warm: bool = True,
) -> FastAPI:
    """Build the app around one topology file, loaded once at startup.

    Args:
        topology_path: Topology YAML file to serve.
        web_dir: Built frontend to serve at ``/``, or None for API only
            (the Vite dev server serves the UI during development).
        layouts_path: File for saved layouts, or None for the one beside the
            topology file.
        state_source: Where live state comes from, or None for simulated
            state (there are no real sources yet).
        warm: Work out the day's events and the present moment in the
            background at startup, and each new moment as it begins while
            anyone is watching, so viewers do not wait.

    Returns:
        The FastAPI application.

    Raises:
        TopologyError: If the topology file is missing or invalid.
    """
    topology = load_topology(topology_path)
    store = LayoutStore(layouts_path or default_layouts_path(topology_path))
    state = state_source or SimulatedState(topology)
    network = Network(topology)
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
        moment = monitor.moment(moment_at(at))
        if "gzip" in request.headers.get("accept-encoding", ""):
            return Response(
                moment.gzipped,
                media_type="application/json",
                headers={"Content-Encoding": "gzip", "Vary": "Accept-Encoding"},
            )
        return Response(moment.body, media_type="application/json")

    @app.get("/api/problems")
    def get_problems(at: datetime | None = None) -> ProblemList:
        """Return the problems in the state as of now or an earlier moment.

        Pass the ``generated_at`` of the state being shown, so the two match.
        """
        return monitor.moment(moment_at(at)).problems

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
        return EventLog(since=since, until=now, events=state.events(since, now))

    @app.get("/api/history/{device}")
    def get_history(device: str) -> DeviceHistory:
        """Return one device's readings over the source's whole history."""
        now = datetime.now(UTC)
        history = state.history(device, now - state.retention, now)
        if history is None:
            raise HTTPException(404, f"{device!r} is not monitored")
        return history

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
    travel in ``SUNSTONE_TOPOLOGY``, ``SUNSTONE_WEB_DIR``, and
    ``SUNSTONE_LAYOUTS`` rather than as arguments.

    Returns:
        The FastAPI application.

    Raises:
        KeyError: If ``SUNSTONE_TOPOLOGY`` is not set.
        TopologyError: If the topology file is missing or invalid.
    """
    web_dir = os.environ.get("SUNSTONE_WEB_DIR")
    layouts = os.environ.get("SUNSTONE_LAYOUTS")
    return create_app(
        Path(os.environ["SUNSTONE_TOPOLOGY"]),
        Path(web_dir) if web_dir else None,
        Path(layouts) if layouts else None,
    )
