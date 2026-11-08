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
cut off. They are worked out once, on the network as documented with
everything up.

What a "what if" compares with, every network's status before the
failures, is worked out once for the healthy network and once for each
live moment asked about, and kept: it is the same for every failure asked
about there, and most of the work.
"""

import threading
from collections import OrderedDict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from sunstone.impact import Failures, Network, WhatIf
from sunstone.layouts import DeviceCenter, LinksCenter, SiteCenter
from sunstone.live import TunnelState
from sunstone.model import device_ends
from sunstone.monitor import KEPT_MOMENTS
from sunstone.status import NetworkStatus, Status, Statuses, StatusReport

# Most shared risks listed for one network.
MAX_RISKS = 40

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


class LayeredWhatIf(WhatIf):
    """What failing some items would do, physically and to each network."""

    networks: list[NetworkImpact]
    """The whole and each named network the failures change, bottom up."""


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
class _Baseline:
    """What failures are compared with: which tunnels are up, and every
    network's status."""

    up: dict[str, bool]
    report: StatusReport


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
        self._risks: RiskReport | None = None
        # By the moment they are for; None for the healthy network.
        self._baselines: OrderedDict[datetime | None, _Baseline] = OrderedDict()
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
        now = was | failures
        when = at or datetime.now(UTC)
        # Without a moment, a before cannot be told from another one.
        kept = before is None or at is not None
        key = at if before else None
        with self._lock:
            base = self._baselines.get(key) if kept else None
            if base is not None:
                self._baselines.move_to_end(key)
        if base is None:
            up = self.layers.tunnels_up(
                set(was.devices), set(was.links), failing, built
            )
            base = _Baseline(up, self._report(when, was, up, dynamic))
            if kept:
                with self._lock:
                    self._baselines[key] = base
                    while len(self._baselines) > KEPT_MOMENTS:
                        self._baselines.popitem(last=False)
        up_before, report_before = base.up, base.report
        up_after = self.layers.tunnels_up(
            set(now.devices), set(now.links), failing, built
        )
        report_after = self._report(when, now, up_after, dynamic)
        lost = {t for t, ok in up_before.items() if ok and not up_after.get(t, False)}
        networks = []
        pairs = [(report_before.whole, report_after.whole)] + list(
            zip(report_before.networks, report_after.networks, strict=True)
        )
        for b, a in pairs:
            name = a.network
            mine = [
                t
                for t in up_before
                if (self.network_of.get(t) or dynamic.get(t)) == name
            ]
            changed = NetworkImpact(
                network=name,
                before=b.status,
                after=a,
                tunnels=len(mine) if name else 0,
                tunnels_lost=sorted(t for t in mine if t in lost) if name else [],
                links_lost=self._links_lost(name, was, now) if name else [],
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
        return LayeredWhatIf(**dict(physical), networks=networks)

    def _report(
        self,
        at: datetime,
        failures: Failures,
        up: dict[str, bool],
        dynamic: dict[str, str],
    ) -> StatusReport:
        """Every network's status with some failures and tunnel states."""
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
        return self.statuses.of(at, set(failures.devices), set(failures.links), tunnels)

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

    def risks(self) -> RiskReport:
        """Every named network's shared risks, worked out once.

        Returns:
            Each network with tunnels, bottom up, with the devices, links,
            and providers beneath it that would take two or more of its
            tunnels at once: those cutting off most of its sites first,
            then those taking most of its tunnels.

        Raises:
            None
        """
        if self._risks is None:
            self._risks = self._work_out_risks()
        return self._risks

    def _work_out_risks(self) -> RiskReport:
        """Fail each candidate alone on the healthy network, and keep those
        taking two or more tunnels of a network they are beneath."""
        layers = self.layers
        providers = self.providers()
        tunnels = layers.all_tunnels()
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
                for d in s.devices - mine:
                    found.add(("device", d))
                    candidates[("device", d)] = Failures(devices=frozenset([d]))
                for link in s.links:
                    found.add(("link", link.id))
                    candidates[("link", link.id)] = Failures(links=frozenset([link.id]))
                    if link.circuit:
                        p = link.circuit.provider
                        found.add(("provider", p))
                        candidates[("provider", p)] = Failures(
                            links=frozenset(providers[p])
                        )
            beneath[name] = found
        healthy = {n: self.statuses.reached(n, set(), set()) for n in beneath}
        # Items with the same consequence for a network are one risk.
        rank = {"provider": 0, "device": 1, "link": 2}
        Key = tuple[RiskKind, str]
        found_risks: dict[str, dict[tuple[tuple[str, ...], tuple[str, ...]], list[Key]]]
        found_risks = {n: {} for n in beneath}
        for key, failed in sorted(
            candidates.items(), key=lambda c: (rank[c[0][0]], c[0][1])
        ):
            down, cut = set(failed.devices), set(failed.links)
            up = layers.tunnels_up(down, cut)
            for name, found in beneath.items():
                if key not in found:
                    continue
                lost = tuple(t for t in own[name] if not up[t])
                if len(lost) < 2:
                    continue
                reached = self.statuses.reached(name, down, cut | set(lost))
                sites = tuple(sorted(healthy[name] - reached))
                found_risks[name].setdefault((lost, sites), []).append(key)
        networks = []
        for name in beneath:
            ranked = sorted(
                (
                    Risk(
                        items=[RiskItem(kind=k, id=i) for k, i in keys],
                        tunnels=list(lost),
                        sites=list(sites),
                    )
                    for (lost, sites), keys in found_risks[name].items()
                ),
                key=lambda r: (-len(r.sites), -len(r.tunnels), r.tunnels),
            )
            networks.append(
                NetworkRisks(
                    network=name,
                    tunnels=len(own[name]),
                    risks=ranked[:MAX_RISKS],
                    more=max(0, len(ranked) - MAX_RISKS),
                )
            )
        return RiskReport(networks=networks)


def _offline_sites(status: NetworkStatus) -> set[str]:
    return {g.id for g in status.groups if g.kind == "site" and g.status == "offline"}
