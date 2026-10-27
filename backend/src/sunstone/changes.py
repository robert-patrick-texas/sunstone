"""Fixes accepted into the documentation: Sunstone's change set.

Discovery offers a fix for each finding it can (``discovery.Fix``): move a
link's end to where its cable is seen, add a cable no one documented, or
retire a link no one sees. Someone reviews it, seeing what Live reads on
the ports involved now and what the change would do to redundancy and to
the problems there are now, and accepts it, with their name and a note.

Accepted fixes make up the change set: the documentation as Sunstone shows
it is the topology file with every change applied in turn, so every view,
problem, and discovery run follows the fixed documentation. The file is
left as it is; the changes are kept beside it in a JSON file, rewritten
whole on each change, until there is a real source of truth to send them
to. A change can be reverted, unless a later one depends on it.

A finding can be marked expected instead, with a note saying why: a link
LLDP cannot see across a media converter, a lab port. That changes no
link, so it is kept in the change set as a change of kind ``expect``, and
discovery sets the finding aside (``discovery.expecting``).
"""

import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Self

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from sunstone.discovery import Finding, Fix
from sunstone.live import InterfaceState
from sunstone.model import Link, Topology
from sunstone.problems import Note, PersonName


class ChangesError(Exception):
    """The changes file cannot be read, or its changes do not apply to the topology."""


class ChangeConflict(Exception):
    """A change does not apply to the documentation as it is."""


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ChangeIn(_Record):
    """A fix someone accepts: the finding it fixes, as of the latest run."""

    finding: str
    note: Note = ""
    by: PersonName
    expect: bool = False
    """Mark the finding expected rather than fix it; that needs a note."""

    @model_validator(mode="after")
    def _explained(self) -> Self:
        if self.expect and not self.note:
            raise ValueError("Say why it is expected")
        return self


class Change(_Record):
    """A fix accepted into the documentation."""

    id: str
    finding: str
    title: str
    """The finding's title when it was fixed."""
    fix: Fix
    note: str
    by: str
    at: datetime


class ChangeSet(_Record):
    """Every change accepted, newest first."""

    changes: list[Change]


class _File(_Record):
    changes: list[Change] = []
    """Oldest first, the order they apply in."""


class PortNow(_Record):
    """A port a fix takes out of the documentation or puts in, as Live reads it now."""

    device: str
    interface: str
    reading: InterfaceState | None = None
    """None if its device is not monitored, or not answering."""


class Review(_Record):
    """What accepting a fix would do, worked out against the network now."""

    finding: Finding
    removes: list[PortNow]
    """Ports the documentation would no longer have a link on."""
    adds: list[PortNow]
    """Ports it would have a link on."""
    exposed: dict[str, list[str]]
    """Devices the documentation would leave depending on a single device to
    reach the core, with the devices on the way, core side first."""
    restored: list[str]
    """Devices it would no longer leave depending on one."""
    cut_off: list[str]
    """Devices it would no longer join to the core at all."""
    cleared: list[str]
    """Problems there are now that it would clear, by title."""
    raised: list[str]
    """Problems it would raise now, by title."""
    involved: list[PortNow] = []
    """For marking it expected, which changes no link: the ports the
    finding is about, as Live reads them now."""


def applied(topology: Topology, fixes: list[Fix]) -> Topology:
    """The documentation with fixes applied in turn.

    Args:
        topology: The documentation to start from.
        fixes: The fixes, oldest first.

    Returns:
        The documentation as changed: a moved link stays where it was in the
        list of links, and an added one goes at the end.

    Raises:
        ChangeConflict: If a fix's link is no longer documented, or the
            fixes would leave the documentation invalid (two links on one
            port, say).
    """
    links = list(topology.links)
    for fix in fixes:
        if fix.before is None:
            if fix.after is not None:
                links.append(fix.after)
            continue
        at = next((i for i, ln in enumerate(links) if ln.id == fix.before.id), None)
        if at is None:
            raise ChangeConflict(
                f"{fix.summary}: the link {fix.before.id} is no longer documented"
            )
        if fix.after is None:
            del links[at]
        else:
            links[at] = fix.after
    try:
        return Topology(sites=topology.sites, devices=topology.devices, links=links)
    except ValidationError as e:
        raise ChangeConflict(
            "; ".join(
                str(err["msg"]).removeprefix("Value error, ") for err in e.errors()
            )
        ) from e


def expected(changes: list[Change]) -> set[str]:
    """The findings marked expected.

    Args:
        changes: The change set.

    Returns:
        Their ids.

    Raises:
        None
    """
    return {c.finding for c in changes if c.fix.kind == "expect"}


def ports(link: Link | None) -> list[tuple[str, str]]:
    """A link's ports, as (device, interface) pairs.

    Args:
        link: The link, or None.

    Returns:
        Its A end, then its B end; none for no link.

    Raises:
        None
    """
    if link is None:
        return []
    return [(link.a.device, link.a.interface), (link.b.device, link.b.interface)]


class ChangeStore:
    """The change set for one topology, in a JSON file created on first change."""

    def __init__(self, path: Path) -> None:
        """Use a changes file.

        Args:
            path: The JSON file.

        Raises:
            ChangesError: If the file exists but cannot be read.
        """
        self.path = path
        self.lock = Lock()
        """Held while the change set and what is worked out from it change."""
        self._changes = self._read()

    def changes(self) -> list[Change]:
        """Every change, oldest first, the order they apply in.

        Returns:
            The changes.

        Raises:
            None
        """
        return list(self._changes)

    def save(self, changes: list[Change]) -> None:
        """Replace the change set.

        Args:
            changes: Every change, oldest first.

        Raises:
            OSError: If the file cannot be written.
        """
        temporary = self.path.with_name(f".{self.path.name}.tmp")
        # Without link ids, which are worked out from the ends.
        body = _File(changes=changes).model_dump(
            mode="json", exclude_computed_fields=True
        )
        temporary.write_text(json.dumps(body, indent=1), encoding="utf-8")
        os.replace(temporary, self.path)
        self._changes = list(changes)

    def _read(self) -> list[Change]:
        try:
            raw = self.path.read_bytes()
        except FileNotFoundError:
            return []
        except OSError as e:
            raise ChangesError(f"{self.path}: {e}") from e
        try:
            return _File.model_validate_json(raw).changes
        except ValidationError as e:
            raise ChangesError(f"{self.path}: {e}") from e


def new_change(finding: Finding, fix: Fix, change: ChangeIn, at: datetime) -> Change:
    """Record a fix someone accepts.

    Args:
        finding: The finding it fixes.
        fix: The fix the finding offers.
        change: Who accepts it, and their note.
        at: When.

    Returns:
        The change, with a new id.

    Raises:
        None
    """
    return Change(
        id=uuid.uuid4().hex[:12],
        finding=finding.id,
        title=finding.title,
        fix=fix,
        note=change.note,
        by=change.by,
        at=at,
    )
