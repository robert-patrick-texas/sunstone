"""Overrides: Sunstone's own exceptions to what its sources say.

Sunstone is the enterprise's status dashboard, fed by tools that do not
always say things the way the operations center needs: a customer-managed
device under a name no one there uses, a switch whose LLDP still sends its
old hostname, a lab switch that should count toward nothing. An override
records one such exception, on one object, with who made it, when, why, and
until when.

Overrides are kept apart from fixes (``changes.py``). A fix corrects the
documentation and is meant for the source of truth; an override is local,
never sent anywhere, and survives the topology file being replaced: one
whose target is gone is kept, and says it is not applied, rather than
stopping the server.

Kinds, and what each applies to:

- ``rename``: the name shown (sites, devices, external nodes). A site's
  name is changed in the topology served; a device or external node keeps
  its name as the key everything else uses, and the views show the new one.
  Discovery matches a device's new name too.
- ``alias``: another name discovery and search match, shown nowhere else.
- ``tag``: a word, as the topology's own tags; ``label``: a key and value.
- ``hide-map``: left out of every drawing, still found by search.
- ``hide-status``: counts toward no status and raises no problem, as an
  ignored link; on a link, a port channel's members, a device, every device
  at a site, or an external node, it is priority ``ignored``.
- ``lock``: one field kept at a value, whatever the topology says.
- ``one-device`` and ``ignore-neighbor``, on one port of our device: every
  row LLDP and CDP give there is one neighbor, under a chosen name; or the
  rows naming one neighbor are dropped before discovery compares.

Overrides apply after the fixes, before status, discovery, and drawing, in
the order they were made. One that has expired stops applying and is kept,
to be renewed or withdrawn; a withdrawn one is kept too, for the handover.
"""

import json
import os
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

from sunstone.discovery import NeighborRules, port_key
from sunstone.model import Lag, Sides, Topology, lag_members
from sunstone.problems import Note, PersonName

TargetKind = Literal[
    "site",
    "device",
    "link",
    "lag",
    "external",
    "transport",
    "tunnel",
    "fabric",
    "resource",
    "network",
    "port",
]
OverrideKind = Literal[
    "rename",
    "alias",
    "tag",
    "label",
    "hide-map",
    "hide-status",
    "lock",
    "one-device",
    "ignore-neighbor",
]
OverrideState = Literal["active", "expired", "not-applied"]
LineEvent = Literal["made", "withdrawn", "expired"]

# Everything that can carry tags, labels, or locks: all but a port.
_OBJECTS: frozenset[TargetKind] = frozenset(
    {
        "site",
        "device",
        "link",
        "lag",
        "external",
        "transport",
        "tunnel",
        "fabric",
        "resource",
        "network",
    }
)
APPLIES_TO: dict[OverrideKind, frozenset[TargetKind]] = {
    "rename": frozenset({"site", "device", "external"}),
    "alias": frozenset({"site", "device", "external"}),
    "tag": _OBJECTS,
    "label": _OBJECTS,
    "hide-map": _OBJECTS - {"network"},
    "hide-status": frozenset({"site", "device", "link", "lag", "external"}),
    "lock": _OBJECTS,
    "one-device": frozenset({"port"}),
    "ignore-neighbor": frozenset({"port"}),
}
"""What each kind of override can be made on."""
LOCKABLE: dict[TargetKind, tuple[str, ...]] = {
    "site": ("region", "lat", "lon"),
    "device": ("site", "role", "platform", "mgmt_ip", "location", "priority"),
    "link": ("speed_mbps", "kind", "medium", "priority", "enterprise_cid"),
    "lag": ("enterprise_cid",),
    "external": ("kind", "tenant", "network", "platform", "description", "priority"),
    "transport": ("kind", "provider", "technology", "description"),
    "tunnel": ("technology", "enterprise_cid"),
    "fabric": ("technology", "enterprise_cid"),
    "resource": ("description",),
    "network": ("tenant", "description"),
}
"""The fields a lock can keep, on each kind of object."""
# Kinds that only the views use: making or withdrawing one changes nothing
# the server works out.
SHOWN_ONLY: frozenset[OverrideKind] = frozenset({"tag", "label", "hide-map"})
# Kinds an object has one of at a time (a lock and a label, one per key):
# making another replaces it.
SINGLE: frozenset[OverrideKind] = frozenset(
    {"rename", "label", "hide-map", "hide-status", "lock", "one-device"}
)
# The lists of objects in a topology, by target kind, and each one's key.
_LISTS: dict[TargetKind, str] = {
    "site": "sites",
    "device": "devices",
    "link": "links",
    "lag": "lags",
    "external": "externals",
    "transport": "transports",
    "tunnel": "tunnels",
    "fabric": "fabrics",
    "resource": "resources",
    "network": "networks",
}
_NOUN: dict[TargetKind, str] = {
    "site": "site",
    "device": "device",
    "link": "link",
    "lag": "port channel",
    "external": "external node",
    "transport": "transport",
    "tunnel": "tunnel",
    "fabric": "fabric",
    "resource": "resource",
    "network": "network",
    "port": "device",
}

