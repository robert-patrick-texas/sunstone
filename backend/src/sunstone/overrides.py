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

A rule is an override on everything that matches: every object of one kind
that passes its tests (a name pattern, a site, a role, a platform, a tag),
or every port of the devices that do whose interface matches a pattern. It
does what an override does (tags, labels, hiding, locks to one value, and
on ports, ignoring neighbors whose names match or taking every row as one
device), but not renaming or aliasing, which are about one object. Rules
see the topology as the fixes and the overrides on single objects leave
it, never what another rule adds, so they never chain. Where an object can
have one of a kind at a time (a label of a key, a lock of a field, hiding),
its own override wins over any rule, and a newer rule over an older one;
an object can also be taken out of a rule, as an exception.
"""

import json
import os
import uuid
from collections.abc import Callable, Iterable
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

from sunstone.discovery import NeighborRules, PortRule, like, port_key
from sunstone.model import (
    Device,
    External,
    Lag,
    Link,
    Sides,
    Site,
    Topology,
    device_ends,
    lag_members,
    link_roles,
    ratings,
)
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


RuleKind = Literal[
    "tag",
    "label",
    "hide-map",
    "hide-status",
    "lock",
    "one-device",
    "ignore-neighbor",
]
TestField = Literal[
    "name",
    "site",
    "region",
    "role",
    "platform",
    "priority",
    "kind",
    "medium",
    "tenant",
    "tag",
    "interface",
]
TEST_FIELDS: tuple[TestField, ...] = (
    "name",
    "site",
    "region",
    "role",
    "platform",
    "priority",
    "kind",
    "medium",
    "tenant",
    "tag",
    "interface",
)
TESTS: dict[TargetKind, tuple[TestField, ...]] = {
    "site": ("name", "region", "tag"),
    "device": ("name", "site", "region", "role", "platform", "priority", "tag"),
    "port": ("name", "site", "region", "role", "platform", "tag", "interface"),
    "link": ("name", "site", "region", "role", "kind", "medium", "priority", "tag"),
    "lag": ("name", "site", "region", "tag"),
    "external": ("name", "kind", "tenant", "platform", "priority", "tag"),
    "transport": ("name", "kind", "tag"),
    "tunnel": ("name", "tag"),
    "fabric": ("name", "tag"),
    "resource": ("name", "tag"),
    "network": ("name", "tag"),
}
"""What a rule can test, on each kind of object. On a port, all but the
interface are its device's; on a link, the site and region are either
end's, the role is at the edge (``internal`` between two of our devices,
``tbd`` until documented), and the priority is its rating."""
RULE_APPLIES: dict[RuleKind, frozenset[TargetKind]] = {
    "tag": APPLIES_TO["tag"],
    "label": APPLIES_TO["label"],
    "hide-map": APPLIES_TO["hide-map"],
    "hide-status": APPLIES_TO["hide-status"],
    "lock": APPLIES_TO["lock"],
    "one-device": APPLIES_TO["one-device"],
    "ignore-neighbor": APPLIES_TO["ignore-neighbor"],
}
"""What each kind of rule can be on: as each kind of override."""
# Kinds of rule that take no value: on ports, one device goes by the name
# its rows give, as no one name fits every port.
_UNVALUED: frozenset[RuleKind] = frozenset({"hide-map", "hide-status", "one-device"})

Pattern = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]
Patterns = Annotated[list[Pattern], Field(max_length=20)]
RuleName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)
]


class Match(_Record):
    """What a rule is on: every object of one kind that passes every test
    given, each by any of its patterns (``*`` for any run of characters,
    ``?`` for one), ignoring case; on ports, every port of the devices that
    pass whose interface matches."""

    of: TargetKind
    name: Patterns = []
    """A site's code or name; a device's or external node's name in the
    topology, new name, or alias; a link's id or either CID; anything
    else's key."""
    site: Patterns = []
    """A site's code or name."""
    region: Patterns = []
    """A region, or one it is in."""
    role: Patterns = []
    """A device's role; a link's roles at the edge."""
    platform: Patterns = []
    priority: Patterns = []
    kind: Patterns = []
    """A link's, external node's, or transport's own kind."""
    medium: Patterns = []
    tenant: Patterns = []
    tag: Patterns = []
    """A tag in the topology, or one an override on the object adds."""
    interface: Patterns = []
    """For ports: ``Gi1/0/48``, ``GigabitEthernet1/0/48``, ``*/0/48``."""

    @model_validator(mode="after")
    def _fits(self) -> Self:
        wrong = [f for f in TEST_FIELDS if getattr(self, f) and f not in TESTS[self.of]]
        if wrong:
            raise ValueError(
                f"A rule on {_NOUN[self.of]}s cannot test {', '.join(wrong)} "
                f"(only {', '.join(TESTS[self.of])})"
            )
        if self.of == "port" and not self.interface:
            raise ValueError("A rule on ports needs an interface pattern")
        return self

    def tests(self) -> dict[TestField, list[str]]:
        """The tests given, but a port's interface.

        Returns:
            Each test's patterns, by field.

        Raises:
            None
        """
        return {
            f: getattr(self, f)
            for f in TEST_FIELDS
            if getattr(self, f) and f != "interface"
        }


