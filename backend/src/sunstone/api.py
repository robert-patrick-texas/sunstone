"""HTTP API, plus the built web UI served from the same origin."""

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException
from fastapi import Path as PathParam
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles

from sunstone.layouts import (
    MAX_NAME,
    LayoutIn,
    LayoutStore,
    LayoutStoreFull,
    LayoutSummary,
    SavedLayout,
)
from sunstone.live import NetworkState, StateSource
from sunstone.loader import load_topology
from sunstone.model import Topology
from sunstone.simulate import SimulatedState

NameParam = Annotated[str, PathParam(min_length=1, max_length=MAX_NAME)]


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

    Returns:
        The FastAPI application.

    Raises:
        TopologyError: If the topology file is missing or invalid.
    """
    topology = load_topology(topology_path)
    store = LayoutStore(layouts_path or default_layouts_path(topology_path))
    state = state_source or SimulatedState(topology)
    app = FastAPI(title="Sunstone")
    # Topology and state run to megabytes for large networks and compress well.
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    @app.get("/api/topology")
    def get_topology() -> Topology:
        """Return the whole topology."""
        return topology

    @app.get("/api/state")
    def get_state() -> NetworkState:
        """Return the live state of everything monitored, as of now."""
        return state.snapshot(datetime.now(UTC))

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