Value = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]


class OverridesError(Exception):
    """The overrides file cannot be read."""


class OverrideRefused(Exception):
    """An override cannot be made on the network as it is."""


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Target(_Record):
    """What an override is on: an object by its key, or one port of a device."""

    kind: TargetKind
    id: str = Field(min_length=1, max_length=400)
    """A site's code, a device's, external node's, transport's, tunnel's,
    fabric's, resource's, or network's name, a link's or port channel's id,
    or for a port, its device's name."""
    interface: str | None = Field(None, min_length=1, max_length=100)
    """A port's interface; only for a port."""

    @model_validator(mode="after")
    def _port_has_interface(self) -> Self:
        if (self.kind == "port") != (self.interface is not None):
            raise ValueError("A port, and only a port, has an interface")
        return self


class OverrideIn(_Record):
    """An override someone makes."""

    target: Target
    kind: OverrideKind
    key: Value | None = None
    """A label's key, or the field a lock keeps."""
    value: Value | None = None
    """The new name, alias, tag, label's value, lock's value, or the
    neighbor's name; none to hide."""
    note: Note = ""
    by: PersonName
    expires: datetime | None = None
    """When it stops applying; None for until it is withdrawn."""

    @model_validator(mode="after")
    def _complete(self) -> Self:
        if self.target.kind not in APPLIES_TO[self.kind]:
            raise ValueError(
                f"A {self.kind} override is not made on a {_NOUN[self.target.kind]}"
            )
        keyed = self.kind in ("label", "lock")
        if keyed != bool(self.key):
            raise ValueError(
                f"A {self.kind} override {'needs' if keyed else 'takes no'} key"
            )
        valued = self.kind not in ("hide-map", "hide-status")
        if valued != bool(self.value):
            raise ValueError(
                f"A {self.kind} override {'needs' if valued else 'takes no'} value"
            )
        if self.kind == "lock" and self.key not in LOCKABLE[self.target.kind]:
            fields = ", ".join(LOCKABLE[self.target.kind])
            raise ValueError(
                f"A {_NOUN[self.target.kind]}'s {self.key} cannot be locked "
                f"(only {fields})"
            )
        return self


class Stamp(_Record):
    """Who did something to an override, and when."""

    by: str
    at: datetime


class Override(_Record):
    """An override, as made, and withdrawn if it has been."""

    id: str
    target: Target
    kind: OverrideKind
    key: str | None = None
    value: str | None = None
    note: str = ""
    by: str
    at: datetime
    expires: datetime | None = None
    renewed: Stamp | None = None
    """Who last gave it a new expiry, and when."""
    withdrawn: Stamp | None = None


