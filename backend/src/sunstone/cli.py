"""Command line: ``sunstone serve|check|self-update``; ``--help`` lists them."""

import argparse
import os
import sys
from collections.abc import Callable
from dataclasses import replace
from importlib.metadata import version
from pathlib import Path

import uvicorn

from sunstone.api import Files, create_app
from sunstone.changes import ChangesError
from sunstone.handover import HandoverError
from sunstone.layouts import LayoutStoreError
from sunstone.loader import TopologyError, load_topology
from sunstone.oncall import DirectoryError, load_directory
from sunstone.operations import OperationsError
from sunstone.settings import DEFAULT_CONFIG, Settings, SettingsError, load_settings
from sunstone.update.updater import INSTALLED, UpdateError, Updater
from sunstone.update.versions import Version

KINDS = ("layouts", "operations", "changes", "handovers")


def main() -> None:
    """Parse arguments and run a command.

    Raises:
        SystemExit: On invalid arguments, and with each command's exit status.
    """
    parser = argparse.ArgumentParser(prog="sunstone", description=__doc__)
    parser.add_argument(
        "--version", action="version", version=f"sunstone {version('sunstone')}"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    serve = commands.add_parser("serve", help="run the server until interrupted")
    _site_options(serve, None)
    serve.add_argument("--web-dir", type=Path, help="built frontend to serve at /")
    serve.add_argument("--host", help="address to listen on (default 127.0.0.1)")
    serve.add_argument("--port", type=int, help="port to listen on (default 8000)")
    serve.add_argument(
        "--reload", action="store_true", help="restart when code or topology changes"
    )

    check = commands.add_parser(
        "check",
        help="load the settings, topology, on-call directory, and saved files, "
        "as the server would, and report",
    )
    _site_options(check, DEFAULT_CONFIG)

    update = commands.add_parser(
        "self-update",
        help="install a newer signed release, as root",
        description="Install the newest signed release if it is newer, after "
        "backing up the configuration and state; roll back if it fails.",
    )
    update.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help=f"settings file (default {DEFAULT_CONFIG})",
    )
    update.add_argument(
        "--check", action="store_true", help="only say whether a newer release exists"
    )
    update.add_argument("--yes", action="store_true", help="do not ask first")
    update.add_argument(
        "--version",
        dest="target",
        metavar="VERSION",
        help="install this release, even if older or the same",
    )
    update.add_argument(
        "--file", type=Path, help="install this package, copied here by hand"
    )
    update.add_argument("--sums", type=Path, help="its SHA256SUMS, with --file")
    update.add_argument("--sig", type=Path, help="SHA256SUMS.sig, with --file")
    update.add_argument(
        "--rollback",
        action="store_true",
        help="go back to the version the last update came from",
    )

    args = parser.parse_args()
    if args.command == "serve":
        _serve(args)
    elif args.command == "check":
        sys.exit(_check(args))
    else:
        if args.file and not (args.sums and args.sig):
            parser.error("--file needs --sums and --sig")
        sys.exit(_self_update(args))


def _site_options(parser: argparse.ArgumentParser, config: Path | None) -> None:
    """Options naming the topology and where saved files go."""
    default = f" (default {config}, if it exists)" if config else ""
    parser.add_argument(
        "--config",
        type=Path,
        default=config,
        help=f"settings file; options given here win over it{default}",
    )
    parser.add_argument("--topology", type=Path, help="topology file to serve")
    parser.add_argument(
        "--oncall",
        type=Path,
        help="on-call directory: teams, rotations, and what they own "
        "(default: beside the topology, NAME.oncall.yaml, if there is one)",
    )
    parser.add_argument(
        "--state-dir",
        type=Path,
        help="where saved files go, one per kind (default: beside the topology)",
    )
    for kind in KINDS:
        parser.add_argument(
            f"--{kind}",
            type=Path,
            help=f"{kind} file (default: NAME.{kind}.json beside the topology, "
            f"or {kind}.json in the state directory)",
        )


def _settings(path: Path | None) -> Settings:
    """The settings file's, or defaults when there is none to read."""
    if path is None or (path == DEFAULT_CONFIG and not path.exists()):
        return Settings()
    return load_settings(path)


