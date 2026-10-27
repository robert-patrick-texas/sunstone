"""HTTP API, plus the built web UI served from the same origin."""

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from sunstone.loader import load_topology
from sunstone.model import Topology


def create_app(topology_path: Path, web_dir: Path | None = None) -> FastAPI:
    """Build the app around one topology file, loaded once at startup.

    Args:
        topology_path: Topology YAML file to serve.
        web_dir: Built frontend to serve at ``/``, or None for API only
            (the Vite dev server serves the UI during development).

    Returns:
        The FastAPI application.

    Raises:
        TopologyError: If the topology file is missing or invalid.
    """
    topology = load_topology(topology_path)
    app = FastAPI(title="Sunstone")

    @app.get("/api/topology")
    def get_topology() -> Topology:
        """Return the whole topology."""
        return topology

    if web_dir is not None:
        app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")
    return app


def app_from_env() -> FastAPI:
    """App factory for uvicorn, configured by the CLI through the environment.

    Uvicorn's reloader re-imports the app in a fresh process, so settings
    travel in ``SUNSTONE_TOPOLOGY`` and ``SUNSTONE_WEB_DIR`` rather than as
    arguments.

    Returns:
        The FastAPI application.

    Raises:
        KeyError: If ``SUNSTONE_TOPOLOGY`` is not set.
        TopologyError: If the topology file is missing or invalid.
    """
    web_dir = os.environ.get("SUNSTONE_WEB_DIR")
    return create_app(
        Path(os.environ["SUNSTONE_TOPOLOGY"]), Path(web_dir) if web_dir else None
    )