class OverrideNow(Override):
    """An override, and how it stands against the network now."""

    state: OverrideState
    """``active`` while it applies, ``expired`` once its time is up, and
    ``not-applied`` while its target is not in the topology, or the topology
    will not take it."""
    reason: str | None = None
    """Why it is not applied."""
    topology_value: str | None = None
    """For a lock that differs from the topology, what the topology says
    (empty for nothing); for a site renamed, its name in the topology."""


class OverrideList(_Record):
    """The overrides not withdrawn, newest first."""

    overrides: list[OverrideNow]


class OverrideLine(_Record):
    """An override made, withdrawn, or expired in a span, for the handover."""

    event: LineEvent
    at: datetime
    override: Override


class RenewIn(_Record):
    """A new expiry for an override, or none."""

    by: PersonName
    expires: datetime | None = None


class WithdrawIn(_Record):
    """Who withdraws an override."""

    by: PersonName


class _File(_Record):
    overrides: list[Override] = []
    """Oldest first, the order they apply in."""


@dataclass(frozen=True)
class Overridden:
    """The topology with the overrides applied, and how each stands."""

    topology: Topology
    rules: NeighborRules
    """What discovery takes from the overrides: other names for devices,
    and what to make of the rows on some ports."""
    now: list[OverrideNow]
    """Every override not withdrawn, oldest first."""

    def applying(self) -> frozenset[str]:
        """The ids of those that apply.

        Returns:
            Them, to tell when one has expired since.

        Raises:
            None
        """
        return frozenset(o.id for o in self.now if o.state == "active")


def text(value: object) -> str:
    """A field's value as an override gives it.

    Args:
        value: The value: a CID's sides, a number, a word, or none.

    Returns:
        The text: a CID as its A side, or ``A / Z`` where Z has its own;
        none as empty.

    Raises:
        None
    """
    if value is None:
        return ""
    if isinstance(value, Sides):
        return value.a if value.z in (None, value.a) else f"{value.a} / {value.z}"
    return str(value)


def _key(kind: TargetKind, item: BaseModel) -> str:
    """An object's key: a site's code, a link's or port channel's id, or
    anything else's name."""
    field = {"site": "code", "link": "id", "lag": "id"}.get(kind, "name")
    return str(getattr(item, field))


def _objects(topology: Topology, kind: TargetKind) -> dict[str, BaseModel]:
    """A topology's objects of one kind, by their key: a port's, its device."""
    if kind == "port":
        kind = "device"
    return {_key(kind, item): item for item in getattr(topology, _LISTS[kind])}


def missing(topology: Topology, target: Target) -> str | None:
    """Why a target is not in a topology.

    Args:
        topology: The topology.
        target: The target.

    Returns:
        "No device alpha-dal-1 now", or None when it is there.

    Raises:
        None
    """
    if target.id in _objects(topology, target.kind):
        return None
    return f"No {_NOUN[target.kind]} {target.id} now"


Edit = tuple[TargetKind, str, str, object]
"""One field of one object to change: its kind, key, field, and value."""


def _with(topology: Topology, edits: list[Edit]) -> Topology:
    """A topology with fields of its objects changed, validated again."""
    lists: dict[str, list[BaseModel]] = {}
    for kind, key, field, value in edits:
        name = _LISTS[kind]
        items = lists.setdefault(name, list(getattr(topology, name)))
        at = next(i for i, item in enumerate(items) if _key(kind, item) == key)
        item = items[at]
        # Its fields, without the ids worked out from them.
        fields = {k: getattr(item, k) for k in type(item).model_fields}
        items[at] = type(item).model_validate({**fields, field: value})
    return Topology.model_validate({**dict(topology), **lists})


def _quiet(topology: Topology, target: Target) -> list[tuple[TargetKind, str]]:
    """The objects whose priority hiding a target from status makes ignored."""
    if target.kind == "site":
        return [("device", d.name) for d in topology.devices if d.site == target.id]
    if target.kind == "lag":
        lag = _objects(topology, "lag")[target.id]
        assert isinstance(lag, Lag)
        return [("link", ln.id) for ln in lag_members(lag, topology.links)]
    return [(target.kind, target.id)]


