/**
 * The problems live state shows, ranked the way a NOC works through them.
 *
 * Devices that the core cannot reach are grouped into one outage per
 * connected group, so a branch that loses its circuits is one problem, not
 * one per device. The devices where reach stops are its edge: they are
 * reported down, or sit behind links that are. Monitoring cannot tell a dead
 * router from one behind a dead circuit, so the outage names both. Links down
 * between devices the core still reaches come next, then congestion, packet
 * loss, busy links, and devices without a recent reading.
 */
import type { Link } from './api/topology.ts';
import { failuresOf, impactOf, noFailures, reach, type Failures, type Impact } from './impact.ts';
import { CRITICAL_PCT, deviceHealth, HIGH_PCT, linkLive, type LiveIndex } from './live.ts';
import type { Selection } from './state.svelte.ts';
import {
	compareNatural,
	formatSpeed,
	linkName,
	shortInterface,
	siteOf,
	type TopologyIndex
} from './topology.ts';

export type ProblemKind = 'outage' | 'link-down' | 'congested' | 'loss' | 'busy' | 'nodata';

/** Kinds in the order they are worked through, with a heading for each. */
export const PROBLEM_KINDS: { kind: ProblemKind; label: string }[] = [
	{ kind: 'outage', label: 'Unreachable' },
	{ kind: 'link-down', label: 'Links down' },
	{ kind: 'congested', label: `Congested, ${CRITICAL_PCT}% or more` },
	{ kind: 'loss', label: 'Packet loss' },
	{ kind: 'busy', label: `Busy, ${HIGH_PCT}% or more` },
	{ kind: 'nodata', label: 'No recent data' }
];

export interface Problem {
	/** The same from one snapshot to the next while the problem lasts. */
	id: string;
	kind: ProblemKind;
	title: string;
	detail: string;
	/** What to select to look at it. */
	target: Selection;
	/** What it does to the network (outages and links down only). */
	impact: Impact | null;
	/** Devices it leaves unreachable, then devices it leaves without redundancy: problems of a kind rank by these. */
	lost: number;
	exposed: number;
}

/** Most names spelled out in a detail line. */
const NAMED = 3;

/**
 * What live state shows has failed: devices down, and links down.
 *
 * @param index - Topology index.
 * @param live - Live index.
 * @returns The failed devices and links.
 */
export function currentFailures(index: TopologyIndex, live: LiveIndex): Failures {
	const failures = noFailures();
	for (const d of index.topology.devices) {
		if (deviceHealth(live, d.name) === 'down') failures.devices.add(d.name);
	}
	for (const l of index.topology.links) {
		if (linkLive(live, l).health === 'down') failures.links.add(l.id);
	}
	return failures;
}

/**
 * Every current problem, most urgent first.
 *
 * @param index - Topology index.
 * @param live - Live index.
 * @returns Problems by kind, then by devices unreachable, devices without
 *   redundancy, and name.
 */
export function findProblems(index: TopologyIndex, live: LiveIndex): Problem[] {
	const failures = currentFailures(index, live);
	const { reached } = reach(index, failures);
	const healthy = reach(index, noFailures()).reached;
	const unreached = new Set([...healthy].filter((d) => !reached.has(d)));
	const problems = [
		...outages(index, live, unreached, reached),
		...linksDown(index, failures, reached),
		...loads(index, live),
		...deviceProblems(index, live, unreached)
	];
	const rank = (p: Problem) => PROBLEM_KINDS.findIndex((k) => k.kind === p.kind);
	return problems.sort(
		(x, y) =>
			rank(x) - rank(y) ||
			y.lost - x.lost ||
			y.exposed - x.exposed ||
			compareNatural(x.title, y.title)
	);
}

function outages(
	index: TopologyIndex,
	live: LiveIndex,
	unreached: Set<string>,
	reached: Set<string>
): Problem[] {
	const problems: Problem[] = [];
	const seen = new Set<string>();
	for (const start of [...unreached].sort(compareNatural)) {
		if (seen.has(start)) continue;
		// One outage per connected group of unreached devices.
		const group = new Set([start]);
		const boundary: Link[] = [];
		for (let frontier = [start]; frontier.length > 0;) {
			const next: string[] = [];
			for (const device of frontier) {
				for (const link of index.linksByDevice.get(device) ?? []) {
					const other = link.a.device === device ? link.b.device : link.a.device;
					if (reached.has(other)) boundary.push(link);
					else if (unreached.has(other) && !group.has(other)) {
						group.add(other);
						next.push(other);
					}
				}
			}
			frontier = next;
		}
		for (const d of group) seen.add(d);

		const edge = new Set(boundary.map((l) => (group.has(l.a.device) ? l.a.device : l.b.device)));
		const down = [...edge].filter((d) => deviceHealth(live, d) === 'down').sort(compareNatural);
		const lost = failuresOf(index, [{ kind: 'links', ids: boundary.map((l) => l.id) }]);
		for (const d of group) lost.devices.add(d);
		const { exposed } = impactOf(index, lost);
		const impact: Impact = {
			failed: { devices: new Set(down), links: new Set(boundary.map((l) => l.id)) },
			cutOff: new Set([...group].filter((d) => !down.includes(d))),
			exposed
		};
		const devices = [...group].sort(compareNatural);
		const sites = [...new Set(devices.map((d) => siteOf(index, d)))].sort(compareNatural);
		const whole = sites.every((s) =>
			(index.devicesBySite.get(s) ?? []).every((d) => group.has(d.name))
		);
		const circuits = boundary.flatMap((l) => (l.circuit ? [l.circuit.circuit_id] : []));
		const title =
			group.size === 1
				? `${start} ${down.length ? 'down' : 'unreachable'}`
				: whole
					? `${sites.join(', ')} cut off`
					: `${group.size} devices unreachable at ${sites.join(', ')}`;
		const where =
			group.size === 1
				? ''
				: circuits.length === boundary.length
					? `${plural(circuits.length, 'circuit')} ${names(circuits)} down`
					: `reach stops at ${names([...edge].sort(compareNatural))}`;
		problems.push({
			id: `outage:${devices[0]}`,
			kind: 'outage',
			title,
			detail: join(group.size > 1 ? plural(group.size, 'device') : '', where, exposure(exposed)),
			target:
				sites.length === 1 && whole
					? { kind: 'site', id: sites[0] ?? '' }
					: { kind: 'device', id: devices[0] ?? '' },
			impact,
			lost: group.size,
			exposed: exposed.size
		});
	}
	return problems;
}