class RuleIn(_Record):
    """A rule someone makes."""

    name: RuleName
    """What people call it: "Daisy chains", "Lab gear"."""
    match: Match
    kind: RuleKind
    key: Value | None = None
    """A label's key, or the field a lock keeps."""
    value: Value | None = None
    """The tag, label's value, lock's value, or the pattern a neighbor's
    name matches to be ignored (``*`` for any); none to hide, or for one
    device on each port."""
    note: Note = ""
    by: PersonName
    expires: datetime | None = None

    @model_validator(mode="after")
    def _complete(self) -> Self:
        of = self.match.of
        if of not in RULE_APPLIES[self.kind]:
            raise ValueError(f"A {self.kind} rule is not made on {_NOUN[of]}s")
        keyed = self.kind in ("label", "lock")
        if keyed != bool(self.key):
            raise ValueError(
                f"A {self.kind} rule {'needs' if keyed else 'takes no'} key"
            )
        valued = self.kind not in _UNVALUED
        if valued != bool(self.value):
            raise ValueError(
                f"A {self.kind} rule {'needs' if valued else 'takes no'} value"
            )
        if self.kind == "lock" and self.key not in LOCKABLE[of]:
            fields = ", ".join(LOCKABLE[of])
            raise ValueError(
                f"A {_NOUN[of]}'s {self.key} cannot be locked (only {fields})"
            )
        return self


class Excepted(_Record):
    """An object taken out of a rule, by whom, and when."""

    target: Target
    """The object; for a rule on ports, their device."""
    by: str
    at: datetime


class Rule(_Record):
    """A rule, as made, with its exceptions, and withdrawn if it has been."""

    id: str
    name: str
    match: Match
    kind: RuleKind
    key: str | None = None
    value: str | None = None
    note: str = ""
    by: str
    at: datetime
    expires: datetime | None = None
    renewed: Stamp | None = None
    withdrawn: Stamp | None = None
    excepted: list[Excepted] = []
    """The objects taken out of it, oldest first."""


class RuleMatch(_Record):
    """An object a rule applies on."""

    target: Target
    """The object; for a rule on ports, their device."""
    topology_value: str | None = None
    """For a lock, what the topology says where it differs (empty for
    nothing)."""


class RuleNow(Rule):
    """A rule, and how it stands against the network now."""

    state: OverrideState
    """``active`` while it applies, ``expired`` once its time is up, and
    ``not-applied`` while the topology will not take it."""
    reason: str | None = None
    """Why it is not applied."""
    matches: list[RuleMatch] = []
    """What it applies on now, while active: everything that matches but
    its exceptions and what wins over it."""
    overridden: list[Target] = []
    """What it matches where an override on the object, or a newer rule,
    wins."""


