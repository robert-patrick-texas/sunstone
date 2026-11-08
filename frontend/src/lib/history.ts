/**
 * The last day of live state: events to list and mark on the timeline, and
 * a link's load over time from the history of one of its devices.
 *
 * Sources report history in 5-minute steps, and events at step boundaries.
 * When several devices at one site change the same way at the same step (a
 * branch losing its circuits takes every device there down at once), they
 * are listed as one row.
 *
 * Each row keeps what changed, so the list can follow the networks chosen
 * and a region: see {@link rowSites}.
 */
import type { DeviceHistory, StateEvent } from './api/state.ts';
import type { Link } from './api/topology.ts';
import type { AnySelection } from './state.svelte.ts';
import { deviceEnds, isDeviceEnd, linkName, siteOf, type TopologyIndex } from './topology.ts';

export const STEP_MS = 5 * 60_000;
/** Devices at one site changing together at one step are one row from this many. */
const GROUP_FROM = 3;

export type EventKind = StateEvent['kind'];
export type EventCategory = 'devices' | 'links' | 'tunnels' | 'load' | 'loss' | 'nodata';
type Severity = 'critical' | 'warning' | 'minor' | 'resolved';

export const EVENT_CATEGORIES: { category: EventCategory; label: string }[] = [
	{ category: 'devices', label: 'Down and up' },
	{ category: 'links', label: 'Links' },
	{ category: 'tunnels', label: 'Tunnels' },
	{ category: 'load', label: 'Load' },
	{ category: 'loss', label: 'Packet loss' },
	{ category: 'nodata', label: 'No data' }
];

const CATEGORY: Record<EventKind, EventCategory> = {
	down: 'devices',
	up: 'devices',
	'link-down': 'links',
	'link-up': 'links',
	'tunnel-down': 'tunnels',
	'tunnel-up': 'tunnels',
	busy: 'load',
	congested: 'load',
	'load-normal': 'load',
	loss: 'loss',
	'loss-cleared': 'loss',
	nodata: 'nodata',
	reporting: 'nodata'
};

const SEVERITY: Record<EventKind, Severity> = {
	down: 'critical',
	'link-down': 'critical',
	'tunnel-down': 'critical',
	congested: 'critical',
	busy: 'warning',
	loss: 'warning',
	nodata: 'minor',
	up: 'resolved',
	'link-up': 'resolved',
	'tunnel-up': 'resolved',
	'load-normal': 'resolved',
	'loss-cleared': 'resolved',
	reporting: 'resolved'
};

/** One row of the event list: an event, or several like it at one site. */
export interface EventRow {
	at: string;
	kind: EventKind;
	title: string;
	/** What to select to look at it. */
	target: AnySelection;
	count: number;
	/** Maintenance open at the time accounts for it. */
	planned: boolean;
	/** What changed: the devices, links, or tunnel (by name, or `FABRIC:a~b`). */
	devices: string[];
	links: string[];
	tunnels: string[];
}

/**
 * Turn events into rows, newest first, grouping devices at one site that
 * change the same way at the same step.
 *
 * @param index - Topology index.
 * @param events - Events, oldest first, as the API returns them.
 * @param shown - Categories to keep.
 * @returns The rows.
 */
