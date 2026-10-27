"""Topology data model: sites, devices, and interface-to-interface links.

Each link end is a device name plus an interface name. NetBox cables, LLDP/CDP
neighbor tables, and NMS exports all reduce to that shape, and it is the key
that other tools' interface references (vakr's, for one) will be matched on.
"""

from collections import Counter
from functools import cached_property
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

Role = Literal["wan-edge", "core", "distribution", "access"]
LinkKind = Literal["lan", "wan"]


class _Record(BaseModel):
    # Unknown keys are rejected so a typo in a hand-edited file is an error,
    # not a silently missing value.
    model_config = ConfigDict(extra="forbid", frozen=True)


class Site(_Record):
    """A physical location with map coordinates."""

    code: str
    name: str
    region: str | None = None
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class Device(_Record):
    """A network device at one site."""

    name: str
    site: str
    role: Role
    platform: str | None = None
    mgmt_ip: str | None = None


class Endpoint(_Record):
    """One end of a link: a device's interface, optionally a LAG member."""

    device: str
    interface: str
    lag: str | None = None


class Circuit(_Record):
    """A carrier circuit carrying a WAN link."""

    provider: str
    circuit_id: str


class Link(_Record):
    """A physical connection between two device interfaces."""

    a: Endpoint
    b: Endpoint
    speed_mbps: int = Field(gt=0)
    kind: LinkKind = "lan"
    circuit: Circuit | None = None

    # Worked out once: links are frozen, and ids are looked up all the time.
    @computed_field
    @cached_property
    def id(self) -> str:
        """Stable identifier that does not depend on which end is listed first.

        Returns:
            The two ``device:interface`` ends, sorted and joined with ``--``.
        """
        ends = sorted(f"{e.device}:{e.interface}" for e in (self.a, self.b))
        return "--".join(ends)


class Topology(_Record):
    """A whole network: every site, device, and link."""

    sites: list[Site]
    devices: list[Device]
    links: list[Link]

    @model_validator(mode="after")
    def _check_references(self) -> Self:
        """Reject duplicates and references to things that do not exist.

        Returns:
            The topology, unchanged.

        Raises:
            ValueError: Listing every problem found, one per line.
        """
        problems = [
            f"duplicate site code {code!r}"
            for code, n in Counter(s.code for s in self.sites).items()
            if n > 1
        ]
        problems += [
            f"duplicate device name {name!r}"
            for name, n in Counter(d.name for d in self.devices).items()
            if n > 1
        ]
        site_codes = {s.code for s in self.sites}
        problems += [
            f"device {d.name!r} is at unknown site {d.site!r}"
            for d in self.devices
            if d.site not in site_codes
        ]
        device_names = {d.name for d in self.devices}
        used: Counter[tuple[str, str]] = Counter()
        for link in self.links:
            if link.a.device == link.b.device:
                problems.append(f"link {link.id} connects a device to itself")
            for end in (link.a, link.b):
                used[(end.device, end.interface)] += 1
                if end.device not in device_names:
                    problems.append(
                        f"link {link.id} references unknown device {end.device!r}"
                    )
        problems += [
            f"interface {dev}:{ifname} is used by {n} links"
            for (dev, ifname), n in used.items()
            if n > 1
        ]
        if problems:
            raise ValueError("\n".join(problems))
        return self
