/**
 * What failures do to the network: which devices they cut off from the
 * core, and which they leave hanging on a single device.
 *
 * "The core" is every device with the core role, where the data centers,
 * the monitoring positions, and the way to other sites are. A device is cut
 * off when no path of working devices and links joins it to any core device.
 * It has no redundancy when every such path runs through one same device, so
 * one more failure would cut it off.
 *
 * Single points of failure come from one depth-first search from a virtual
 * root joined to every core device (Tarjan's articulation points): a device
 * u is the only way to the core for the part of the search tree below its
 * child c when nothing below c links back above u.
 */
import type { Link } from './api/topology.ts';
import type { Selection } from './state.svelte.ts';
import type { TopologyIndex } from './topology.ts';

export interface Failures {
	devices: Set<string>;
	links: Set<string>;
}

export interface Reach {
	/** Devices with a path to the core. */
	reached: Set<string>;
	/**
	 * Reached devices whose every path to the core runs through one device,
	 * with those devices, core side first.
	 */
	fragile: Map<string, string[]>;
}

export interface Impact {
	failed: Failures;
	/** Devices, not failed themselves, left with no path to the core. */
	cutOff: Set<string>;
	/** Devices that had a second path to the core and now have one, with the devices it runs through. */
	exposed: Map<string, string[]>;
}

/** How one device or link is affected, for drawing. */
export type DeviceImpact = 'failed' | 'cutoff' | 'exposed';
export type LinkImpact = 'lost' | 'partial';

export const IMPACT_LABEL: Record<DeviceImpact, string> = {
	failed: 'Failed',
	cutoff: 'Cut off',
	exposed: 'No redundancy left'
};

const SEVERITY: DeviceImpact[] = ['exposed', 'cutoff', 'failed'];

export function noFailures(): Failures {
	return { devices: new Set(), links: new Set() };
}

/**
 * The devices and links some selected items stand for.
 *
 * @param index - Topology index.
 * @param items - Devices, sites (all their devices), and links.
 * @returns Everything they include.
 */
export function failuresOf(index: TopologyIndex, items: Selection[]): Failures {
	const failures = noFailures();
	for (const item of items) {
		if (item.kind === 'device') failures.devices.add(item.id);
		else if (item.kind === 'site') {
			for (const d of index.devicesBySite.get(item.id) ?? []) failures.devices.add(d.name);
		} else for (const id of item.ids) failures.links.add(id);
	}
	return failures;
}

/**
 * Which devices reach the core around some failures, and which of them
 * depend on a single device to do so.
 *
 * @param index - Topology index.
 * @param failures - Devices and links to leave out.
 * @returns Reached devices, and the fragile ones among them.
 */
export function reach(index: TopologyIndex, failures: Failures): Reach {
	const devices = index.topology.devices;
	const n = devices.length;
	const ROOT = n;
	const id = new Map(devices.map((d, i) => [d.name, i]));
	const adjacent: [number, number][][] = devices.map(() => []);
	index.topology.links.forEach((link, li) => {
		if (failures.links.has(link.id)) return;
		if (failures.devices.has(link.a.device) || failures.devices.has(link.b.device)) return;
		const a = id.get(link.a.device);
		const b = id.get(link.b.device);
		if (a === undefined || b === undefined) return;
		adjacent[a]?.push([b, li]);
		adjacent[b]?.push([a, li]);
	});

	// Discovery times start at 1: the virtual root is 0, and every core device
	// links back to it, so a core device anywhere in the tree has low 0.
	const disc = new Int32Array(n).fill(-1);
	const low = new Int32Array(n);
	const parent = new Int32Array(n).fill(ROOT);
	const parentLink = new Int32Array(n).fill(-1);
	const next = new Int32Array(n);
	const order: number[] = [];
	let time = 1;
	const discover = (v: number, from: number, link: number) => {
		disc[v] = time++;
		low[v] = devices[v]?.role === 'core' ? 0 : (disc[v] ?? 0);
		parent[v] = from;
		parentLink[v] = link;
		order.push(v);
	};
	devices.forEach((device, start) => {
		if (device.role !== 'core' || failures.devices.has(device.name) || disc[start] !== -1) return;
		discover(start, ROOT, -1);
		const stack = [start];
		while (stack.length > 0) {
			const v = stack[stack.length - 1] ?? start;
			const edges = adjacent[v] ?? [];
			const i = next[v] ?? 0;
			if (i < edges.length) {
				next[v] = i + 1;
				const [w, li] = edges[i] ?? [0, -1];
				// Skip only the tree link itself: a parallel link back to the parent is a second way.
				if (li === parentLink[v]) continue;
				if (disc[w] === -1) {
					discover(w, v, li);
					stack.push(w);
				} else low[v] = Math.min(low[v] ?? 0, disc[w] ?? 0);
			} else {
				stack.pop();
				const p = parent[v] ?? ROOT;
				if (p !== ROOT) low[p] = Math.min(low[p] ?? 0, low[v] ?? 0);
			}
		}
	});

	// In discovery order, every parent is settled before its children.
	const chain: string[][] = [];
	const fragile = new Map<string, string[]>();
	for (const v of order) {
		const p = parent[v] ?? ROOT;
		const above = p === ROOT ? [] : (chain[p] ?? []);
		const only = p !== ROOT && (low[v] ?? 0) >= (disc[p] ?? 0);
		chain[v] = only ? [...above, devices[p]?.name ?? ''] : above;
		if (chain[v].length > 0) fragile.set(devices[v]?.name ?? '', chain[v]);
	}
	return { reached: new Set(order.map((v) => devices[v]?.name ?? '')), fragile };
}

