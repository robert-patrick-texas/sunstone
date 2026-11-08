# Copyright 2026 Robert Patrick
# SPDX-License-Identifier: Apache-2.0
r"""Turn a verified release into an annotated tag, a pushed tag, and a GitHub release.

These are the only irreversible steps of a release, so they are built as
plain command lists first. A dry run prints them; a real run executes them in
order and stops at the first failure. Release notes come from the matching
``CHANGELOG.md`` section, so what operators read on GitHub is exactly what
the repository records (VER-004). Versions whose sections were written but
never released on their own, between the last release tagged on the remote
and this one, are carried along in the notes, each under its own heading,
so operators see everything that changed since the release they have. That
catching up is Sunstone's addition; vakr's copy takes the one section only.

Dependencies:
    re, shlex: Find changelog sections; quote commands for display.
    release_proc: Runs ``git`` and ``gh`` with argument lists.

Safety:
    Nothing here runs unless the caller passes ``dry_run=False``. Commands
    never pass through a shell, so notes and titles cannot inject arguments.

Example:
    >>> changelog_notes("## 1.2.3\n\n- Fixed it.\n## 1.2.2\n", "1.2.3")
    '- Fixed it.'
"""

import re
import shlex
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from release_config import ReleaseConfig
from release_proc import Runner
from release_version import ReleaseVersion, VersionError

_HEADING = re.compile(r"^##\s+\[?v?(\d+\.\d+\.\d+(?:-rc\.\d+)?)\]?(?=\s|$)")
"""A changelog section's heading, in the forms ``changelog_notes`` accepts."""


@dataclass(frozen=True)
class Notes:
    """A release's notes, and which versions they cover.

    Attributes:
        text: The notes, as given to ``gh release create``.
        versions: Newest first: the version released, then those never
            released on their own whose sections the notes carry.
        since: The last release tagged before it, or ``None`` when there is
            none.
    """

    text: str
    versions: tuple[str, ...]
    since: str | None


def changelog_notes(text: str, version: str) -> str | None:
    """Extract the body of the changelog section for ``version``.

    Accepts headings such as ``## 1.2.3``, ``## [1.2.3]``, ``## v1.2.3``,
    and any of those followed by a date.

    Args:
        text: Changelog Markdown.
        version: Version as written in ``VERSION``.

    Returns:
        str | None: The section body without its heading, stripped; ``None``
        when the section is missing or empty.

    Raises:
        None
    """
    heading = re.compile(rf"^##\s+\[?v?{re.escape(version)}\]?(?=\s|$)")
    body: list[str] | None = None
    for line in text.splitlines():
        if body is None:
            body = [] if heading.match(line) else None
        elif line.startswith("## "):
            break
        else:
            body.append(line)
    notes = "\n".join(body or []).strip()
    return notes or None


def published_versions(runner: Runner, remote: str) -> list[ReleaseVersion]:
    """List the versions tagged ``v<version>`` on the remote, oldest first.

    Args:
        runner: Command runner in the repository.
        remote: Remote name, for example ``origin``.

    Returns:
        list[ReleaseVersion]: Each version once; tags that are not versions
        are left out.

    Raises:
        release_proc.CommandError: If the remote cannot be queried.
    """
    found: set[ReleaseVersion] = set()
    for line in runner.run(["git", "ls-remote", "--tags", remote]).stdout.splitlines():
        ref = line.rpartition("\t")[2].removesuffix("^{}")
        if ref.startswith("refs/tags/v"):
            try:
                found.add(ReleaseVersion.parse(ref.removeprefix("refs/tags/v")))
            except VersionError:
                continue
    return sorted(found, key=_rank)


