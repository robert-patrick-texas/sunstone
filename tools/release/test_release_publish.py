# Copyright 2026 Robert Patrick
# SPDX-License-Identifier: Apache-2.0
"""Tests for release notes, catching up across versions never released, and the
tag/push/release commands (28.7 step 4).

Tagging and publishing cannot be undone, so the commands are checked as
data: the right tag name, the pre-release flag under the MVP rule, notes
taken from the matching changelog section, and nothing executed in a dry
run.

Dependencies:
    pytest: Test runner.
    release_publish, release_config: Modules under test.

Safety:
    A fake runner records calls; nothing is tagged, pushed, or released.

Example:
    $ uv run pytest tools/release/test_release_publish.py
"""

from pathlib import Path
from typing import Any

import pytest
from release_config import EXAMPLE, ReleaseConfig
from release_publish import (
    Notes,
    changelog_notes,
    publish,
    publish_commands,
    published_versions,
    release_notes,
)
from release_version import ReleaseVersion

CHANGES = """# Changelog

## Unreleased

- Not yet.

## [1.2.30] - 2026-11-01

- Wrong section.

## 1.2.3 - 2026-10-20

### Added

- New option.

## 1.2.2

- Older.
"""


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("1.2.3", "### Added\n\n- New option."),
        ("1.2.30", "- Wrong section."),
        ("1.2.2", "- Older."),
        ("9.9.9", None),
    ],
)
def test_changelog_notes_take_the_exact_section(version: str, expected: str | None) -> None:
    """VER-004: notes are the version's own section, never a neighbour's.

    Args:
        version: Version to look up.
        expected: Expected notes, or ``None`` when there is no section.

    Returns:
        None

    Raises:
        AssertionError: If the wrong text is extracted.
    """
    assert changelog_notes(CHANGES, version) == expected


def test_empty_section_counts_as_missing() -> None:
    """A heading with no notes would publish an empty release description.

    Args:
        None

    Returns:
        None

    Raises:
        AssertionError: If an empty section is accepted.
    """
    assert changelog_notes("## v2.0.0\n\n## 1.0.0\n- x\n", "2.0.0") is None


CATCH_UP = """# Changelog

## 0.6.0

- Six.

## 0.5.0 - 2026-11-07

- Five.

## [0.4.0]

- Four.

## 0.3.0

- Three.

## 0.2.0

- Two.
"""


def v(text: str) -> ReleaseVersion:
    """Parse a version, for short test data.

    Args:
        text: Version as written in ``VERSION``.

    Returns:
        ReleaseVersion: The version.

    Raises:
        release_version.VersionError: If the text is not a version.
    """
    return ReleaseVersion.parse(text)


def test_notes_after_the_last_release_are_its_own_section_alone() -> None:
    """With nothing skipped since the last release, the notes are unchanged.

    Args:
        None

    Returns:
        None

    Raises:
        AssertionError: If anything is added to the version's own section.
    """
    notes = release_notes(CATCH_UP, v("0.6.0"), [v("0.2.0"), v("0.5.0")])
    assert notes == Notes("- Six.", ("0.6.0",), "0.5.0")


def test_versions_never_released_are_carried_under_their_own_headings() -> None:
    """Every section since the last release comes along, newest first.

    Args:
        None

    Returns:
        None

    Raises:
        AssertionError: If a skipped version is missing, or a released one
            is carried again.
    """
    notes = release_notes(CATCH_UP, v("0.6.0"), [v("0.1.0"), v("0.2.0")])
    assert notes is not None
    assert (notes.versions, notes.since) == (("0.6.0", "0.5.0", "0.4.0", "0.3.0"), "0.2.0")
    assert notes.text == (
        "This release also carries the notes of 0.5.0, 0.4.0, and 0.3.0, never released"
        " on their own; the last release was 0.2.0.\n\n"
        "## 0.6.0\n\n- Six.\n\n"
        "## 0.5.0 - 2026-11-07\n\n- Five.\n\n"
        "## [0.4.0]\n\n- Four.\n\n"
        "## 0.3.0\n\n- Three."
    )


def test_release_candidates_count_as_releases() -> None:
    """A candidate released is the last release; one never released is carried.

    Args:
        None

    Returns:
        None

    Raises:
        AssertionError: If candidates are ordered or counted wrongly.
    """
    text = "## 1.0.0\n\n- Final.\n\n## 1.0.0-rc.2\n\n- Second.\n\n## 1.0.0-rc.1\n\n- First.\n"
    final = release_notes(text, v("1.0.0"), [v("0.9.0"), v("1.0.0-rc.1")])
    assert final is not None
    assert (final.versions, final.since) == (("1.0.0", "1.0.0-rc.2"), "1.0.0-rc.1")
    # A candidate comes before its final release, and catches up as one does.
    second = release_notes(text, v("1.0.0-rc.2"), [v("0.9.0")])
    assert second is not None
    assert second.versions == ("1.0.0-rc.2", "1.0.0-rc.1")


