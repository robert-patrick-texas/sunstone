"""Simulated live state, standing in for real monitoring sources.

Every value is a function of the topology and the moment asked about, so all
viewers see the same picture and tests can fix the clock:

- Coverage: every WAN edge, core, and distribution device is monitored, and
  about half the access switches, the way a tool like vakr watches the
  devices that matter rather than everything.
- Load: each link has a base level for its kind, a daily cycle in its site's
  local time, and slow drift. A few WAN circuits run hot in each 15-minute
  window.
- Faults: in each 5-minute window a few monitored devices are down, a few
  stop reporting, and a few drop packets. A down device cannot be polled, so
  its interfaces are absent; the far end of each of its links reports the
  link down.
- Reachability: round-trip time from each monitoring position grows with
  distance, about 1 ms per 100 km of fiber, plus jitter.
"""

import hashlib
import math
from datetime import datetime, timedelta
from typing import Literal

from sunstone.live import (
    DeviceState,
    InterfaceState,
    MonitoringPosition,
    NetworkState,
    Reachability,
)
from sunstone.model import Link, Site, Topology

FAULT_WINDOW_S = 300
LOAD_WINDOW_S = 900
STALE_AGE = timedelta(minutes=10)

Condition = Literal["up", "down", "stale", "lossy"]


def _unit(*parts: object) -> float:
    """A stable pseudo-random number in [0, 1) for the given parts."""
    digest = hashlib.blake2b("|".join(map(str, parts)).encode(), digest_size=8)
    return int.from_bytes(digest.digest()) / 2**64


def _km(a: Site, b: Site) -> float:
    """Great-circle distance between two sites."""
    la1, la2 = math.radians(a.lat), math.radians(b.lat)
    dlat, dlon = la2 - la1, math.radians(b.lon - a.lon)
    h = (
        math.sin(dlat / 2) ** 2
        + math.cos(la1) * math.cos(la2) * math.sin(dlon / 2) ** 2
    )
    return 2 * 6371 * math.asin(math.sqrt(h))


def _pct(value: float) -> float:
    """A percentage clamped to 0-100, to one decimal."""
    return round(min(100.0, max(0.0, value)), 1)


def _pick(names: list[str], count: int, *salt: object) -> set[str]:
    """A stable choice of ``count`` names that changes with ``salt``."""
    return set(sorted(names, key=lambda n: _unit(*salt, n))[:count])


