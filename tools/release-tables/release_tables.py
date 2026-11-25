# Copyright 2026 Robert Patrick
# SPDX-License-Identifier: Apache-2.0
"""Print the Lines of Code and Versions tables that end each release's notes.

Every ``CHANGELOG.md`` section ends with these two tables
(docs/RELEASING.md). Lines of code are counted with ``cloc`` over the files git
tracks that are Sunstone's own, by area, leaving out generated files. The
versions are what the build installs: taken from ``backend/uv.lock``,
``frontend/package-lock.json``, ``frontend/.node-version``, and the
builder's ``packaging/Dockerfile``, never from the ``>=`` ranges, and
Python from the backend's environment. When an earlier changelog section
has a Versions table, its versions are the old column and this release's
the new one, in bold where they changed.

Dependencies:
    json, re, subprocess, tomllib: Read the lockfiles and run ``git``,
        ``cloc``, and ``uv``.

Safety:
    Read-only: it runs ``git ls-files``, ``cloc``, and ``uv run python``
    with argument lists, never a shell, and prints Markdown to paste into
    the changelog.

Example:
    $ uv run tools/release-tables/release_tables.py
"""

import argparse
import json
import re
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Callable, Sequence
from pathlib import Path

GENERATED = (
    "backend/uv.lock",
    "frontend/package-lock.json",
    "frontend/openapi.json",
    "frontend/src/lib/api/schema.d.ts",
    "packaging/build-constraints.txt",
    "data/sample/",
)
"""Tracked files that tools write, not people: lockfiles, the OpenAPI schema
and the types made from it, the build pins, and mockgen's sample data."""


def _is_test(path: str) -> bool:
    """Whether a web UI file is a unit test or its fixture."""
    return path.endswith(".test.ts") or path == "frontend/src/lib/test-fixture.ts"


AREAS: tuple[tuple[str, Callable[[str], bool]], ...] = (
    ("Backend", lambda p: p.startswith("backend/") and not p.startswith("backend/tests/")),
    ("Backend tests", lambda p: p.startswith("backend/tests/")),
    ("Web UI tests", lambda p: p.startswith("frontend/") and _is_test(p)),
    (
        "Browser tests and benchmarks",
        lambda p: p.startswith(("frontend/e2e/", "frontend/bench/", "frontend/playwright")),
    ),
    ("Web UI", lambda p: p.startswith("frontend/")),
    ("Packaging and CI", lambda p: p.startswith(("packaging/", ".github/"))),
    ("Tools", lambda p: p.startswith("tools/") or p == "Makefile"),
    ("Documentation", lambda p: p.endswith(".md")),
)
"""Each tracked file counts in the first area that takes it."""


def area_of(path: str) -> str | None:
    """Name the area a tracked file counts in.

    Args:
        path: Path relative to the repository root, as ``git ls-files``
            prints it.

    Returns:
        str | None: The area, or ``None`` for a generated file or one in no
        area (``VERSION``, ``LICENSE``).

    Raises:
        None
    """
    if path.startswith(GENERATED):
        return None
    return next((name for name, takes in AREAS if takes(path)), None)


def count_lines(root: Path) -> list[tuple[str, dict[str, int]]]:
    """Count each area's files, blank lines, comments, and code with cloc.

    Args:
        root: Repository root.

    Returns:
        list[tuple[str, dict[str, int]]]: Each area in ``AREAS`` order with
        cloc's ``nFiles``, ``blank``, ``comment``, and ``code``. Files cloc
        does not recognize as a language are not counted.

    Raises:
        subprocess.CalledProcessError: If ``git`` or ``cloc`` fails.
    """
    tracked = _run(["git", "ls-files"], root).splitlines()
    rows = []
    for name, _ in AREAS:
        files = [p for p in tracked if area_of(p) == name]
        with tempfile.NamedTemporaryFile("w", suffix=".txt") as listing:
            listing.write("\n".join(files) + "\n")
            listing.flush()
            out = _run(["cloc", "--quiet", "--json", f"--list-file={listing.name}"], root)
        total = json.loads(out).get("SUM", {}) if out.strip() else {}
        rows.append(
            (name, {k: int(total.get(k, 0)) for k in ("nFiles", "blank", "comment", "code")})
        )
    return rows


def loc_table(rows: list[tuple[str, dict[str, int]]], cloc_version: str) -> str:
    """Render the Lines of Code table and the statement under it.

    Args:
        rows: Output of ``count_lines``.
        cloc_version: ``cloc --version``.

    Returns:
        str: Markdown, starting with its ``### Lines of Code`` heading.

    Raises:
        None
    """
    keys = ("nFiles", "code", "comment", "blank")
    lines = [
        "### Lines of Code",
        "",
        "| Area | Files | Code | Comments | Blank |",
        "|---|--:|--:|--:|--:|",
    ]
    lines += [f"| {name} | " + " | ".join(f"{c[k]:,}" for k in keys) + " |" for name, c in rows]
    totals = [sum(c[k] for _, c in rows) for k in keys]
    lines.append("| **Total** | " + " | ".join(f"**{t:,}**" for t in totals) + " |")
    lines += [
        "",
        f"Counted with cloc {cloc_version} over the files in the repository that are"
        " Sunstone's own. No dependencies or external components are included:"
        " nothing vendored or brought in from elsewhere, such as npm or Python packages"
        " or the build images, and no generated files (lockfiles, the OpenAPI schema"
        " and the types made from it, the build pins, and the sample topologies).",
    ]
    return "\n".join(lines)