export function eventRows(
	index: TopologyIndex,
	events: StateEvent[],
	shown: Set<EventCategory>
): EventRow[] {
	const rows: EventRow[] = [];
	const groups = new Map<
		string,
		{ at: string; kind: EventKind; site: string; planned: boolean; devices: string[] }
	>();
	for (const e of events) {
		if (!shown.has(CATEGORY[e.kind])) continue;
		if (e.device) {
			const site = siteOf(index, e.device);
			const key = [e.at, e.kind, site, e.planned].join(' ');
			const group = groups.get(key) ?? {
				at: e.at,
				kind: e.kind,
				site,
				planned: e.planned,
				devices: []
			};
			group.devices.push(e.device);
			groups.set(key, group);
			continue;
		}
		if (e.tunnel) {
			rows.push({
				at: e.at,
				kind: e.kind,
				title: `${tunnelName(e.tunnel)} ${e.kind === 'tunnel-down' ? 'down' : 'back up'}`,
				target: tunnelTarget(index, e.tunnel),
				count: 1,
				planned: e.planned,
				devices: [],
				links: [],
				tunnels: [e.tunnel]
			});
			continue;
		}
		const link = e.link ? index.links.get(e.link) : undefined;
		if (!link) continue;
		rows.push({
			at: e.at,
			kind: e.kind,
			title: linkTitle(link, e),
			target: { kind: 'links', ids: [link.id] },
			count: 1,
			planned: e.planned,
			devices: [],
			links: [link.id],
			tunnels: []
		});
	}
	for (const { at, kind, site, planned, devices } of groups.values()) {
		if (devices.length >= GROUP_FROM) {
			rows.push({
				at,
				kind,
				title: `${site}: ${devices.length} ${GROUP_TEXT[kind]}`,
				target: { kind: 'site', id: site },
				count: devices.length,
				planned,
				devices,
				links: [],
				tunnels: []
			});
		} else {
			for (const device of devices) {
				rows.push({
					at,
					kind,
					title: `${device} ${DEVICE_TEXT[kind]}`,
					target: { kind: 'device', id: device },
					count: 1,
					planned,
					devices: [device],
					links: [],
					tunnels: []
				});
			}
		}
	}
	// Newest first; at one step, the most severe first.
	const order = (r: EventRow) => SEVERITY_ORDER.indexOf(SEVERITY[r.kind]);
	return rows.sort(
		(x, y) => y.at.localeCompare(x.at) || order(x) - order(y) || x.title.localeCompare(y.title)
	);
}

const SEVERITY_ORDER: Severity[] = ['critical', 'warning', 'minor', 'resolved'];

const DEVICE_TEXT: Partial<Record<EventKind, string>> = {
	down: 'down',
	up: 'back up',
	loss: 'dropping packets',
	'loss-cleared': 'no longer dropping packets',
	nodata: 'stopped reporting',
	reporting: 'reporting again'
};

const GROUP_TEXT: Partial<Record<EventKind, string>> = {
	down: 'devices down',
	up: 'devices back up',
	loss: 'devices dropping packets',
	'loss-cleared': 'devices no longer dropping packets',
	nodata: 'devices stopped reporting',
	reporting: 'devices reporting again'
};

/**
 * A tunnel as people say it.
 *
 * @param tunnel - A tunnel's name, or `FABRIC:a~b` for one a fabric is made of.
 * @returns The name, or for a fabric's, the fabric and its two ends.
 */
export function tunnelName(tunnel: string): string {
	const colon = tunnel.indexOf(':');
	if (colon < 0) return tunnel;
	const [a, b] = tunnel.slice(colon + 1).split('~');
	return `${tunnel.slice(0, colon)}: ${a} – ${b}`;
}

/**
 * What to select for a tunnel: itself, or the fabric it is part of.
 *
 * @param index - Topology index.
 * @param tunnel - A tunnel's name, or `FABRIC:a~b`.
 * @returns The selection.
 */
export function tunnelTarget(index: TopologyIndex, tunnel: string): AnySelection {
	if (index.tunnels.has(tunnel)) return { kind: 'tunnel', id: tunnel };
	return { kind: 'fabric', id: tunnel.slice(0, tunnel.indexOf(':')) };
}

/**
 * The sites a row of the event list touches, for keeping a region's rows.
 *
 * @param index - Topology index.
 * @param row - The row.
 * @returns The sites of its devices, of its links' device ends, and of its
 *   tunnel's device ends.
 */
