"""Command line: ``sunstone --topology FILE [options]``; ``--help`` lists them."""

import argparse
import os
from pathlib import Path

import uvicorn


def main() -> None:
    """Parse arguments and run the API server until interrupted.

    Raises:
        SystemExit: On invalid arguments.
    """
    parser = argparse.ArgumentParser(prog="sunstone", description=__doc__)
    parser.add_argument("--topology", type=Path, required=True)
    parser.add_argument("--web-dir", type=Path, help="built frontend to serve at /")
    parser.add_argument(
        "--layouts",
        type=Path,
        help="saved layouts file (default: beside the topology, NAME.layouts.json)",
    )
    parser.add_argument(
        "--operations",
        type=Path,
        help="maintenance windows and acknowledgements file "
        "(default: beside the topology, NAME.operations.json)",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--reload", action="store_true", help="restart when code or topology changes"
    )
    args = parser.parse_args()

    os.environ["SUNSTONE_TOPOLOGY"] = str(args.topology.resolve())
    if args.web_dir:
        os.environ["SUNSTONE_WEB_DIR"] = str(args.web_dir.resolve())
    if args.layouts:
        os.environ["SUNSTONE_LAYOUTS"] = str(args.layouts.resolve())
    if args.operations:
        os.environ["SUNSTONE_OPERATIONS"] = str(args.operations.resolve())
    uvicorn.run(
        "sunstone.api:app_from_env",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
        reload_dirs=[str(Path(__file__).parent), str(args.topology.resolve().parent)],
        reload_includes=["*.py", "*.yaml"],
    )