def current_versions(root: Path) -> dict[str, str]:
    """Gather the version of Sunstone and of each prominent component.

    Args:
        root: Repository root.

    Returns:
        dict[str, str]: Component name to version, in table order.

    Raises:
        subprocess.CalledProcessError: If the backend's Python cannot run.
        KeyError: If a listed package is missing from its lockfile.
    """
    uv_lock = tomllib.loads((root / "backend/uv.lock").read_text())
    py = {p["name"]: p["version"] for p in uv_lock["package"] if "version" in p}
    npm = json.loads((root / "frontend/package-lock.json").read_text())["packages"]
    dockerfile = (root / "packaging/Dockerfile").read_text()

    def js(name: str) -> str:
        return npm[f"node_modules/{name}"]["version"]

    def pinned(pattern: str) -> str:
        match = re.search(pattern, dockerfile, re.MULTILINE)
        return match.group(1) if match else "?"

    python = _run(
        ["uv", "run", "python", "-c", "import platform; print(platform.python_version())"],
        root / "backend",
    ).strip()
    return {
        "Sunstone": (root / "VERSION").read_text().strip(),
        "Python": python,
        "FastAPI": py["fastapi"],
        "Starlette": py["starlette"],
        "Pydantic": py["pydantic"],
        "Uvicorn": py["uvicorn"],
        "PyYAML": py["pyyaml"],
        "Node.js (builds the web UI)": (root / "frontend/.node-version").read_text().strip(),
        "Svelte": js("svelte"),
        "SvelteKit": js("@sveltejs/kit"),
        "Vite": js("vite"),
        "TypeScript": js("typescript"),
        "MapLibre GL JS": js("maplibre-gl"),
        "Cytoscape.js": js("cytoscape"),
        "pytest": py["pytest"],
        "Ruff": py["ruff"],
        "ty": py["ty"],
        "Vitest": js("vitest"),
        "Playwright": js("@playwright/test"),
        "uv (package build)": pinned(r"astral-sh/uv:([^@\s]+)"),
        "nfpm (package build)": pinned(r"nfpm@v([^\s]+)"),
        "Ubuntu (package target)": pinned(r"^ARG BASE_IMAGE=ubuntu:(\S+)"),
    }


def previous_versions(changelog: str, version: str) -> tuple[str, dict[str, str]] | None:
    """Find the newest Versions table in a section older than ``version``.

    Args:
        changelog: ``CHANGELOG.md`` text.
        version: The version being released, whose own section is skipped.

    Returns:
        tuple[str, dict[str, str]] | None: That section's version and its
        table, component to version (the last column, without bold), or
        ``None`` when no earlier section has one.

    Raises:
        None
    """
    section: str | None = None
    in_table = False
    found: dict[str, str] = {}
    for line in changelog.splitlines():
        heading = re.match(r"^##\s+\[?v?(\S+?)\]?(?:\s|$)", line)
        if heading:
            if found:
                break
            section, in_table = heading.group(1), False
        elif line.startswith("### "):
            if found:
                break
            in_table = section not in (None, version) and line.strip() == "### Versions"
        elif in_table and line.startswith("| ") and not line.startswith("| Component"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            found[cells[0]] = cells[-1].strip("*")
    return (section, found) if found and section else None


def versions_table(
    version: str, current: dict[str, str], previous: tuple[str, dict[str, str]] | None
) -> str:
    """Render the Versions table: one column, or old and new with changes in bold.

    Args:
        version: The version being released.
        current: Output of ``current_versions``.
        previous: Output of ``previous_versions``.

    Returns:
        str: Markdown, starting with its ``### Versions`` heading.

    Raises:
        None
    """
    lines = ["### Versions", ""]
    if previous is None:
        lines += [f"| Component | Current ({version}) |", "|---|---|"]
        lines += [f"| {name} | {v} |" for name, v in current.items()]
        return "\n".join(lines)
    since, old = previous
    lines += [f"| Component | Old ({since}) | New ({version}) |", "|---|---|---|"]
    for name, new in current.items():
        was = old.get(name, "none")
        lines.append(f"| {name} | {was} | {new if new == was else f'**{new}**'} |")
    return "\n".join(lines)


def _run(argv: Sequence[str], cwd: Path) -> str:
    """Run a command and return its standard output.

    Args:
        argv: Argument list, never passed through a shell.
        cwd: Directory to run it in.

    Returns:
        str: Standard output.

    Raises:
        subprocess.CalledProcessError: If the command exits non-zero.
    """
    return subprocess.run(argv, cwd=cwd, check=True, capture_output=True, text=True).stdout


def main(argv: Sequence[str] | None = None) -> int:
    """Print both tables for the version in ``VERSION``.

    Args:
        argv: Command-line arguments; ``sys.argv`` when ``None``.

    Returns:
        int: 0 on success.

    Raises:
        subprocess.CalledProcessError: If ``git``, ``cloc``, or ``uv`` fails.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path("."), help="repository root")
    root = parser.parse_args(argv).root.resolve()
    version = (root / "VERSION").read_text().strip()
    cloc_version = _run(["cloc", "--version"], root).strip()
    previous = previous_versions((root / "CHANGELOG.md").read_text(), version)
    print(loc_table(count_lines(root), cloc_version))
    print()
    print(versions_table(version, current_versions(root), previous))
    return 0


if __name__ == "__main__":
    sys.exit(main())