def _site(args: argparse.Namespace) -> tuple[Settings, Path, Files]:
    """The settings, the topology, and where everything else is."""
    settings = _settings(args.config)
    topology = args.topology or settings.topology
    if topology is None:
        raise SettingsError("give --topology, or topology in a settings file")
    state = args.state_dir or settings.state_dir
    saved = {
        kind: getattr(args, kind) or (state / f"{kind}.json" if state else None)
        for kind in KINDS
    }
    return settings, topology, Files(**saved, oncall=args.oncall or settings.oncall)


def _serve(args: argparse.Namespace) -> None:
    """Run the API server until interrupted, configured through the environment."""
    try:
        settings, topology, files = _site(args)
    except SettingsError as e:
        sys.exit(f"sunstone serve: {e}")
    os.environ["SUNSTONE_TOPOLOGY"] = str(topology.resolve())
    if args.web_dir:
        os.environ["SUNSTONE_WEB_DIR"] = str(args.web_dir.resolve())
    for kind in (*KINDS, "oncall"):
        path = getattr(files, kind)
        if path:
            os.environ[f"SUNSTONE_{kind.upper()}"] = str(path.resolve())
    # Uvicorn's reloader imports the app afresh in another process, so the
    # settings travel in the environment.
    uvicorn.run(
        "sunstone.api:app_from_env",
        factory=True,
        host=args.host or settings.host,
        port=args.port or settings.port,
        reload=args.reload,
        reload_dirs=[str(Path(__file__).parent), str(topology.resolve().parent)],
        reload_includes=["*.py", "*.yaml"],
    )


def _check(args: argparse.Namespace) -> int:
    """Load everything as the server would, and say what was found."""
    try:
        _, topology, files = _site(args)
        create_app(topology, files=files, warm=False)
        network = load_topology(topology)
        print(
            f"sunstone check: {topology}: {len(network.sites)} sites, "
            f"{len(network.devices)} devices, {len(network.links)} links"
        )
        oncall = files.path(topology, "oncall")
        if files.oncall or oncall.exists():
            teams = len(load_directory(oncall, network).teams)
            print(f"sunstone check: {oncall}: {teams} teams")
        saved = sorted({str(files.path(topology, kind).parent) for kind in KINDS})
        print(f"sunstone check: saved files in {', '.join(saved)} are readable")
    except SettingsError as e:
        print(f"sunstone check: {e}", file=sys.stderr)
        return 2
    except (
        TopologyError,
        DirectoryError,
        ChangesError,
        OperationsError,
        HandoverError,
        LayoutStoreError,
    ) as e:
        print(f"sunstone check: {e}", file=sys.stderr)
        return 1
    print("sunstone check: ok")
    return 0


def _self_update(args: argparse.Namespace) -> int:
    """Check for, install, or roll back a release."""
    try:
        settings = _settings(args.config)
    except SettingsError as e:
        print(f"sunstone self-update: {e}", file=sys.stderr)
        return 2
    host = "127.0.0.1" if settings.host in ("", "0.0.0.0") else settings.host
    host = "[::1]" if host == "::" else f"[{host}]" if ":" in host else host
    updater = Updater(
        paths=replace(
            INSTALLED,
            config_file=args.config,
            state_dir=settings.state_dir or INSTALLED.state_dir,
        ),
        repository=settings.update.repository,
        installed=Version.parse(version("sunstone")),
        health_url=f"http://{host}:{settings.port}/api/version",
    )
    if args.check:
        return updater.check()
    if os.geteuid() != 0:
        print("sunstone self-update: run it as root: sudo sunstone self-update")
        return 2
    try:
        if args.rollback:
            return updater.rollback(_asker(args.yes))
        if args.file:
            return updater.install_files(
                args.file, args.sums, args.sig, _asker(args.yes)
            )
        target = Version.parse(args.target) if args.target else None
        return updater.update(target, _asker(args.yes))
    except ValueError as e:
        print(f"sunstone self-update: {e}", file=sys.stderr)
        return 2
    except UpdateError as e:
        print(f"sunstone self-update: {e}", file=sys.stderr)
        return 1


def _asker(yes: bool) -> Callable[[str], bool]:
    """Asks at the terminal, unless told yes; without a terminal, the answer is no."""

    def ask(question: str) -> bool:
        if yes:
            return True
        if not sys.stdin.isatty():
            print(f"{question} No terminal to ask at; pass --yes to go ahead.")
            return False
        return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")

    return ask
