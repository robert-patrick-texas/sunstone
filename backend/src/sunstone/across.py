"""Failures across the layers: what they do to each named network they
reach, and the risks a network's tunnels share beneath it.

Impact (``impact.py``) stays physical: which devices a failure cuts off
from the core, and which it leaves on one device. Here a failure is
followed up through the named networks instead. The tunnels riding what
failed go down unless they find another way, as the simulator works them
out, and every network's status is worked out again from that, by the
rules live status follows. A switch taking two of a site's four Internet
circuits degrades black there, and blue, riding black over the other two,
stays up with a caveat.

Tunnels look like independent paths in their own network, but two of them
can ride one circuit, one switch, or one provider's circuits. A network's
shared risks are the devices and links beneath it, other than its own, and
the providers of the circuits beneath it, that would each take two or more
of its tunnels down at once on their own, with the sites of it they would
cut off. They are worked out on the network as documented with
everything up, and, with live state, on top of what is down at a moment:
a circuit down at a site can leave the one beside it carrying two
tunnels alone.

Each outage and link down in live state says what fixing it would bring
back to each network: everything down now is compared with everything
down but it, so two circuits down at one site each bring the site back.

What a "what if" compares with, every network's status before the
failures, is worked out once for the healthy network and once for each
live moment asked about, and kept: it is the same for every failure asked
about there, and most of the work. What fixing a problem brings back, and
the risks at a moment, are kept for as long as the same things are down.
"""

import threading
from collections import OrderedDict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from sunstone.impact import Failures, Impact, Network, WhatIf
from sunstone.layouts import DeviceCenter, LinksCenter, SiteCenter
from sunstone.live import TunnelState
from sunstone.model import device_ends
from sunstone.problems import Problem
from sunstone.status import NetworkStatus, ResourceStatus, Status, Statuses

# Most shared risks listed for one network.
MAX_RISKS = 40
# Moments kept with what a "what if" there compares with, as the monitor
# keeps moments; and answers kept for sets of things down.
KEPT_MOMENTS = 16
KEPT_ANSWERS = 256

RiskKind = Literal["device", "link", "provider"]


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class NetworkImpact(_Record):
    """What some failures do to the whole network, or to one named network."""

    network: str | None
    """The named network, or None for the whole."""
    before: Status
    after: NetworkStatus
    """Its status with the failures, with why."""
    tunnels: int
    """How many tunnels it has, those built on demand now included."""
    tunnels_lost: list[str]
    """Its tunnels up before and down with the failures."""
    links_lost: list[str]
    """Its links working before and failed, or ending at a device that
    failed, with the failures; none for the whole."""
    sites_lost: list[str]
    """Its sites reached before, and not with the failures."""


class ResourceImpact(_Record):
    """What some failures do to one resource."""

    name: str
    before: Status
    after: ResourceStatus
    """Its status with the failures, with why."""


class LayeredWhatIf(WhatIf):
    """What failing some items would do, physically and to each network."""

    networks: list[NetworkImpact]
    """The whole and each named network the failures change, bottom up."""
    resources: list[ResourceImpact] = []
    """Each resource whose status or reasons the failures change."""


class RiskItem(_Record):
    """A device, a link, or a provider's circuits, failing alone."""

    kind: RiskKind
    id: str
    """A device's name, a link's id, or a provider's name."""


class Risk(_Record):
    """Tunnels of one network that are not independent paths: any one of
    some items failing alone takes them all down."""

    items: list[RiskItem]
    """Providers first, then devices, then links."""
    tunnels: list[str]
    """The network's tunnels each item would take down."""
    sites: list[str]
    """The network's sites each item would cut off from it."""
    new: bool = False
    """A risk only with what is down now: on the network as documented,
    none of its items takes two of the network's tunnels. Items new and old
    with the same consequence are two risks, so the new ones stand out."""


class NetworkRisks(_Record):
    """One named network's shared risks, worst first."""

    network: str
    tunnels: int
    """How many tunnels it has, apart from those built on demand."""
    risks: list[Risk]
    more: int
    """Risks left out of the list."""