def _error(e: ValidationError) -> str:
    """A validation error in a sentence."""
    return "; ".join(
        str(err["msg"]).removeprefix("Value error, ") for err in e.errors()
    )


def apply(
    topology: Topology, overrides: Iterable[Override], at: datetime
) -> Overridden:
    """The topology with the overrides that apply at a moment applied.

    The changes to the topology are made together and validated once, as
    validating a large topology takes most of a second; only if it will not
    take them all are they made one at a time, to find which it refuses.

    Args:
        topology: The documentation, with its fixes.
        overrides: Every override, oldest first; withdrawn ones are skipped.
        at: The moment, for which have expired.

    Returns:
        The topology changed by locks, sites' new names, and hiding from
        status; the rules discovery takes from names and ports; and how
        each override stands.

    Raises:
        None
    """
    now: list[OverrideNow] = []
    names: dict[str, str] = {}
    one_device: dict[tuple[str, str], str] = {}
    ignored: dict[tuple[str, str], set[str]] = {}
    changing: list[tuple[int, list[Edit]]] = []
    for o in overrides:
        if o.withdrawn is not None:
            continue
        state: OverrideState = "active"
        reason = missing(topology, o.target)
        if o.expires is not None and o.expires <= at:
            state = "expired"
        elif reason is not None:
            state = "not-applied"
        if state == "active" and (edits := _edits(topology, o)):
            changing.append((len(now), edits))
        if state == "active" and o.target.kind == "device" and o.value:
            if o.kind in ("rename", "alias"):
                names[o.value] = o.target.id
        if state == "active" and o.target.kind == "port" and o.value:
            port = (o.target.id, port_key(o.target.interface or ""))
            if o.kind == "one-device":
                one_device[port] = o.value
            elif o.kind == "ignore-neighbor":
                ignored.setdefault(port, set()).add(o.value)
        now.append(
            OverrideNow(
                **dict(o),
                state=state,
                reason=reason if state == "not-applied" else None,
            )
        )
    return Overridden(
        topology=_changed(topology, changing, now),
        rules=NeighborRules(
            names=names,
            one_device=one_device,
            ignored={p: frozenset(v) for p, v in ignored.items()},
        ),
        now=now,
    )


def _edits(topology: Topology, o: Override) -> list[Edit]:
    """What an override changes in the topology: none for most kinds."""
    t = o.target
    if o.kind == "lock" and o.key:
        return [(t.kind, t.id, o.key, o.value)]
    if o.kind == "rename" and t.kind == "site":
        return [("site", t.id, "name", o.value)]
    if o.kind == "hide-status":
        return [(k, key, "priority", "ignored") for k, key in _quiet(topology, t)]
    return []


def _changed(
    topology: Topology, changing: list[tuple[int, list[Edit]]], now: list[OverrideNow]
) -> Topology:
    """The topology with each override's edits made, all at once if it
    takes them, else one override at a time, marking those it refuses not
    applied; and, on each lock that differs and each site renamed, what the
    topology says.

    Args:
        topology: The documentation, with its fixes.
        changing: Where each override that changes it is in ``now``, and its edits.
        now: How each override stands, updated in place.

    Returns:
        The topology changed.
    """
    if not changing:
        return topology
    try:
        result = _with(topology, [e for _, edits in changing for e in edits])
    except ValidationError:
        result = topology
        for i, edits in changing:
            try:
                result = _with(result, edits)
            except ValidationError as e:
                now[i] = now[i].model_copy(
                    update={"state": "not-applied", "reason": _error(e)}
                )
    for i, _ in changing:
        o = now[i]
        field = o.key if o.kind == "lock" else "name" if o.kind == "rename" else None
        if o.state != "active" or field is None:
            continue
        t = o.target
        before = text(getattr(_objects(topology, t.kind)[t.id], field))
        after = text(getattr(_objects(result, t.kind)[t.id], field))
        if before != after or o.kind == "rename":
            now[i] = o.model_copy(update={"topology_value": before})
    return result


