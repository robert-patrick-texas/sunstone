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
"""

from datetime import datetime
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


class StateSource(Protocol):
    """Anything that can report the network's current state."""

    def snapshot(self, now: datetime) -> NetworkState:
        """Report the state as of a moment.

        Args:
            now: The moment, timezone-aware.

        Returns:
            The snapshot.

        Raises:
            None
        """
        ...