class RiskReport(_Record):
    """Every named network with tunnels, and its shared risks."""

    at: datetime | None = None
    """The moment they are worked out on top of, or None for the network as
    documented."""

    networks: list[NetworkRisks]


class ProviderTarget(_Record):
    """Every circuit from one provider, failing together."""

    kind: Literal["provider"]
    id: str


Failing = Annotated[
    DeviceCenter | SiteCenter | LinksCenter | ProviderTarget,
    Field(discriminator="kind"),
]


@dataclass(frozen=True)
class Before:
    """What is down already: devices and links, and every tunnel the source
    reports, those built spoke to spoke among them."""

    failures: Failures
    tunnels: tuple[TunnelState, ...]


@dataclass(frozen=True)
class _State:
    """Some failures, which tunnels are up with them, and each named
    network's status, with the whole network's when it was asked for."""

    failures: Failures
    up: dict[str, bool]
    whole: NetworkStatus | None
    networks: list[NetworkStatus]
    resources: list[ResourceStatus]


class Across:
    """Follows failures through the named networks of one topology."""

    def __init__(self, network: Network, statuses: Statuses) -> None:
        """Index a topology's networks for "what if" questions.

        Args:
            network: The topology, indexed for impact.
            statuses: Its status rules, indexed.

        Raises:
            None
        """
        self.network = network
        self.statuses = statuses
        self.layers = statuses.layers
        self.network_of = dict(self.layers.all_tunnels())
        # By the moment they are for; None for the healthy network.
        self._baselines: OrderedDict[datetime | None, _State] = OrderedDict()
        # On the network as documented, with every item that is a risk; and
        # on top of what is down, by what is.
        self._documented: (
            tuple[RiskReport, dict[str, set[tuple[RiskKind, str]]]] | None
        ) = None
        self._risks: OrderedDict[tuple, RiskReport] = OrderedDict()
        self._fixed: OrderedDict[tuple, list[NetworkImpact]] = OrderedDict()
        self._lock = threading.Lock()

    def providers(self) -> dict[str, list[str]]:
        """Each provider's circuits.

        Returns:
            Provider name to the ids of its links, in topology order.
        """
        found: dict[str, list[str]] = {}
        for link in self.network.topology.links:
            if link.circuit:
                found.setdefault(link.circuit.provider, []).append(link.id)
        return found

    def failures_of(self, targets: Iterable[Failing]) -> Failures:
        """The devices and links some items to fail stand for.

        Args:
            targets: Devices, sites (all their devices), links, and
                providers (all their circuits).

        Returns:
            Everything they include.

        Raises:
            None
        """
        providers = self.providers()
        found = Failures()
        for t in targets:
            if isinstance(t, ProviderTarget):
                found |= Failures(links=frozenset(providers.get(t.id, [])))
            else:
                found |= self.network.failures_of([t])
        return found

    def what_if(
        self, failures: Failures, before: Before | None, at: datetime | None = None
    ) -> LayeredWhatIf:
        """What failing some devices and links would do, physically and to
        every network they reach.

        Args:
            failures: The failures to suppose.
            before: What is down already, or None for the healthy network.
            at: The moment ``before`` is from. A moment always has the same
                ``before``, so what it compares with is kept by moment.

        Returns:
            The physical impact, whether everything named was gone
            already, and each network the failures change.

        Raises:
            None
        """
        was = before.failures if before else Failures()
        physical = self.network.what_if(failures, was if before else None)
        reported = before.tunnels if before else ()
        failing = {t.tunnel for t in reported if t.status == "down"}
        built = {t.tunnel for t in reported if t.dynamic and t.status == "up"}
        dynamic = {t.tunnel: t.network for t in reported if t.dynamic}
        when = at or datetime.now(UTC)
        # Without a moment, a before cannot be told from another one.
        kept = before is None or at is not None
        key = at if before else None
        with self._lock:
            base = self._baselines.get(key) if kept else None
            if base is not None:
                self._baselines.move_to_end(key)
        if base is None:
            base = self._state(when, was, failing, built, dynamic)
            if kept:
                with self._lock:
                    _keep(self._baselines, key, base, KEPT_MOMENTS)
        after = self._state(when, was | failures, failing, built, dynamic)
        networks = self._compare(base, after, dynamic)
        resources = [
            ResourceImpact(name=a.name, before=b.status, after=a)
            for b, a in zip(base.resources, after.resources, strict=True)
            if (b.status, b.reasons) != (a.status, a.reasons)
        ]
        return LayeredWhatIf(**dict(physical), networks=networks, resources=resources)

    def fixing(
        self,
        at: datetime,
        failures: Failures,
        tunnels: Iterable[TunnelState],
        problems: Iterable[Problem],
    ) -> dict[str, list[NetworkImpact]]:
        """What fixing each outage and link down would bring back, with
        everything else still down.

        Args:
            at: The moment.
            failures: Everything down at it.
            tunnels: The tunnels' states it reports.
            problems: Its problems; those with an impact are answered.

        Returns:
            By problem id, each named network that fixing it would give
            something back to, or change the status of, bottom up:
            ``before`` is with it fixed, ``after`` as things are. The whole
            network's part is the problem's physical impact.

        Raises:
            None
        """
        reported = tuple(tunnels)
        built = {t.tunnel for t in reported if t.dynamic and t.status == "up"}
        dynamic = {t.tunnel: t.network for t in reported if t.dynamic}
        # A tunnel down while everything it rides works fails of its own
        # accord, and stays down whatever problem is fixed.
        rides = self.layers.tunnels_up(
            set(failures.devices), set(failures.links), (), built
        )
        failing = {
            t.tunnel for t in reported if t.status == "down" and rides.get(t.tunnel)
        }
        common = (failures, frozenset(failing), frozenset(built))
        targets: dict[str, Failures] = {}
        for p in problems:
            if p.impact is not None:
                ours = self._fixes(p.kind == "outage", p.impact, failures)
                if ours.devices or ours.links:
                    targets[p.id] = ours
        found: dict[str, list[NetworkImpact]] = {}
        with self._lock:
            for pid, ours in targets.items():
                if (common, ours) in self._fixed:
                    found[pid] = self._fixed[(common, ours)]
                    self._fixed.move_to_end((common, ours))
        todo = {pid: ours for pid, ours in targets.items() if pid not in found}
        if not todo:
            return found
        # Their physical impact is the whole network's part, so only the
        # named networks are worked out: on a large network, the whole
        # network's status is most of the work.
        now = self._state(at, failures, failing, built, dynamic, whole=False)
        for pid, ours in todo.items():
            fixed = Failures(
                failures.devices - ours.devices, failures.links - ours.links
            )
            compared = self._compare(
                self._state(at, fixed, failing, built, dynamic, whole=False),
                now,
                dynamic,
            )
            # A network whose reasons alone differ, with nothing lost and
            # its status the same, is told about by what it rides.
            answer = [
                n
                for n in compared
                if n.tunnels_lost
                or n.links_lost
                or n.sites_lost
                or n.before != n.after.status
            ]
            found[pid] = answer
            with self._lock:
                _keep(self._fixed, (common, ours), answer, KEPT_ANSWERS)
        return found

    def _fixes(self, outage: bool, impact: Impact, failures: Failures) -> Failures:
        """What fixing a problem would bring back: a link down, or an
        outage's devices down and every link down at it or inside it."""
        if not outage:
            return Failures(links=frozenset(impact.failed.links) & failures.links)
        group = set(impact.failed.devices) | set(impact.cut_off)
        edge = set(impact.failed.links)
        links = self.network.links
        return Failures(
            frozenset(group) & failures.devices,
            frozenset(
                i
                for i in failures.links
                if i in edge or any(e.device in group for e in device_ends(links[i]))
            ),
        )

    def _state(
        self,
        at: datetime,
        failures: Failures,
        failing: set[str],
        built: set[str],
        dynamic: dict[str, str],
        *,
        whole: bool = True,
    ) -> _State:
        """The tunnels up and each network's status with some failures."""
        up = self.layers.tunnels_up(
            set(failures.devices), set(failures.links), failing, built
        )
        tunnels = [
            TunnelState(
                tunnel=t,
                network=self.network_of.get(t) or dynamic[t],
                status="up" if ok else "down",
                dynamic=t in dynamic,
            )
            for t, ok in up.items()
            if t in self.network_of or t in dynamic
        ]
        down, cut = set(failures.devices), set(failures.links)
        if whole:
            report = self.statuses.of(at, down, cut, tunnels)
            return _State(failures, up, report.whole, report.networks, report.resources)
        return _State(failures, up, None, self.statuses.named(down, cut, tunnels), [])

    def _compare(
        self, before: _State, after: _State, dynamic: dict[str, str]
    ) -> list[NetworkImpact]:
        """The whole network, when both states have it, and each named
        network that differ from one state to another, with what they lose."""
        lost = {t for t, ok in before.up.items() if ok and not after.up.get(t, False)}
        networks = []
        pairs = [(before.whole, after.whole)] if before.whole and after.whole else []
        pairs += list(zip(before.networks, after.networks, strict=True))
        for b, a in pairs:
            name = a.network
            mine = [
                t
                for t in before.up
                if (self.network_of.get(t) or dynamic.get(t)) == name
            ]
            changed = NetworkImpact(
                network=name,
                before=b.status,
                after=a,
                tunnels=len(mine) if name else 0,
                tunnels_lost=sorted(t for t in mine if t in lost) if name else [],
                links_lost=self._links_lost(name, before.failures, after.failures)
                if name
                else [],
                sites_lost=sorted(_offline_sites(a) - _offline_sites(b)),
            )
            if (
                changed.tunnels_lost
                or changed.links_lost
                or changed.sites_lost
                or (b.status, b.reasons, b.caveats, b.groups)
                != (a.status, a.reasons, a.caveats, a.groups)
            ):
                networks.append(changed)
        return networks

    def _links_lost(self, name: str, was: Failures, now: Failures) -> list[str]:
        """A network's links working before and lost with the failures."""

        def gone(f: Failures, link_id: str, ends: Iterable[str]) -> bool:
            return link_id in f.links or any(d in f.devices for d in ends)

        found = []
        for link in self.layers.slices[name].links:
            ends = [e.device for e in device_ends(link)]
            if gone(now, link.id, ends) and not gone(was, link.id, ends):
                found.append(link.id)
        return sorted(found)

    def risks(
        self, failures: Failures | None = None, tunnels: Iterable[TunnelState] = ()
    ) -> RiskReport:
        """Every named network's shared risks, on the network as documented
        or on top of what is down at a moment.

        Args:
            failures: What is down, or None for the network as documented.
            tunnels: The tunnels' states at that moment.

        Returns:
            Each network with tunnels, bottom up, with the devices, links,
            and providers beneath it that would take two or more of its
            tunnels at once: those cutting off most of its sites first,
            then those taking most of its tunnels. On top of what is down,
            only what is still up counts, and a risk only with it is new
            and comes first.

        Raises:
            None
        """
        with self._lock:
            documented = self._documented
        if documented is None:
            documented = self._work_out_risks(Failures(), set(), set(), None)
            with self._lock:
                self._documented = documented
        if failures is None:
            return documented[0]
        reported = tuple(tunnels)
        failing = frozenset(t.tunnel for t in reported if t.status == "down")
        built = frozenset(t.tunnel for t in reported if t.dynamic and t.status == "up")
        key = (failures, failing, built)
        with self._lock:
            found = self._risks.get(key)
        if found is None:
            found = self._work_out_risks(
                failures, set(failing), set(built), documented[1]
            )[0]
            with self._lock:
                _keep(self._risks, key, found, KEPT_MOMENTS)
        return found

    def _work_out_risks(
        self,
        was: Failures,
        failing: set[str],
        built: set[str],
        documented: dict[str, set[tuple[RiskKind, str]]] | None,
    ) -> tuple[RiskReport, dict[str, set[tuple[RiskKind, str]]]]:
        """Fail each candidate still up alone on top of what is down, and
        keep those taking two or more tunnels up of a network they are
        beneath; with every item that is a risk, by network."""
        layers = self.layers
        providers = self.providers()
        tunnels = layers.all_tunnels()
        down_now, cut_now = set(was.devices), set(was.links)
        # What each candidate stands for, and which networks it is beneath.
        candidates: dict[tuple[RiskKind, str], Failures] = {}
        beneath: dict[str, set[tuple[RiskKind, str]]] = {}
        own: dict[str, list[str]] = {}
        for name in layers.order:
            own[name] = [t for t, n in tunnels if n == name]
            if len(own[name]) < 2:
                continue
            # Its tunnels' own ends take them down in plain sight.
            mine = {d for e in layers.tunnel_edges(name) for d in (e.a, e.b)}
            found: set[tuple[RiskKind, str]] = set()
            for under in layers.beneath([name]):
                s = layers.slices[under]
                for d in s.devices - mine - down_now:
                    found.add(("device", d))
                    candidates[("device", d)] = Failures(devices=frozenset([d]))
                for link in s.links:
                    if link.id in cut_now:
                        continue
                    found.add(("link", link.id))
                    candidates[("link", link.id)] = Failures(links=frozenset([link.id]))
                    if link.circuit:
                        p = link.circuit.provider
                        found.add(("provider", p))
                        candidates[("provider", p)] = Failures(
                            links=frozenset(providers[p])
                        )
            beneath[name] = found
        up_now = layers.tunnels_up(down_now, cut_now, failing, built)
        gone_now = {t for t, ok in up_now.items() if not ok}
        reached_now = {
            n: self.statuses.reached(n, down_now, cut_now | gone_now) for n in beneath
        }
        # Items with the same consequence for a network are one risk, and
        # those that are risks only with what is down now another.
        rank = {"provider": 0, "device": 1, "link": 2}
        Key = tuple[RiskKind, str]
        Consequence = tuple[tuple[str, ...], tuple[str, ...], bool]
        found_risks: dict[str, dict[Consequence, list[Key]]] = {n: {} for n in beneath}
        for key, failed in sorted(
            candidates.items(), key=lambda c: (rank[c[0][0]], c[0][1])
        ):
            down, cut = down_now | failed.devices, cut_now | failed.links
            up = layers.tunnels_up(down, cut, failing, built)
            for name, found in beneath.items():
                if key not in found:
                    continue
                lost = tuple(t for t in own[name] if up_now.get(t) and not up[t])
                if len(lost) < 2:
                    continue
                reached = self.statuses.reached(name, down, cut | gone_now | set(lost))
                sites = tuple(sorted(reached_now[name] - reached))
                new = documented is not None and key not in documented.get(name, set())
                found_risks[name].setdefault((lost, sites, new), []).append(key)
        networks = []
        for name in beneath:
            ranked = sorted(
                (
                    Risk(
                        items=[RiskItem(kind=k, id=i) for k, i in keys],
                        tunnels=list(lost),
                        sites=list(sites),
                        new=new,
                    )
                    for (lost, sites, new), keys in found_risks[name].items()
                ),
                key=lambda r: (not r.new, -len(r.sites), -len(r.tunnels), r.tunnels),
            )
            networks.append(
                NetworkRisks(
                    network=name,
                    tunnels=len(own[name]),
                    risks=ranked[:MAX_RISKS],
                    more=max(0, len(ranked) - MAX_RISKS),
                )
            )
        items = {
            name: {k for keys in found_risks[name].values() for k in keys}
            for name in beneath
        }
        return RiskReport(networks=networks), items


def _keep(kept: OrderedDict, key: object, value: object, most: int) -> None:
    """Keep an answer, dropping the oldest beyond ``most``."""
    kept[key] = value
    kept.move_to_end(key)
    while len(kept) > most:
        kept.popitem(last=False)


def _offline_sites(status: NetworkStatus) -> set[str]:
    return {g.id for g in status.groups if g.kind == "site" and g.status == "offline"}
