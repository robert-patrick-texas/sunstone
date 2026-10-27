"""Simulated live state, standing in for real monitoring sources.

Every value is a function of the topology and the moment asked about, so all
viewers see the same picture, any moment of the last day can be replayed,
and tests can fix the clock:

- Coverage: every WAN edge, core, and distribution device is monitored, and
  about half the access switches, the way a tool like vakr watches the
  devices that matter rather than everything.
- Load: each link has a base level for its kind, a daily cycle in its site's
  local time, and slow drift. A few WAN circuits run hot in each 15-minute
  window.
- Faults come and go in 5-minute steps. At any time a few monitored devices
  are down, a few have stopped reporting, a few drop packets, and a few
  carrier circuits are down. Each incident lasts 15 minutes to an hour, and
  they start and end at different times. In about a third of half-hours a
  branch loses all of its circuits. A down device cannot be polled, so its
  interfaces are absent; the far end of each of its links reports the link
  down.
- Planned work: devices and links in an open maintenance window are down
  for all of it, as the work would take them down.
- Cut off: a device the monitoring positions cannot reach, over devices and
  links that are up, looks down to them, and its interfaces go unpolled.
- Reachability: round-trip time from each monitoring position grows with
  distance, about 1 ms per 100 km of fiber, plus jitter.
- History: events are what changed from one 5-minute step to the next, and
  load crossing 80% or 95% at those steps.
"""

import hashlib
import math
from collections.abc import Mapping, Set
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol

from sunstone.impact import Failures
from sunstone.live import (
    DeviceHistory,
    DeviceState,
    EventKind,
    InterfaceHistory,
    InterfaceState,
    MonitoringPosition,
    NetworkState,
    Reachability,
    StateEvent,
)
from sunstone.model import Endpoint, Link, Site, Topology

FAULT_WINDOW_S = 300
LOAD_WINDOW_S = 900
STALE_AGE = timedelta(minutes=10)
RETENTION = timedelta(hours=24)
# Each incident lasts this many fault windows, at least and at most.
MIN_RUN, MAX_RUN = 3, 12
# Branch outages last this many fault windows, and happen in this share of them.
ISOLATED_RUN = 6
ISOLATED_SHARE = 0.3
HIGH_PCT, CRITICAL_PCT = 80, 95
MAX_CACHED_WINDOWS = 1000


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


def _at(window: int) -> datetime:
    """When a fault window starts."""
    return datetime.fromtimestamp(window * FAULT_WINDOW_S, UTC)