class RulePreview(_Record):
    """What a rule would do, made now."""

    matches: list[Target]
    """What it would apply on."""
    overridden: list[Target]
    """What it matches where an override on the object, or a newer rule,
    wins."""
    set_aside: list[str]
    """For a rule on ports, the titles of the discovery findings it would
    set aside in the latest run."""
    raised: list[str]
    """And of those it would raise, such as a link no longer seen once the
    rows that showed it are dropped."""
    reason: str | None = None
    """Why the topology would not take it, if it would not."""


class ExceptIn(_Record):
    """An object to take out of a rule, or put back, and who does it."""

    target: Target
    by: PersonName


class RuleLine(_Record):
    """A rule made, withdrawn, or expired in a span, for the handover."""

    event: LineEvent
    at: datetime
    rule: Rule


class OverrideList(_Record):
    """The overrides and rules not withdrawn, newest first."""

    overrides: list[OverrideNow]
    rules: list[RuleNow] = []


class _File(_Record):
    overrides: list[Override] = []
    """Oldest first, the order they apply in."""
    rules: list[Rule] = []
    """Oldest first."""


@dataclass(frozen=True)
class Overridden:
    """The topology with the overrides and rules applied, and how each stands."""

    topology: Topology
    rules: NeighborRules
    """What discovery takes from the overrides: other names for devices,
    and what to make of the rows on some ports."""
    now: list[OverrideNow]
    """Every override not withdrawn, oldest first."""
    ruled: list[RuleNow]
    """Every rule not withdrawn, oldest first."""

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
Ref = tuple[Literal["override", "rule"], int]
"""An override, or a rule, by where it is in the list of how each stands."""


def _with(topology: Topology, edits: list[Edit], validate: bool = True) -> Topology:
    """A topology with fields of its objects changed, validated again; or,
    not validated, only to be read, as rules read it."""
    lists: dict[str, list[BaseModel]] = {}
    where: dict[str, dict[str, int]] = {}
    for kind, key, field, value in edits:
        name = _LISTS[kind]
        if name not in lists:
            lists[name] = list(getattr(topology, name))
            where[name] = {_key(kind, item): i for i, item in enumerate(lists[name])}
        items = lists[name]
        at = where[name][key]
        item = items[at]
        if validate:
            # Its fields, without the ids worked out from them.
            fields = {k: getattr(item, k) for k in type(item).model_fields}
            items[at] = type(item).model_validate({**fields, field: value})
        else:
            items[at] = item.model_copy(update={field: value})
    if not validate:
        return topology.model_copy(update=lists)
    return Topology.model_validate({**dict(topology), **lists})


def _lookup(topology: Topology) -> Callable[[TargetKind, str], BaseModel]:
    """Find a topology's objects by kind and key, indexing each kind once."""
    found: dict[TargetKind, dict[str, BaseModel]] = {}

    def get(kind: TargetKind, key: str) -> BaseModel:
        if kind not in found:
            found[kind] = _objects(topology, kind)
        return found[kind][key]

    return get


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


@dataclass
class _Standing:
    """How the overrides on single objects stand, and what they change."""

    now: list[OverrideNow]
    changing: list[tuple[int, list[Edit]]]
    """Where each override that changes the topology is in ``now``, and its edits."""
    names: dict[str, str]
    one_device: dict[tuple[str, str], str]
    ignored: dict[tuple[str, str], set[str]]

    def active(self) -> list[OverrideNow]:
        """Those that apply."""
        return [o for o in self.now if o.state == "active"]

    def edits(self) -> list[Edit]:
        """Everything they change, in order."""
        return [e for _, edits in self.changing for e in edits]


def _standing(
    topology: Topology, overrides: Iterable[Override], at: datetime
) -> _Standing:
    """How each override not withdrawn stands at a moment, what those that
    apply change in the topology, and what they tell discovery."""
    found = _Standing([], [], {}, {}, {})
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
            found.changing.append((len(found.now), edits))
        if state == "active" and o.target.kind == "device" and o.value:
            if o.kind in ("rename", "alias"):
                found.names[o.value] = o.target.id
        if state == "active" and o.target.kind == "port" and o.value:
            port = (o.target.id, port_key(o.target.interface or ""))
            if o.kind == "one-device":
                found.one_device[port] = o.value
            elif o.kind == "ignore-neighbor":
                found.ignored.setdefault(port, set()).add(o.value)
        found.now.append(
            OverrideNow(
                **dict(o),
                state=state,
                reason=reason if state == "not-applied" else None,
            )
        )
    return found