def release_notes(
    text: str, version: ReleaseVersion, published: Iterable[ReleaseVersion]
) -> Notes | None:
    """Build a release's notes: its own changelog section, and the sections
    of every version since the last release that was never released.

    With only its own section, the notes are that section's body, as
    ``changelog_notes`` gives it. With more, a line says which versions the
    notes also carry, and each section follows under its own heading,
    newest first. Without any earlier release, every older section counts
    as never released.

    Args:
        text: Changelog Markdown.
        version: Version being released.
        published: Versions already released, as tagged on the remote.

    Returns:
        Notes | None: The notes, or ``None`` when the version's own section
        is missing or empty.

    Raises:
        None
    """
    own = changelog_notes(text, version.semver)
    if own is None:
        return None
    earlier = [v for v in published if _rank(v) < _rank(version)]
    since = max(earlier, key=_rank) if earlier else None
    headings: dict[ReleaseVersion, str] = {}
    for line in text.splitlines():
        match = _HEADING.match(line)
        if not match:
            continue
        try:
            headings.setdefault(ReleaseVersion.parse(match.group(1)), line.strip())
        except VersionError:
            continue
    skipped = [
        (v, body)
        for v in sorted(headings, key=_rank, reverse=True)
        if _rank(v) < _rank(version)
        and (since is None or _rank(since) < _rank(v))
        and (body := changelog_notes(text, v.semver)) is not None
    ]
    last = since.semver if since else None
    if not skipped:
        return Notes(own, (version.semver,), last)
    names = [v.semver for v, _ in skipped]
    lead = f"This release also carries the notes of {_and_list(names)}, never released on their own"
    lead += f"; the last release was {last}." if last else "."
    sections = [(headings[version], own)] + [(headings[v], body) for v, body in skipped]
    parts = [lead, *(f"{heading}\n\n{body}" for heading, body in sections)]
    return Notes("\n\n".join(parts), (version.semver, *names), last)


def _rank(version: ReleaseVersion) -> tuple[int, int, int, bool, int]:
    """Order versions: a release candidate comes before its final release.

    Args:
        version: Any version.

    Returns:
        tuple[int, int, int, bool, int]: A sort key.

    Raises:
        None
    """
    return (version.major, version.minor, version.patch, version.rc is None, version.rc or 0)


def _and_list(words: list[str]) -> str:
    """Join words as a list in prose: ``a``, ``a and b``, ``a, b, and c``.

    Args:
        words: At least one word.

    Returns:
        str: The words joined.

    Raises:
        None
    """
    if len(words) <= 2:
        return " and ".join(words)
    return f"{', '.join(words[:-1])}, and {words[-1]}"


def publish_commands(
    cfg: ReleaseConfig,
    version: ReleaseVersion,
    notes: Path,
    files: list[Path],
) -> list[list[str]]:
    """Build the tag, push, and release commands, in execution order.

    Args:
        cfg: Release configuration.
        version: Version being released.
        notes: File holding the release notes.
        files: Artifacts plus ``SHA256SUMS`` and its signature, to attach.

    Returns:
        list[list[str]]: Argument lists for ``git tag``, ``git push``, and
        ``gh release create``.

    Raises:
        release_version.VersionError: If the configured prerelease rule is
            unknown.
    """
    title = f"{cfg.package} {version.semver}"
    release = ["gh", "release", "create", version.tag, "--repo", cfg.repo]
    release += ["--title", title, "--notes-file", str(notes), "--verify-tag"]
    if version.is_prerelease(cfg.prerelease):
        release.append("--prerelease")
    return [
        ["git", "tag", "--annotate", version.tag, "--message", title],
        ["git", "push", cfg.remote, f"refs/tags/{version.tag}"],
        [*release, *(str(path) for path in files)],
    ]


def publish(runner: Runner, commands: list[list[str]], *, dry_run: bool) -> None:
    """Execute (or, in a dry run, only print) the publishing commands.

    Args:
        runner: Command runner in the repository.
        commands: Output of ``publish_commands``.
        dry_run: Print instead of executing.

    Returns:
        None

    Raises:
        release_proc.CommandError: If a command fails; later commands are
            not run, so a failed push never leads to a release.
    """
    for argv in commands:
        if dry_run:
            print(f"  would run: {shlex.join(argv)}")
        else:
            print(f"  running: {shlex.join(argv[:4])} ...")
            runner.run(argv, capture=False)
