"""Live state of the network: device reachability and interface load.

A state source reports two kinds of observation, in the shapes monitoring
tools such as vakr produce:

- per device: up or down, and round-trip time and loss as measured from
  each monitoring position;
- per interface, keyed by device name and interface name: operational status
  and utilization in each direction.

Sunstone works out each link's state from the interfaces at its two ends.

Sources cover only what they monitor. A device or interface absent from a
snapshot is not monitored; one present but ``stale`` is monitored with no
fresh reading. Neither is ever reported as zero.

Sources also keep a while of history: the state as of any moment in it,
the changes they saw, and one device's readings over time.
"""

from datetime import datetime, timedelta
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MonitoringPosition(_Record):
    """A place measurements are taken from, such as a collector at a hub."""

    name: str
    site: str


class Reachability(_Record):
    """Round-trip time and loss to a device from one monitoring position."""

    position: str
    rtt_ms: float | None
    loss_pct: float | None


class DeviceState(_Record):
    """Whether a monitored device answers, and how quickly."""

    device: str
    status: Literal["up", "down"]
    observed_at: datetime
    stale: bool
    reachability: list[Reachability]


class InterfaceState(_Record):
    """A monitored interface's status and load, as a share of its speed."""

    device: str
    interface: str
    oper: Literal["up", "down"]
    in_pct: float | None
    out_pct: float | None
    observed_at: datetime
    stale: bool


class NetworkState(_Record):
    """One snapshot of everything a source monitors."""

    source: str
    generated_at: datetime
    positions: list[MonitoringPosition]
    devices: list[DeviceState]
    interfaces: list[InterfaceState]


EventKind = Literal[
    "down",
    "up",
    "nodata",
    "reporting",
    "loss",
    "loss-cleared",
    "link-down",
    "link-up",
    "busy",
    "congested",
    "load-normal",
]


class StateEvent(_Record):
    """A change a source saw: a device or link going down or coming back,
    readings stopping or resuming, packet loss starting or clearing, or a
    link's load crossing 80% or 95% (``pct`` is the load after the change).
    """

    at: datetime
    kind: EventKind
    device: str | None = None
    link: str | None = None
    pct: float | None = None
    planned: bool = False
    """Maintenance open at the time accounts for it."""


class EventLog(_Record):
    """The changes seen between two moments, oldest first."""

    since: datetime
    until: datetime
    events: list[StateEvent]


class InterfaceHistory(_Record):
    """One interface's readings at each step of a device history."""

    interface: str
    oper: list[Literal["up", "down"] | None]
    in_pct: list[float | None]
    out_pct: list[float | None]


class DeviceHistory(_Record):
    """One device's readings at regular steps, oldest first.

    Step ``i`` is at ``start + i * step_s``. Values are None where there was
    no fresh reading: the device was down, cut off, or not reporting.
    """

    device: str
    start: datetime
    step_s: int
    status: list[Literal["up", "down", "nodata"]]
    rtt_ms: dict[str, list[float | None]]
    loss_pct: dict[str, list[float | None]]
    interfaces: list[InterfaceHistory]


class StateSource(Protocol):
    """Anything that can report the network's state, now and for a while back."""

    retention: timedelta
    """How far back history goes."""

    def snapshot(self, now: datetime) -> NetworkState:
        """Report the state as of a moment.

        Args:
            now: The moment, timezone-aware, within the retention.

        Returns:
            The snapshot.

        Raises:
            None
        """
        ...

    def events(self, since: datetime, until: datetime) -> list[StateEvent]:
        """Report the changes seen after one moment, up to another.

        Args:
            since: Start, exclusive, timezone-aware.
            until: End, inclusive.

        Returns:
            The events, oldest first.

        Raises:
            None
        """
        ...

    def history(
        self, device: str, since: datetime, until: datetime
    ) -> DeviceHistory | None:
        """Report one device's readings over a span.

        Args:
            device: Device name.
            since: Start, timezone-aware.
            until: End.

        Returns:
            The readings, or None if the source does not monitor the device.

        Raises:
            None
        """
        ...
