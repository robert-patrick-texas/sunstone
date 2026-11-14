# Copyright 2026 Robert Patrick
# SPDX-License-Identifier: Apache-2.0
"""Tests for the release tables: which files count, and the Versions columns.

Dependencies:
    pytest: Test runner.
    release_tables: The module under test, imported from this directory.

Safety:
    Pure functions only; nothing runs git, cloc, or uv.

Example:
    $ uv run pytest tools/release-tables
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from release_tables import area_of, loc_table, previous_versions, versions_table  # noqa: E402

CHANGELOG = """# Changelog

## 0.13.0

### Fixed

- Something.

## 0.12.0

- Rules.

### Lines of Code

| Area | Files | Code | Comments | Blank |
|---|--:|--:|--:|--:|
| Backend | 1 | 2 | 3 | 4 |

### Versions

| Component | Current (0.12.0) |
|---|---|
| Sunstone | 0.12.0 |
| Python | 3.15.2 |

## 0.11.0

### Versions

| Component | Current (0.11.0) |
|---|---|
| Sunstone | 0.11.0 |
"""


@pytest.mark.parametrize(
    ("path", "area"),
    [
        ("backend/src/sunstone/api.py", "Backend"),
        ("backend/pyproject.toml", "Backend"),
        ("backend/tests/test_api.py", "Backend tests"),
        ("frontend/src/lib/status.test.ts", "Web UI tests"),
        ("frontend/src/lib/test-fixture.ts", "Web UI tests"),
        ("frontend/scripts/bundled-packages.test.ts", "Web UI tests"),
        ("frontend/e2e/map.spec.ts", "Browser tests and benchmarks"),
        ("frontend/playwright.config.ts", "Browser tests and benchmarks"),
        ("frontend/src/lib/DetailsPanel.svelte", "Web UI"),
        ("packaging/build-deb.sh", "Packaging and CI"),
        (".github/workflows/ci.yml", "Packaging and CI"),
        ("tools/release/release.py", "Tools"),
        ("Makefile", "Tools"),
        ("README.md", "Documentation"),
        ("backend/uv.lock", None),
        ("frontend/package-lock.json", None),
        ("frontend/src/lib/api/schema.d.ts", None),
        ("data/sample/small.yaml", None),
        ("LICENSE", None),
    ],
)
def test_each_file_counts_in_one_area_and_generated_ones_in_none(
    path: str, area: str | None
) -> None:
    """First-party files fall in an area; generated and external text do not.

    Args:
        path: A tracked path.
        area: The area it should count in.

    Returns:
        None

    Raises:
        AssertionError: If the file lands elsewhere.
    """
    assert area_of(path) == area


def test_loc_table_totals_every_area_and_says_how_it_was_counted() -> None:
    """The total row sums the areas, and the statement names cloc.

    Args:
        None

    Returns:
        None

    Raises:
        AssertionError: If the total or the statement is wrong.
    """
    rows = [
        ("Backend", {"nFiles": 2, "blank": 1, "comment": 3, "code": 1000}),
        ("Tools", {"nFiles": 1, "blank": 0, "comment": 1, "code": 500}),
    ]
    table = loc_table(rows, "2.06")
    assert "| Backend | 2 | 1,000 | 3 | 1 |" in table
    assert "| **Total** | **3** | **1,500** | **4** | **1** |" in table
    assert "Counted with cloc 2.06" in table
    assert "No dependencies or external components are included" in table


def test_previous_versions_come_from_the_newest_earlier_table() -> None:
    """The release's own section is skipped; the next table down is used.

    Args:
        None

    Returns:
        None

    Raises:
        AssertionError: If the wrong section's table is read.
    """
    assert previous_versions(CHANGELOG, "0.13.0") == (
        "0.12.0",
        {"Sunstone": "0.12.0", "Python": "3.15.2"},
    )
    assert previous_versions("## 0.1.0\n\n- First.\n", "0.2.0") is None


def test_versions_table_has_one_column_first_then_old_and_new() -> None:
    """Without an earlier table, one column; after, changes are in bold.

    Args:
        None

    Returns:
        None

    Raises:
        AssertionError: If a column or the bold marking is wrong.
    """
    current = {"Sunstone": "0.13.0", "Python": "3.15.2", "Ruff": "0.17.5"}
    first = versions_table("0.13.0", current, None)
    assert "| Component | Current (0.13.0) |" in first
    assert "| Python | 3.15.2 |" in first
    previous = ("0.12.0", {"Sunstone": "0.12.0", "Python": "3.15.2"})
    later = versions_table("0.13.0", current, previous)
    assert "| Component | Old (0.12.0) | New (0.13.0) |" in later
    assert "| Sunstone | 0.12.0 | **0.13.0** |" in later
    assert "| Python | 3.15.2 | 3.15.2 |" in later
    assert "| Ruff | none | **0.17.5** |" in later


def test_bold_in_an_earlier_table_is_not_carried_into_the_old_column() -> None:
    """A version bold in the last table reads as a plain version.

    Args:
        None

    Returns:
        None

    Raises:
        AssertionError: If the old column keeps the bold.
    """
    text = "## 0.13.0\n\n### Versions\n\n| Component | Old (0.12.0) | New (0.13.0) |\n"
    text += "|---|---|---|\n| Sunstone | 0.12.0 | **0.13.0** |\n"
    assert previous_versions(text, "0.14.0") == ("0.13.0", {"Sunstone": "0.13.0"})