const healthy = new WeakMap<TopologyIndex, Reach>();

/**
 * What some failures do on top of others.
 *
 * @param index - Topology index.
 * @param failures - The failures to look at.
 * @param before - Failures already in place (for example, what live state
 *   shows down); their effects are not counted again.
 * @returns The failures, the devices they cut off, and the devices they leave without redundancy.
 */
export function impactOf(
	index: TopologyIndex,
	failures: Failures,
	before: Failures = noFailures()
): Impact {
	const nothingBefore = before.devices.size === 0 && before.links.size === 0;
	let was = nothingBefore ? healthy.get(index) : undefined;
	if (!was) {
		was = reach(index, before);
		if (nothingBefore) healthy.set(index, was);
	}
	const now = reach(index, {
		devices: new Set([...before.devices, ...failures.devices]),
		links: new Set([...before.links, ...failures.links])
	});
	const cutOff = new Set(
		[...was.reached].filter((d) => !now.reached.has(d) && !failures.devices.has(d))
	);
	const exposed = new Map([...now.fragile].filter(([d]) => !was.fragile.has(d)));
	return { failed: failures, cutOff, exposed };
}

/**
 * How a device is affected.
 *
 * @param impact - The impact being shown.
 * @param device - Device name.
 * @returns Failed, cut off, left exposed, or null if untouched.
 */
export function deviceImpact(impact: Impact, device: string): DeviceImpact | null {
	if (impact.failed.devices.has(device)) return 'failed';
	if (impact.cutOff.has(device)) return 'cutoff';
	if (impact.exposed.has(device)) return 'exposed';
	return null;
}

/**
 * The worst way any of a group of devices (a site) is affected.
 *
 * @param impact - The impact being shown.
 * @param devices - Device names.
 * @returns The most severe device impact among them, or null.
 */
export function worstImpact(impact: Impact, devices: string[]): DeviceImpact | null {
	let worst = -1;
	for (const d of devices) {
		const found = deviceImpact(impact, d);
		if (found) worst = Math.max(worst, SEVERITY.indexOf(found));
	}
	return SEVERITY[worst] ?? null;
}

/**
 * Whether links carry traffic any more: lost when failed or ending at a
 * failed or cut-off device.
 *
 * @param impact - The impact being shown.
 * @param links - Links drawn as one (a LAG, or a site pair).
 * @returns Lost when all are, partial when some are, null when none.
 */
export function linksImpact(impact: Impact, links: Link[]): LinkImpact | null {
	const gone = (d: string) => impact.failed.devices.has(d) || impact.cutOff.has(d);
	const lost = links.filter(
		(l) => impact.failed.links.has(l.id) || gone(l.a.device) || gone(l.b.device)
	).length;
	if (lost === 0) return null;
	return lost === links.length ? 'lost' : 'partial';
}