class SimulatedState:
    """A state source that makes up plausible observations."""

    source = "simulated"

    def __init__(self, topology: Topology) -> None:
        """Prepare to simulate one topology.

        Args:
            topology: The network to simulate.

        Raises:
            None
        """
        self.topology = topology
        self.sites = {s.code: s for s in topology.sites}
        self.devices = {d.name: d for d in topology.devices}
        self.monitored = [
            d.name
            for d in topology.devices
            if d.role != "access" or _unit("monitored", d.name) < 0.5
        ]
        self.positions = self._positions()

    def _positions(self) -> list[MonitoringPosition]:
        """Collectors at up to two core sites, named by which is further east."""
        cores = {d.site for d in self.topology.devices if d.role == "core"}
        hubs = [s for s in self.topology.sites if s.code in cores][:2]
        hubs = hubs or self.topology.sites[:1]
        hubs.sort(key=lambda s: s.lon)
        names = ["west", "east"] if len(hubs) == 2 else ["central"]
        return [
            MonitoringPosition(name=n, site=s.code)
            for n, s in zip(names, hubs, strict=True)
        ]

    def snapshot(self, now: datetime) -> NetworkState:
        """Report the simulated state as of a moment.

        Args:
            now: The moment, timezone-aware.

        Returns:
            The snapshot.

        Raises:
            None
        """
        t = now.timestamp()
        window = int(t // FAULT_WINDOW_S)
        count = len(self.monitored)
        down = _pick(self.monitored, max(1, count // 250), "down", window)
        up = [n for n in self.monitored if n not in down]
        stale = _pick(up, max(1, count // 150), "stale", window)
        lossy = _pick(
            [n for n in up if n not in stale], max(1, count // 200), "loss", window
        )
        condition: dict[str, Condition] = {
            **{n: "down" for n in down},
            **{n: "stale" for n in stale},
            **{n: "lossy" for n in lossy},
        }
        devices = [
            self._device(name, now, condition.get(name, "up"))
            for name in self.monitored
        ]
        interfaces = self._interfaces(now, down, stale)
        return NetworkState(
            source=self.source,
            generated_at=now,
            positions=self.positions,
            devices=devices,
            interfaces=interfaces,
        )

    def _device(self, name: str, now: datetime, condition: Condition) -> DeviceState:
        down = condition == "down"
        seen = now - STALE_AGE if condition == "stale" else now
        t = seen.timestamp()
        site = self.sites[self.devices[name].site]
        reachability = []
        for position in self.positions:
            if down:
                reachability.append(
                    Reachability(position=position.name, rtt_ms=None, loss_pct=100)
                )
                continue
            km = _km(site, self.sites[position.site])
            jitter = 0.3 * math.sin(t / 60 + 6 * _unit("phase", name)) + 0.2 * _unit(
                name, int(t)
            )
            rtt = 0.4 + km / 100 + 0.5 * _unit("offset", name) + jitter
            lost = 1 + 3 * _unit("lost", name, position.name, int(t // FAULT_WINDOW_S))
            loss = round(lost, 1) if condition == "lossy" else 0.0
            reachability.append(
                Reachability(
                    position=position.name,
                    rtt_ms=round(max(rtt, 0.1), 2),
                    loss_pct=loss,
                )
            )
        status = "down" if down else "up"
        return DeviceState(
            device=name,
            status=status,
            observed_at=seen,
            stale=condition == "stale",
            reachability=reachability,
        )

    def _interfaces(
        self, now: datetime, down: set[str], stale: set[str]
    ) -> list[InterfaceState]:
        monitored = set(self.monitored)
        wan = [link.id for link in self.topology.links if link.kind == "wan"]
        window = int(now.timestamp() // LOAD_WINDOW_S)
        hot = _pick(wan, max(1, len(wan) // 40), "hot", window)
        out: list[InterfaceState] = []
        for link in self.topology.links:
            link_down = link.a.device in down or link.b.device in down
            for near, forward in ((link.a, True), (link.b, False)):
                if near.device not in monitored or near.device in down:
                    continue
                seen = now - STALE_AGE if near.device in stale else now
                in_pct, out_pct = 0.0, 0.0
                if not link_down:
                    a_to_b, b_to_a = self._load(link, seen, link.id in hot)
                    sent, received = (a_to_b, b_to_a) if forward else (b_to_a, a_to_b)
                    # Both ends measure the same traffic, give or take a little.
                    salt = (near.device, near.interface, int(seen.timestamp()))
                    wobble = _unit("measure", *salt) - 0.5
                    in_pct, out_pct = _pct(received + wobble), _pct(sent + wobble)
                out.append(
                    InterfaceState(
                        device=near.device,
                        interface=near.interface,
                        oper="down" if link_down else "up",
                        in_pct=in_pct,
                        out_pct=out_pct,
                        observed_at=seen,
                        stale=near.device in stale,
                    )
                )
        return out

    def _load(self, link: Link, at: datetime, hot: bool) -> tuple[float, float]:
        """Percent load each way: A to B, then B to A."""
        t = at.timestamp()
        site = self.sites[self.devices[link.a.device].site]
        local_hour = (t / 3600 + site.lon / 15) % 24
        daily = 0.6 + 0.4 * math.cos(2 * math.pi * (local_hour - 14) / 24)
        base = (
            (0.3 + 0.35 * _unit("base", link.id))
            if link.kind == "wan"
            else (0.08 + 0.35 * _unit("base", link.id))
        )
        drift = 1 + 0.15 * math.sin(t / 600 + 6 * _unit("drift", link.id))
        level = 100 * base * daily * drift
        a_to_b = level * (0.8 + 0.4 * _unit("ab", link.id))
        b_to_a = level * (0.5 + 0.5 * _unit("ba", link.id))
        if hot:
            a_to_b = 92 + 7 * _unit("heat", link.id)
        return a_to_b, b_to_a