def check(topology: Topology, made: OverrideIn) -> None:
    """Whether an override can be made on the network as it is.

    Args:
        topology: The documentation with its fixes and the overrides now.
        made: The override.

    Raises:
        OverrideRefused: If its target is not there, or the topology will
            not take it, such as a device locked to a site there is not.
    """
    gone = missing(topology, made.target)
    if gone:
        raise OverrideRefused(gone)
    if made.kind == "lock" and made.key:
        try:
            _with(topology, [(made.target.kind, made.target.id, made.key, made.value)])
        except ValidationError as e:
            raise OverrideRefused(_error(e)) from e


def same(a: Override, b: OverrideIn | Override) -> bool:
    """Whether a new override takes the place of an old one, or repeats it.

    Args:
        a: An override not withdrawn.
        b: A new one.

    Returns:
        True for one of a kind an object has one of at a time, on the same
        target (and key), or for one of another kind with the same value.

    Raises:
        None
    """
    if a.target != b.target or a.kind != b.kind:
        return False
    if a.kind in SINGLE:
        return a.key == b.key
    return (a.value or "").lower() == (b.value or "").lower()


def lines(
    overrides: Iterable[Override], since: datetime, until: datetime
) -> list[OverrideLine]:
    """The overrides made, withdrawn, or expired in a span, latest first.

    Args:
        overrides: Every override, withdrawn ones too.
        since: The span's start.
        until: Its end.

    Returns:
        A line for each of those moments in the span: an override withdrawn
        before it expired did not expire.

    Raises:
        None
    """
    found: list[OverrideLine] = []
    for o in overrides:
        if since <= o.at <= until:
            found.append(OverrideLine(event="made", at=o.at, override=o))
        if o.withdrawn and since <= o.withdrawn.at <= until:
            found.append(OverrideLine(event="withdrawn", at=o.withdrawn.at, override=o))
        if (
            o.expires
            and since <= o.expires <= until
            and (o.withdrawn is None or o.withdrawn.at > o.expires)
        ):
            found.append(OverrideLine(event="expired", at=o.expires, override=o))
    return sorted(found, key=lambda line: line.at, reverse=True)


def new_override(made: OverrideIn, at: datetime) -> Override:
    """Record an override someone makes.

    Args:
        made: The override.
        at: When.

    Returns:
        It, with a new id.

    Raises:
        None
    """
    return Override(id=uuid.uuid4().hex[:12], **dict(made), at=at)


class OverrideStore:
    """Every override for one topology, in a JSON file created on first one."""

    def __init__(self, path: Path) -> None:
        """Use an overrides file.

        Args:
            path: The JSON file.

        Raises:
            OverridesError: If the file exists but cannot be read.
        """
        self.path = path
        self._overrides = self._read()

    def overrides(self) -> list[Override]:
        """Every override, withdrawn ones too, oldest first.

        Returns:
            The overrides.

        Raises:
            None
        """
        return list(self._overrides)

    def save(self, overrides: list[Override]) -> None:
        """Replace the overrides.

        Args:
            overrides: Every override, oldest first.

        Raises:
            OSError: If the file cannot be written.
        """
        temporary = self.path.with_name(f".{self.path.name}.tmp")
        body = _File(overrides=overrides).model_dump(mode="json")
        temporary.write_text(json.dumps(body, indent=1), encoding="utf-8")
        os.replace(temporary, self.path)
        self._overrides = list(overrides)

    def _read(self) -> list[Override]:
        try:
            raw = self.path.read_bytes()
        except FileNotFoundError:
            return []
        except OSError as e:
            raise OverridesError(f"{self.path}: {e}") from e
        try:
            return _File.model_validate_json(raw).overrides
        except ValidationError as e:
            raise OverridesError(f"{self.path}: {e}") from e