export function rowSites(index: TopologyIndex, row: EventRow): Set<string> {
	const devices = [...row.devices];
	for (const id of row.links) {
		const link = index.links.get(id);
		if (link) devices.push(...deviceEnds(link).map((e) => e.device));
	}
	for (const id of row.tunnels) {
		const tunnel = index.tunnels.get(id);
		if (!tunnel) devices.push(...id.slice(id.indexOf(':') + 1).split('~'));
		else devices.push(tunnel.a.device, ...('device' in tunnel.b ? [tunnel.b.device] : []));
	}
	return new Set(devices.map((d) => siteOf(index, d)).filter((s) => s !== ''));
}

function linkTitle(link: Link, e: StateEvent): string {
	const name = linkName(link);
	const pct = Math.round(e.pct ?? 0);
	switch (e.kind) {
		case 'link-down':
			return `${name} down`;
		case 'link-up':
			return `${name} back up`;
		case 'load-normal':
			return `${name} back to ${pct}%`;
		default:
			return `${name} at ${pct}%`;
	}
}

/**
 * How much went down at each step, for marking the timeline: devices and
 * links, so that a branch losing every device stands out from one switch.
 *
 * @param events - Events.
 * @param start - Time of step 0, in milliseconds.
 * @returns Devices and links that went down, by step index; quiet steps are absent.
 */
export function downsBySteps(events: StateEvent[], start: number): Map<number, number> {
	const steps = new Map<number, number>();
	for (const e of events) {
		if (e.kind !== 'down' && e.kind !== 'link-down') continue;
		const step = Math.round((Date.parse(e.at) - start) / STEP_MS);
		steps.set(step, (steps.get(step) ?? 0) + 1);
	}
	return steps;
}

/**
 * A link's load each way over time, from the history of one of its ends.
 *
 * @param history - History of the device at one end of the link.
 * @param link - The link.
 * @returns Load from A to B and from B to A at each step, and where the link was down.
 */
export function linkHistory(
	history: DeviceHistory,
	link: Link
): { aToB: (number | null)[]; bToA: (number | null)[]; down: boolean[] } | null {
	const end =
		isDeviceEnd(link.b) && link.b.device === history.device && link.a.device !== history.device
			? link.b
			: link.a;
	const atA = end === link.a;
	const series = history.interfaces.find((i) => i.interface === end.interface);
	if (!series) return null;
	return {
		aToB: atA ? series.out_pct : series.in_pct,
		bToA: atA ? series.in_pct : series.out_pct,
		down: series.oper.map((o) => o === 'down')
	};
}

/**
 * A moment as a short clock time, with the weekday if it is not today.
 *
 * @param iso - ISO time.
 * @returns For example `14:05`, or `Mon 23:40`.
 */
export function clock(iso: string): string {
	const at = new Date(iso);
	const time = at.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
	if (at.toDateString() === new Date().toDateString()) return time;
	return `${at.toLocaleDateString([], { weekday: 'short' })} ${time}`;
}

/** The stretch of time history covers. */
export interface Span {
	since: string;
	until: string;
}

/**
 * The step before a moment, for stepping back through history the way the
 * time slider does.
 *
 * @param at - The moment shown (ISO time), or null for now.
 * @param span - The stretch history covers.
 * @returns The step before, never before history starts.
 */
export function stepEarlier(at: string | null, span: Span): string {
	const first = Math.ceil(Date.parse(span.since) / STEP_MS) * STEP_MS;
	const latest = Math.floor(Date.parse(span.until) / STEP_MS) * STEP_MS;
	const from = at ? Math.round(Date.parse(at) / STEP_MS) * STEP_MS - STEP_MS : latest;
	return new Date(Math.max(first, from)).toISOString();
}

/**
 * The step after a moment, or now once there is none.
 *
 * @param at - The moment shown (ISO time).
 * @param span - The stretch history covers.
 * @returns The step after, or null for now.
 */
export function stepLater(at: string, span: Span): string | null {
	const latest = Math.floor(Date.parse(span.until) / STEP_MS) * STEP_MS;
	const next = Math.round(Date.parse(at) / STEP_MS) * STEP_MS + STEP_MS;
	return next > latest ? null : new Date(next).toISOString();
}