def apply(
    topology: Topology,
    overrides: Iterable[Override],
    at: datetime,
    rules: Iterable[Rule] = (),
) -> Overridden:
    """The topology with the overrides and rules that apply at a moment applied.

    The changes to the topology are made together and validated once, as
    validating a large topology takes most of a second; only if it will not
    take them all are they made one at a time, to find which it refuses.
    Rules' changes come first, so where an override on the object changes
    the same field, it wins.

    Args:
        topology: The documentation, with its fixes.
        overrides: Every override, oldest first; withdrawn ones are skipped.
        at: The moment, for which have expired.
        rules: Every rule, oldest first; withdrawn ones are skipped.

    Returns:
        The topology changed by locks, sites' new names, and hiding from
        status; the rules discovery takes from names and ports; and how
        each override and rule stands.

    Raises:
        None
    """
    standing = _standing(topology, overrides, at)
    alive = [r for r in rules if r.withdrawn is None]
    ruled, by_rules, ports = _ruled(
        topology, standing.active(), standing.edits(), alive, at
    )
    every: list[tuple[Ref, list[Edit]]] = [
        *((("rule", i), edits) for i, edits in by_rules),
        *((("override", i), edits) for i, edits in standing.changing),
    ]
    return Overridden(
        topology=_changed(topology, every, standing.now, ruled),
        rules=NeighborRules(
            names=standing.names,
            one_device=standing.one_device,
            ignored={p: frozenset(v) for p, v in standing.ignored.items()},
            ports=tuple(ports),
        ),
        now=standing.now,
        ruled=ruled,
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


def _slot(target: Target, kind: OverrideKind, key: str | None) -> tuple[object, ...]:
    """What an object can have one of at a time: a label of a key, a lock of
    a field, one hiding of each kind."""
    return (target.kind, target.id, target.interface, kind, key)


def _ruled(
    topology: Topology,
    active: list[OverrideNow],
    edits: list[Edit],
    rules: list[Rule],
    at: datetime,
) -> tuple[list[RuleNow], list[tuple[int, list[Edit]]], list[PortRule]]:
    """How each rule stands, what each changes in the topology, and what
    those on ports tell discovery.

    Rules match the topology as the overrides on single objects leave it.
    Newer rules claim what they match first, after those overrides, so an
    override on the object wins over any rule, and a newer rule over an
    older one, where an object has one of a kind at a time.

    Args:
        topology: The documentation, with its fixes.
        active: The overrides on single objects that apply.
        edits: What they change in the topology.
        rules: Every rule not withdrawn, oldest first.
        at: The moment, for which have expired.

    Returns:
        How each rule stands, oldest first; where each that changes the
        topology is in that list, with its edits, oldest first; and the
        rules on ports, oldest first.
    """
    if not rules:
        return [], [], []
    matcher = _Matcher(_with(topology, edits, validate=False), active)
    held = {_slot(o.target, o.kind, o.key) for o in active if o.kind in SINGLE}
    found: dict[int, RuleNow] = {}
    changing: list[tuple[int, list[Edit]]] = []
    ports: list[PortRule] = []
    for i in reversed(range(len(rules))):
        r = rules[i]
        if r.expires is not None and r.expires <= at:
            found[i] = RuleNow(**dict(r), state="expired")
            continue
        out = {(e.target.kind, e.target.id) for e in r.excepted}
        mine: list[Target] = []
        beaten: list[Target] = []
        for t in matcher.matching(r.match):
            if (t.kind, t.id) in out:
                continue
            if r.kind in SINGLE and r.match.of != "port":
                slot = _slot(t, r.kind, r.key)
                if slot in held:
                    beaten.append(t)
                    continue
                held.add(slot)
            mine.append(t)
        found[i] = RuleNow(
            **dict(r),
            state="active",
            matches=[RuleMatch(target=t) for t in mine],
            overridden=beaten,
        )
        if r.match.of == "port":
            ports.append(
                PortRule(
                    devices=frozenset(t.id for t in mine),
                    interfaces=tuple(r.match.interface),
                    kind="one-device" if r.kind == "one-device" else "ignore-neighbor",
                    neighbor=r.value or "*",
                )
            )
        elif made := _rule_edits(matcher.topology, r, mine):
            changing.append((i, made))
    return [found[i] for i in range(len(rules))], changing[::-1], ports[::-1]


def _rule_edits(topology: Topology, r: Rule, on: list[Target]) -> list[Edit]:
    """What a rule changes in the topology, on what it applies on."""
    if r.kind == "lock" and r.key:
        return [(t.kind, t.id, r.key, r.value) for t in on]
    if r.kind == "hide-status":
        return [
            (k, key, "priority", "ignored")
            for t in on
            for k, key in _quiet(topology, t)
        ]
    return []


class _Matcher:
    """Which objects a rule's tests match, on the topology as the fixes and
    the overrides on single objects leave it: their tags, new names, and
    aliases count, as locked fields do."""

    def __init__(self, topology: Topology, active: Iterable[OverrideNow]) -> None:
        self.topology = topology
        self._added: dict[tuple[str, str], dict[str, list[str]]] = {}
        for o in active:
            if o.kind in ("tag", "rename", "alias") and o.value:
                test = "tag" if o.kind == "tag" else "name"
                by = self._added.setdefault((o.target.kind, o.target.id), {})
                by.setdefault(test, []).append(o.value)
        self._sites: dict[str, Site] = {s.code: s for s in topology.sites}
        self._devices: dict[str, Device] = {d.name: d for d in topology.devices}
        self._externals: dict[str, External] = {e.name: e for e in topology.externals}
        self._parents = {r.name: r.parent for r in topology.regions}
        self._ratings: dict[str, str] | None = None

    def matching(self, match: Match) -> list[Target]:
        """Everything a rule's tests match.

        Args:
            match: The tests.

        Returns:
            The objects that pass them all, in the topology's order; for a
            rule on ports, their devices.
        """
        kind: TargetKind = "device" if match.of == "port" else match.of
        tests = match.tests()
        found: list[Target] = []
        for item in getattr(self.topology, _LISTS[kind]):
            key = _key(kind, item)
            if all(
                like(patterns, *self._values(kind, key, item, test))
                for test, patterns in tests.items()
            ):
                found.append(Target(kind=kind, id=key))
        return found

    def _values(
        self, kind: TargetKind, key: str, item: BaseModel, test: TestField
    ) -> list[str | None]:
        """The values of an object a test can match."""
        added = self._added.get((kind, key), {})
        if test == "name":
            return [
                key,
                getattr(item, "name", None),
                *added.get("name", []),
                *_cids(item),
            ]
        if test == "tag":
            return [*getattr(item, "tags", []), *added.get("tag", [])]
        if test in ("site", "region"):
            sites = [self._sites[c] for c in self._codes(item) if c in self._sites]
            if test == "site":
                return [v for s in sites for v in (s.code, s.name)]
            return [r for s in sites for r in self._regions(s.region)]
        if test == "role" and isinstance(item, Link):
            roles = link_roles(item, self._externals)
            if roles.edges:
                return list(roles.edges)
            return ["tbd" if roles.source == "tbd" else "internal"]
        if test == "priority" and isinstance(item, Link):
            if self._ratings is None:
                self._ratings = {
                    k: r.priority for k, r in ratings(self.topology).items()
                }
            return [self._ratings.get(item.id)]
        return [text(getattr(item, test, None)) or None]

    def _regions(self, region: str | None) -> list[str]:
        """A region and every region it is in."""
        found: list[str] = []
        while region is not None and region not in found:
            found.append(region)
            region = self._parents.get(region)
        return found

    def _codes(self, item: BaseModel) -> list[str]:
        """The sites an object is at: a site's own, a device's, either end's."""
        if isinstance(item, Site):
            return [item.code]
        if isinstance(item, Device):
            return [item.site]
        if isinstance(item, Link):
            ends = [e.device for e in device_ends(item)]
        elif isinstance(item, Lag):
            ends = [item.a.device, item.b.device]
        else:
            return []
        return [self._devices[d].site for d in ends if d in self._devices]


def _cids(item: BaseModel) -> list[str | None]:
    """A link's or port channel's circuit IDs, each side, and the
    enterprise's: what else it is known by."""
    sides: list[Sides | None] = []
    if isinstance(item, (Link, Lag)):
        sides = [item.enterprise_cid, item.circuit.circuit_id if item.circuit else None]
    return [v for s in sides if s for v in (s.a, s.z)]


def _changed(
    topology: Topology,
    changing: list[tuple[Ref, list[Edit]]],
    now: list[OverrideNow],
    ruled: list[RuleNow],
) -> Topology:
    """The topology with each override's and rule's edits made, all at once
    if it takes them, else one at a time, marking those it refuses not
    applied; and, on each lock that differs and each site renamed, what the
    topology says.

    Args:
        topology: The documentation, with its fixes.
        changing: Each override and rule that changes it, and its edits, in
            the order they are made.
        now: How each override stands, updated in place.
        ruled: How each rule stands, updated in place.

    Returns:
        The topology changed.
    """
    if not changing:
        return topology

    def refuse(ref: Ref, reason: str) -> None:
        kind, i = ref
        if kind == "override":
            now[i] = now[i].model_copy(
                update={"state": "not-applied", "reason": reason}
            )
        else:
            ruled[i] = ruled[i].model_copy(
                update={
                    "state": "not-applied",
                    "reason": reason,
                    "matches": [],
                    "overridden": [],
                }
            )

    try:
        result = _with(topology, [e for _, edits in changing for e in edits])
    except ValidationError:
        result = topology
        for ref, edits in changing:
            try:
                result = _with(result, edits)
            except ValidationError as e:
                refuse(ref, _error(e))
    before, after = _lookup(topology), _lookup(result)
    for (kind, i), _ in changing:
        if kind == "rule":
            r = ruled[i]
            if r.state != "active" or r.kind != "lock" or not r.key:
                continue
            field = r.key
            matches = []
            for m in r.matches:
                t = m.target
                was = text(getattr(before(t.kind, t.id), field))
                if was != text(getattr(after(t.kind, t.id), field)):
                    m = m.model_copy(update={"topology_value": was})
                matches.append(m)
            ruled[i] = r.model_copy(update={"matches": matches})
            continue
        o = now[i]
        field = o.key if o.kind == "lock" else "name" if o.kind == "rename" else None
        if o.state != "active" or field is None:
            continue
        t = o.target
        was = text(getattr(before(t.kind, t.id), field))
        if was != text(getattr(after(t.kind, t.id), field)) or o.kind == "rename":
            now[i] = o.model_copy(update={"topology_value": was})
    return result


def preview(
    topology: Topology,
    documented: Topology,
    overrides: Iterable[Override],
    rules: Iterable[Rule],
    made: Rule,
    at: datetime,
) -> tuple[RuleNow, PortRule | None]:
    """How a rule would stand, made now, without validating the topology
    again unless it changes it.

    Args:
        topology: The documentation, with its fixes.
        documented: It with the overrides and rules there are now applied.
        overrides: Every override, oldest first.
        rules: Every rule, oldest first.
        made: The rule, newest of all.
        at: The moment.

    Returns:
        How it would stand, ``not-applied`` with the reason where the
        topology would not take it; and, for a rule on ports, what it would
        tell discovery.

    Raises:
        None
    """
    standing = _standing(topology, overrides, at)
    alive = [r for r in rules if r.withdrawn is None]
    ruled, _, ports = _ruled(
        topology, standing.active(), standing.edits(), [*alive, made], at
    )
    found = ruled[-1]
    if made.match.of == "port":
        return found, ports[-1]
    edits = _rule_edits(documented, made, [m.target for m in found.matches])
    if edits:
        try:
            _with(documented, edits)
        except ValidationError as e:
            found = found.model_copy(
                update={"state": "not-applied", "reason": _error(e)}
            )
    return found, None


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
    found = [
        OverrideLine(event=event, at=at, override=o)
        for o in overrides
        for event, at in _moments(o, since, until)
    ]
    return sorted(found, key=lambda line: line.at, reverse=True)


def rule_lines(
    rules: Iterable[Rule], since: datetime, until: datetime
) -> list[RuleLine]:
    """The rules made, withdrawn, or expired in a span, latest first.

    Args:
        rules: Every rule, withdrawn ones too.
        since: The span's start.
        until: Its end.

    Returns:
        A line for each of those moments in the span, as for overrides.

    Raises:
        None
    """
    found = [
        RuleLine(event=event, at=at, rule=r)
        for r in rules
        for event, at in _moments(r, since, until)
    ]
    return sorted(found, key=lambda line: line.at, reverse=True)


def _moments(
    o: Override | Rule, since: datetime, until: datetime
) -> list[tuple[LineEvent, datetime]]:
    """When an override or rule was made, withdrawn, and expired, in a span:
    one withdrawn before it expired did not expire."""
    found: list[tuple[LineEvent, datetime]] = []
    if since <= o.at <= until:
        found.append(("made", o.at))
    if o.withdrawn and since <= o.withdrawn.at <= until:
        found.append(("withdrawn", o.withdrawn.at))
    if (
        o.expires
        and since <= o.expires <= until
        and (o.withdrawn is None or o.withdrawn.at > o.expires)
    ):
        found.append(("expired", o.expires))
    return found


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


def new_rule(made: RuleIn, at: datetime) -> Rule:
    """Record a rule someone makes.

    Args:
        made: The rule.
        at: When.

    Returns:
        It, with a new id.

    Raises:
        None
    """
    return Rule(id=uuid.uuid4().hex[:12], **dict(made), at=at)


def same_rule(a: Rule, b: RuleIn) -> bool:
    """Whether a new rule repeats one there.

    Args:
        a: A rule not withdrawn.
        b: A new one.

    Returns:
        True for the same tests, kind, key, and value, ignoring case.

    Raises:
        None
    """
    return (
        a.match == b.match
        and a.kind == b.kind
        and a.key == b.key
        and (a.value or "").lower() == (b.value or "").lower()
    )


class OverrideStore:
    """Every override and rule for one topology, in a JSON file created on
    the first one."""

    def __init__(self, path: Path) -> None:
        """Use an overrides file.

        Args:
            path: The JSON file.

        Raises:
            OverridesError: If the file exists but cannot be read.
        """
        self.path = path
        found = self._read()
        self._overrides = found.overrides
        self._rules = found.rules

    def overrides(self) -> list[Override]:
        """Every override, withdrawn ones too, oldest first.

        Returns:
            The overrides.

        Raises:
            None
        """
        return list(self._overrides)

    def rules(self) -> list[Rule]:
        """Every rule, withdrawn ones too, oldest first.

        Returns:
            The rules.

        Raises:
            None
        """
        return list(self._rules)

    def save(
        self, overrides: list[Override] | None = None, rules: list[Rule] | None = None
    ) -> None:
        """Replace the overrides, or the rules, or both.

        Args:
            overrides: Every override, oldest first; None to keep them.
            rules: Every rule, oldest first; None to keep them.

        Raises:
            OSError: If the file cannot be written.
        """
        overrides = self._overrides if overrides is None else list(overrides)
        rules = self._rules if rules is None else list(rules)
        temporary = self.path.with_name(f".{self.path.name}.tmp")
        body = _File(overrides=overrides, rules=rules).model_dump(mode="json")
        temporary.write_text(json.dumps(body, indent=1), encoding="utf-8")
        os.replace(temporary, self.path)
        self._overrides = overrides
        self._rules = rules

    def _read(self) -> _File:
        try:
            raw = self.path.read_bytes()
        except FileNotFoundError:
            return _File()
        except OSError as e:
            raise OverridesError(f"{self.path}: {e}") from e
        try:
            return _File.model_validate_json(raw)
        except ValidationError as e:
            raise OverridesError(f"{self.path}: {e}") from e