function linksDown(index: TopologyIndex, failures: Failures, reached: Set<string>): Problem[] {
	return [...failures.links].flatMap((id): Problem[] => {
		const link = index.links.get(id);
		if (!link || !reached.has(link.a.device) || !reached.has(link.b.device)) return [];
		const impact = impactOf(index, failuresOf(index, [{ kind: 'links', ids: [id] }]));
		return [
			{
				id: `down:${id}`,
				kind: 'link-down',
				title: `${linkName(link)} down`,
				detail: join(ends(link), exposure(impact.exposed) || 'redundancy holds'),
				target: { kind: 'links', ids: [id] },
				impact,
				lost: 0,
				exposed: impact.exposed.size
			}
		];
	});
}

function loads(index: TopologyIndex, live: LiveIndex): Problem[] {
	return index.topology.links.flatMap((link): Problem[] => {
		const state = linkLive(live, link);
		if (state.health !== 'ok' || state.utilPct === null || state.utilPct < HIGH_PCT) return [];
		const forward = (state.aToB ?? 0) >= (state.bToA ?? 0);
		const [from, to] = forward ? [link.a, link.b] : [link.b, link.a];
		return [
			{
				id: `load:${link.id}`,
				kind: state.utilPct >= CRITICAL_PCT ? 'congested' : 'busy',
				title: `${linkName(link)} at ${Math.round(state.utilPct)}%`,
				detail: join(
					`${from.device} ${shortInterface(from.interface)} → ${to.device}`,
					`${formatSpeed(link.speed_mbps)} link`
				),
				target: { kind: 'links', ids: [link.id] },
				impact: null,
				lost: 0,
				exposed: 0
			}
		];
	});
}

function deviceProblems(index: TopologyIndex, live: LiveIndex, unreached: Set<string>): Problem[] {
	const at = Date.parse(live.state.generated_at);
	return index.topology.devices.flatMap((device): Problem[] => {
		if (unreached.has(device.name)) return [];
		const health = deviceHealth(live, device.name);
		const record = live.devices.get(device.name);
		if (!record || (health !== 'degraded' && health !== 'nodata')) return [];
		const target: Selection = { kind: 'device', id: device.name };
		if (health === 'nodata') {
			const minutes = Math.round((at - Date.parse(record.observed_at)) / 60_000);
			return [
				{
					id: `nodata:${device.name}`,
					kind: 'nodata',
					title: device.name,
					detail: `last reading ${minutes} min before this snapshot`,
					target,
					impact: null,
					lost: 0,
					exposed: 0
				}
			];
		}
		const loss = record.reachability
			.filter((r) => (r.loss_pct ?? 0) > 0)
			.map((r) => `${r.loss_pct}% from ${r.position}`);
		return [
			{
				id: `loss:${device.name}`,
				kind: 'loss',
				title: device.name,
				detail: join(...loss),
				target,
				impact: null,
				lost: 0,
				exposed: 0
			}
		];
	});
}

function ends(link: Link): string {
	const end = (e: Link['a']) => `${e.device} ${shortInterface(e.interface)}`;
	return `${end(link.a)} ↔ ${end(link.b)}`;
}

/** "N devices left without redundancy", or nothing when there are none. */
function exposure(exposed: Map<string, string[]>): string {
	if (exposed.size === 0) return '';
	return `${plural(exposed.size, 'device')} left without redundancy`;
}

function names(list: string[]): string {
	const shown = list.slice(0, NAMED).join(', ');
	return list.length > NAMED ? `${shown} and ${list.length - NAMED} more` : shown;
}

function plural(n: number, noun: string): string {
	return `${n} ${noun}${n === 1 ? '' : 's'}`;
}

function join(...parts: string[]): string {
	return parts.filter(Boolean).join(' · ');
}