def _window(at: datetime) -> int:
    """The fault window a moment falls in."""
    return int(at.timestamp() // FAULT_WINDOW_S)


def _incidents(names: list[str], slots: int, kind: str, window: int) -> dict[str, int]:
    """Who has an incident of a kind in a fault window, and the window it began.

    Each of ``slots`` runs incidents back to back, all of one length for that
    slot and offset differently from the others, so about ``slots`` are open
    at any time and they change one at a time.
    """
    found: dict[str, int] = {}
    if not names:
        return found
    for slot in range(slots):
        length = MIN_RUN + int(_unit(kind, "length", slot) * (MAX_RUN - MIN_RUN + 1))
        offset = int(_unit(kind, "offset", slot) * length)
        run = (window + offset) // length
        name = names[int(_unit(kind, slot, run) * len(names))]
        found.setdefault(name, run * length - offset)
    return found


# One interface's oper status, load in, and load out, step by step.
_Columns = tuple[
    list[Literal["up", "down"] | None], list[float | None], list[float | None]
]


class Plans(Protocol):
    """Maintenance planned on the network."""

    version: int
    """Goes up whenever the plans change."""

    def planned_at(self, at: datetime) -> Failures:
        """Devices and links being worked on at a moment."""
        ...


@dataclass(frozen=True)
class _Faults:
    """What is wrong during one fault window."""

    down: frozenset[str]
    unreachable: frozenset[str]
    stale: Mapping[str, datetime]
    """Monitored devices not reporting, with the time of their last reading."""
    lossy: frozenset[str]
    cut: frozenset[str]

    @property
    def silent(self) -> frozenset[str]:
        """Devices that cannot be polled: down, or cut off."""
        return self.down | self.unreachable


class SimulatedState:
    """A state source that makes up plausible observations."""

    source = "simulated"
    retention = RETENTION

    def __init__(self, topology: Topology, plans: Plans | None = None) -> None:
        """Prepare to simulate one topology.

        Args:
            topology: The network to simulate.
            plans: Maintenance to act out, if any.

        Raises:
            None
        """
        self.topology = topology
        self.plans = plans
        self.sites = {s.code: s for s in topology.sites}
        self.devices = {d.name: d for d in topology.devices}
        self.monitored = [
            d.name
            for d in topology.devices
            if d.role != "access" or _unit("monitored", d.name) < 0.5
        ]
        self.watched = set(self.monitored)
        self.positions = self._positions()
        position_sites = {p.site for p in self.positions}
        at_positions = [d for d in topology.devices if d.site in position_sites]
        # The collectors hang off the core at their sites.
        self.seeds = [d.name for d in at_positions if d.role == "core"] or [
            d.name for d in at_positions
        ]
        self.branches = [s.code for s in topology.sites if s.code not in position_sites]
        self.wan = [link.id for link in topology.links if link.kind == "wan"]
        self.circuits_of: dict[str, set[str]] = {}
        self.ends_of: dict[str, list[tuple[Link, Endpoint, bool]]] = {}
        self.adjacent: dict[str, list[tuple[str, str]]] = {}
        for link in topology.links:
            for near, far, forward in ((link.a, link.b, True), (link.b, link.a, False)):
                self.ends_of.setdefault(near.device, []).append((link, near, forward))
                self.adjacent.setdefault(near.device, []).append((far.device, link.id))
                if link.kind == "wan":
                    site = self.devices[near.device].site
                    self.circuits_of.setdefault(site, set()).add(link.id)
        # Links whose load can cross the high mark, for load events.
        self.loaded = [
            link
            for link in topology.links
            if link.kind == "wan" or self._peak(link) >= HIGH_PCT
        ]
        # Kept with the version of the plans they were worked out under.
        self._faults_by_window: dict[int, tuple[int, _Faults]] = {}
        self._loads_by_window: dict[int, tuple[int, dict[str, float]]] = {}

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
        faults = self._faults(_window(now))
        hot = self._hot(now)
        devices = [self._device(name, now, faults) for name in self.monitored]
        interfaces = [
            reading
            for link in self.topology.links
            for near, forward in ((link.a, True), (link.b, False))
            if (reading := self._reading(link, near, forward, now, faults, hot))
        ]
        return NetworkState(
            source=self.source,
            generated_at=now,
            positions=self.positions,
            devices=devices,
            interfaces=interfaces,
        )

    def events(self, since: datetime, until: datetime) -> list[StateEvent]:
        """Report what changed at each 5-minute step after one moment, up to another.

        Args:
            since: Start, exclusive, timezone-aware.
            until: End, inclusive.

        Returns:
            The events, oldest first.

        Raises:
            None
        """
        first, last = _window(since) + 1, _window(until)
        before = self._faults(first - 1)
        bands = {link: _band(load) for link, load in self._loads(first - 1).items()}
        events: list[StateEvent] = []
        for window in range(first, last + 1):
            at = _at(window)
            now = self._faults(window)
            events += self._changes(at, before, now)
            for link, load in self._loads(window).items():
                band, old = _band(load), bands.get(link)
                bands[link] = band
                if old is not None and band != old:
                    events.append(
                        StateEvent(at=at, kind=BAND_EVENT[band], link=link, pct=load)
                    )
            before = now
        return events

    def history(
        self, device: str, since: datetime, until: datetime
    ) -> DeviceHistory | None:
        """Report one device's readings at each 5-minute step of a span.

        Args:
            device: Device name.
            since: Start, timezone-aware.
            until: End.

        Returns:
            The readings, or None if the device is not monitored.

        Raises:
            None
        """
        if device not in self.watched:
            return None
        first = -(-int(since.timestamp()) // FAULT_WINDOW_S)
        steps = range(first, _window(until) + 1)
        status: list[Literal["up", "down", "nodata"]] = []
        rtt: dict[str, list[float | None]] = {p.name: [] for p in self.positions}
        loss: dict[str, list[float | None]] = {p.name: [] for p in self.positions}
        ends = sorted(self.ends_of.get(device, []), key=lambda e: e[1].interface)
        columns: list[_Columns] = [([], [], []) for _ in ends]
        for window in steps:
            at, faults = _at(window), self._faults(window)
            hot = self._hot(at)
            state = self._device(device, at, faults)
            fresh = state.status == "up" and not state.stale
            status.append(
                "down" if state.status == "down" else "up" if fresh else "nodata"
            )
            for r in state.reachability:
                rtt[r.position].append(r.rtt_ms if fresh else None)
                loss[r.position].append(r.loss_pct if fresh else None)
            for (link, near, forward), (oper, inbound, outbound) in zip(
                ends, columns, strict=True
            ):
                reading = self._reading(link, near, forward, at, faults, hot)
                if reading is None or reading.stale:
                    reading = None
                up = reading is not None and reading.oper == "up"
                oper.append(reading.oper if reading else None)
                inbound.append(reading.in_pct if reading and up else None)
                outbound.append(reading.out_pct if reading and up else None)
        return DeviceHistory(
            device=device,
            start=_at(first),
            step_s=FAULT_WINDOW_S,
            status=status,
            rtt_ms=rtt,
            loss_pct=loss,
            interfaces=[
                InterfaceHistory(
                    interface=near.interface,
                    oper=oper,
                    in_pct=inbound,
                    out_pct=outbound,
                )
                for (_, near, _), (oper, inbound, outbound) in zip(
                    ends, columns, strict=True
                )
            ],
        )

    def _faults(self, window: int) -> _Faults:
        """What is wrong in a fault window, worked out once and kept."""
        version = self.plans.version if self.plans else 0
        cached = self._faults_by_window.get(window)
        if cached is not None and cached[0] == version:
            return cached[1]
        count = len(self.monitored)
        down = set(_incidents(self.monitored, max(1, count // 250), "down", window))
        cut = set(_incidents(self.wan, max(1, len(self.wan) // 60), "cut", window))
        cut |= self._isolated(window)
        if self.plans:
            planned = self.plans.planned_at(_at(window))
            down |= planned.devices
            cut |= planned.links
        unreachable = self._unreachable(down, cut)
        silent = down | unreachable
        stale = {
            name: _at(start) - STALE_AGE
            for name, start in _incidents(
                self.monitored, max(1, count // 150), "stale", window
            ).items()
            if name not in silent
        }
        lossy = {
            name
            for name in _incidents(self.monitored, max(1, count // 200), "loss", window)
            if name not in silent and name not in stale
        }
        faults = _Faults(
            down=frozenset(down),
            unreachable=frozenset(unreachable),
            stale=stale,
            lossy=frozenset(lossy),
            cut=frozenset(cut),
        )
        if len(self._faults_by_window) >= MAX_CACHED_WINDOWS:
            self._faults_by_window.clear()
        self._faults_by_window[window] = (version, faults)
        return faults

    def _loads(self, window: int) -> dict[str, float]:
        """Load, in the busier direction, of each link that can run high and is
        observed at the start of a fault window; worked out once and kept.
        """
        version = self.plans.version if self.plans else 0
        cached = self._loads_by_window.get(window)
        if cached is not None and cached[0] == version:
            return cached[1]
        at, faults = _at(window), self._faults(window)
        hot = self._hot(at)
        loads: dict[str, float] = {}
        for link in self.loaded:
            ends = {link.a.device, link.b.device}
            if link.id in faults.cut or ends & faults.silent or not ends & self.watched:
                continue
            loads[link.id] = _pct(max(self._load(link, at, link.id in hot)))
        if len(self._loads_by_window) >= MAX_CACHED_WINDOWS:
            self._loads_by_window.clear()
        self._loads_by_window[window] = (version, loads)
        return loads

    def _isolated(self, window: int) -> set[str]:
        """Circuits of the branch, if any, that is cut off in a fault window."""
        run = window // ISOLATED_RUN
        if not self.branches or _unit("isolated", run) >= ISOLATED_SHARE:
            return set()
        site = self.branches[int(_unit("isolated-site", run) * len(self.branches))]
        return self.circuits_of.get(site, set())

    def _unreachable(self, down: set[str], cut: set[str]) -> set[str]:
        """Devices that are up but that no monitoring position can reach."""
        reached = {n for n in self.seeds if n not in down}
        frontier = list(reached)
        while frontier:
            device = frontier.pop()
            for neighbor, link in self.adjacent.get(device, []):
                if neighbor in reached or neighbor in down or link in cut:
                    continue
                reached.add(neighbor)
                frontier.append(neighbor)
        return set(self.devices) - reached - down

    def _hot(self, at: datetime) -> set[str]:
        """WAN circuits running hot at a moment."""
        window = int(at.timestamp() // LOAD_WINDOW_S)
        return _pick(self.wan, max(1, len(self.wan) // 40), "hot", window)

    def _changes(self, at: datetime, before: _Faults, now: _Faults) -> list[StateEvent]:
        """What the monitoring sees change from one fault window to the next."""
        events: list[StateEvent] = []

        def note(names: Set[str], kind: EventKind, field: str = "device") -> None:
            events.extend(
                StateEvent(at=at, kind=kind, **{field: name}) for name in sorted(names)
            )

        # Only monitored devices are seen going down or coming back.
        was, silent = before.silent & self.watched, now.silent & self.watched
        note(silent - was, "down")
        note(was - silent, "up")
        note(set(now.stale) - set(before.stale), "nodata")
        note(set(before.stale) - set(now.stale) - silent, "reporting")
        note(now.lossy - before.lossy, "loss")
        note(before.lossy - now.lossy - silent, "loss-cleared")
        note(now.cut - before.cut, "link-down", "link")
        note(before.cut - now.cut, "link-up", "link")
        return events

    def _device(self, name: str, now: datetime, faults: _Faults) -> DeviceState:
        down = name in faults.silent
        seen = faults.stale.get(name, now)
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
            loss = round(lost, 1) if name in faults.lossy else 0.0
            reachability.append(
                Reachability(
                    position=position.name,
                    rtt_ms=round(max(rtt, 0.1), 2),
                    loss_pct=loss,
                )
            )
        return DeviceState(
            device=name,
            status="down" if down else "up",
            observed_at=seen,
            stale=name in faults.stale,
            reachability=reachability,
        )

    def _reading(
        self,
        link: Link,
        near: Endpoint,
        forward: bool,
        now: datetime,
        faults: _Faults,
        hot: set[str],
    ) -> InterfaceState | None:
        """What one end of a link reports, or None if it is not polled.

        A link to a device that cannot be polled, or a cut circuit, reads as
        down. ``forward`` says ``near`` is the link's A end.
        """
        if near.device not in self.watched or near.device in faults.silent:
            return None
        seen = faults.stale.get(near.device, now)
        link_down = (
            link.id in faults.cut
            or link.a.device in faults.silent
            or link.b.device in faults.silent
        )
        in_pct, out_pct = 0.0, 0.0
        if not link_down:
            a_to_b, b_to_a = self._load(link, seen, link.id in hot)
            sent, received = (a_to_b, b_to_a) if forward else (b_to_a, a_to_b)
            # Both ends measure the same traffic, give or take a little.
            salt = (near.device, near.interface, int(seen.timestamp()))
            wobble = _unit("measure", *salt) - 0.5
            in_pct, out_pct = _pct(received + wobble), _pct(sent + wobble)
        return InterfaceState(
            device=near.device,
            interface=near.interface,
            oper="down" if link_down else "up",
            in_pct=in_pct,
            out_pct=out_pct,
            observed_at=seen,
            stale=near.device in faults.stale,
        )

    def _load(self, link: Link, at: datetime, hot: bool) -> tuple[float, float]:
        """Percent load each way: A to B, then B to A."""
        t = at.timestamp()
        site = self.sites[self.devices[link.a.device].site]
        local_hour = (t / 3600 + site.lon / 15) % 24
        daily = 0.6 + 0.4 * math.cos(2 * math.pi * (local_hour - 14) / 24)
        drift = 1 + 0.15 * math.sin(t / 600 + 6 * _unit("drift", link.id))
        level = 100 * _base(link) * daily * drift
        a_to_b = level * (0.8 + 0.4 * _unit("ab", link.id))
        b_to_a = level * (0.5 + 0.5 * _unit("ba", link.id))
        if hot:
            a_to_b = 92 + 7 * _unit("heat", link.id)
        return a_to_b, b_to_a

    def _peak(self, link: Link) -> float:
        """The most load a link can carry, leaving aside hot circuits."""
        spread = max(0.8 + 0.4 * _unit("ab", link.id), 0.5 + 0.5 * _unit("ba", link.id))
        return 100 * _base(link) * 1.15 * spread


def _base(link: Link) -> float:
    """A link's typical share of its capacity, before the daily cycle."""
    if link.kind == "wan":
        return 0.3 + 0.35 * _unit("base", link.id)
    return 0.08 + 0.35 * _unit("base", link.id)


def _band(pct: float) -> int:
    """0 below the high mark, 1 from it, 2 from the critical mark."""
    return 2 if pct >= CRITICAL_PCT else 1 if pct >= HIGH_PCT else 0


BAND_EVENT: dict[int, EventKind] = {0: "load-normal", 1: "busy", 2: "congested"}