def test_without_an_earlier_release_every_older_section_is_carried() -> None:
    """Nothing was ever released, so every older section is new to operators.

    Args:
        None

    Returns:
        None

    Raises:
        AssertionError: If an older section is left out, or a lone one changed.
    """
    assert release_notes("## 0.1.0\n\n- First.\n", v("0.1.0"), []) == Notes(
        "- First.", ("0.1.0",), None
    )
    notes = release_notes(CATCH_UP, v("0.3.0"), [])
    assert notes is not None
    assert notes.versions == ("0.3.0", "0.2.0")
    assert notes.text.startswith(
        "This release also carries the notes of 0.2.0, never released on their own.\n\n## 0.3.0"
    )


def test_notes_need_the_versions_own_section() -> None:
    """Sections for older versions never stand in for a missing one.

    Args:
        None

    Returns:
        None

    Raises:
        AssertionError: If notes are built without the version's section.
    """
    assert release_notes(CATCH_UP, v("0.7.0"), [v("0.2.0")]) is None


def test_published_versions_are_the_remotes_version_tags(tmp_path: Path, fake_runner: Any) -> None:
    """Annotated tags are listed twice by ``ls-remote``; other tags are not versions.

    Args:
        tmp_path: Working directory for the fake runner.
        fake_runner: ``FakeRunner`` class from ``conftest.py``.

    Returns:
        None

    Raises:
        AssertionError: If a version is missed, repeated, or invented.
    """
    listed = (
        "a1\trefs/tags/v0.2.0\n"
        "a2\trefs/tags/v0.2.0^{}\n"
        "a3\trefs/tags/v0.1.0\n"
        "a4\trefs/tags/nightly\n"
        "a5\trefs/tags/v1.0\n"
    )
    fake = fake_runner(tmp_path, {("git", "ls-remote"): listed})
    assert published_versions(fake, "origin") == [v("0.1.0"), v("0.2.0")]
    assert fake.calls == [["git", "ls-remote", "--tags", "origin"]]


@pytest.mark.parametrize(("text", "prerelease"), [("0.9.0", True), ("1.0.0", False)])
def test_publish_commands_tag_push_then_release(text: str, prerelease: bool) -> None:
    """Section 28.7: annotated tag, push, then ``gh release create`` with assets.

    Args:
        text: Version being released.
        prerelease: Whether ``--prerelease`` is expected (MVP rule).

    Returns:
        None

    Raises:
        AssertionError: If the commands differ.
    """
    cfg = ReleaseConfig.from_mapping({**EXAMPLE, "prerelease": "rc-or-major-zero"}, Path("/r"))
    version = ReleaseVersion.parse(text)
    files = [Path("/r/out/pkg.deb"), Path("/r/out/SHA256SUMS"), Path("/r/out/SHA256SUMS.sig")]
    tag, push, release = publish_commands(cfg, version, Path("/r/out/notes.txt"), files)
    assert tag == ["git", "tag", "--annotate", f"v{text}", "--message", f"package {text}"]
    assert push == ["git", "push", "remote", f"refs/tags/v{text}"]
    assert release[:6] == ["gh", "release", "create", f"v{text}", "--repo", "owner/example"]
    assert ("--prerelease" in release) is prerelease
    assert release[-3:] == [str(f) for f in files]


def test_dry_run_executes_nothing(
    tmp_path: Path, fake_runner: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    """Section 28.7: a dry run prints the commands and runs none of them.

    Args:
        tmp_path: Working directory for the fake runner.
        fake_runner: ``FakeRunner`` class from ``conftest.py``.
        capsys: Captures printed commands.

    Returns:
        None

    Raises:
        AssertionError: If a command runs or is not shown.
    """
    fake = fake_runner(tmp_path, {("git",): "", ("gh",): ""})
    publish(fake, [["git", "tag", "v1.0.0", "--message", "pkg 1.0.0"]], dry_run=True)
    assert fake.calls == []
    # Quoted, so a printed command can be pasted into a shell as is.
    assert "would run: git tag v1.0.0 --message 'pkg 1.0.0'" in capsys.readouterr().out
    publish(fake, [["gh", "release", "create", "v1.0.0"]], dry_run=False)
    assert fake.calls == [["gh", "release", "create", "v1.0.0"]]
