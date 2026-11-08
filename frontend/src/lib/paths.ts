/**
 * Shortest paths between two devices, counted in hops (links).
 *
 * Sunstone has no routing metrics, so "shortest" means fewest links. Networks
 * are built with redundancy, so there are usually several equally short
 * paths, and all of them are found: someone tracing a problem needs every
 * way traffic could go. Parallel links (LAG members) are one hop, and every
 * member is part of the path. Across an E-Tree, a leaf reaches only the
 * roots, so a path between two leaves goes through a root's router.
 */
import { joins } from './connections.ts';
import type { Link } from './api/topology.ts';
import { compareNatural, isDeviceEnd, nodeKey, type TopologyIndex } from './topology.ts';

/** Most paths listed one by one; the rest are counted. */
export const MAX_LISTED = 12;

export interface PathResult {
	from: string;
	to: string;
	/** Links on each shortest path, or null when the devices are not connected. */
	hops: number | null;
	/** Every device on some shortest path, with its hops from `from`. */
	devices: Map<string, number>;
	/** Every link on some shortest path. */
	links: Set<string>;
	/** Number of shortest paths, as device sequences. */
	count: number;
	/** Up to {@link MAX_LISTED} of them, in name order. */
	listed: string[][];
}

/** One way from a node of a path: the link, and the node it leads to. */
export interface Hop {
	link: Link;
	to: string;
}

const HOPS = new WeakMap<TopologyIndex, Map<string, Hop[]>>();

/**
 * Every way links join nodes, as the server's `transport_hops` has it: a
 * device to a device; a circuit for transit to its transport's node; into
 * an E-Tree, a leaf's circuit to a corner of its own (`transport:NAME~` and
 * its id), which each root's circuit reaches too. An external node leads
 * nowhere, and neither does a circuit for peering, open, ingress, or egress
 * alone.
 *
 * @param index - Topology index.
 * @returns The hops from each node, worked out once per index.
 */
export function hopsOf(index: TopologyIndex): Map<string, Hop[]> {
	const known = HOPS.get(index);
	if (known) return known;
	const hops = new Map<string, Hop[]>();
	const join = (a: string, b: string, link: Link) => {
		hops.set(a, [...(hops.get(a) ?? []), { link, to: b }]);
		hops.set(b, [...(hops.get(b) ?? []), { link, to: a }]);
	};
	const leaves = new Map<string, Link[]>();
	for (const link of index.topology.links) {
		const b = link.b;
		if (!joins(link) || !('transport' in b) || b.role === 'root') continue;
		if (index.transports.get(b.transport)?.service !== 'e-tree') continue;
		leaves.set(b.transport, [...(leaves.get(b.transport) ?? []), link]);
	}
	for (const link of index.topology.links) {
		const b = link.b;
		if (!joins(link)) continue;
		if (isDeviceEnd(b)) {
			join(link.a.device, b.device, link);
		} else if ('transport' in b) {
			const cloud = nodeKey(b);
			const tree = index.transports.get(b.transport)?.service === 'e-tree';
			if (tree && b.role !== 'root') {
				join(link.a.device, `${cloud}~${link.id}`, link);
				continue;
			}
			join(link.a.device, cloud, link);
			if (tree)
				for (const leaf of leaves.get(b.transport) ?? [])
					join(link.a.device, `${cloud}~${leaf.id}`, link);
		}
	}
	HOPS.set(index, hops);
	return hops;
}

/** A node as the views know it: an E-Tree leaf's corner is its transport. */
export const shownNode = (node: string): string =>
	node.startsWith('transport:') && node.includes('~') ? node.slice(0, node.indexOf('~')) : node;

/**
 * Find every shortest path between two devices.
 *
 * @param index - Topology index.
 * @param from - Starting device.
 * @param to - Destination device.
 * @returns The paths; `hops` is null when `to` cannot be reached.
 */
export function shortestPaths(index: TopologyIndex, from: string, to: string): PathResult {
	const hopsAt = hopsOf(index);
	const dist = new Map([[from, 0]]);
	for (let frontier = [from]; frontier.length > 0 && !dist.has(to);) {
		const next: string[] = [];
		for (const device of frontier) {
			for (const { to: neighbor } of hopsAt.get(device) ?? []) {
				if (dist.has(neighbor)) continue;
				dist.set(neighbor, (dist.get(device) ?? 0) + 1);
				next.push(neighbor);
			}
		}
		frontier = next;
	}
	const hops = dist.get(to);
	if (hops === undefined) {
		return { from, to, hops: null, devices: new Map(), links: new Set(), count: 0, listed: [] };
	}

	// Walk back from the destination along links that step one hop closer to the start.
	const devices = new Map([[to, hops]]);
	const links = new Set<string>();
	const previous = new Map<string, Set<string>>();
	for (let frontier = [to]; frontier.length > 0;) {
		const next: string[] = [];
		for (const device of frontier) {
			const here = devices.get(device) ?? 0;
			for (const { link, to: neighbor } of hopsAt.get(device) ?? []) {
				if (dist.get(neighbor) !== here - 1) continue;
				links.add(link.id);
				previous.set(device, (previous.get(device) ?? new Set()).add(neighbor));
				if (devices.has(neighbor)) continue;
				devices.set(neighbor, here - 1);
				next.push(neighbor);
			}
		}
		frontier = next;
	}

	const ways = new Map([[from, 1]]);
	const byDistance = [...devices.keys()].sort(
		(x, y) => (devices.get(x) ?? 0) - (devices.get(y) ?? 0)
	);
	for (const device of byDistance) {
		if (device === from) continue;
		const before = [...(previous.get(device) ?? [])];
		ways.set(
			device,
			before.reduce((sum, p) => sum + (ways.get(p) ?? 0), 0)
		);
	}
	// The views know an E-Tree leaf's corner as its transport.
	const shown = new Map<string, number>();
	for (const [node, at] of devices) {
		const key = shownNode(node);
		shown.set(key, Math.min(at, shown.get(key) ?? at));
	}
	return {
		from,
		to,
		hops,
		devices: shown,
		links,
		count: ways.get(to) ?? 0,
		listed: list(from, to, previous).map((path) => path.map(shownNode))
	};
}

/** Spell out paths back from `to`, stopping at {@link MAX_LISTED}. */
function list(from: string, to: string, previous: Map<string, Set<string>>): string[][] {
	const paths: string[][] = [];
	const walk = (device: string, tail: string[]): void => {
		if (paths.length >= MAX_LISTED) return;
		if (device === from) {
			paths.push([from, ...tail]);
			return;
		}
		for (const p of [...(previous.get(device) ?? [])].sort(compareNatural))
			walk(p, [device, ...tail]);
	};
	walk(to, []);
	return paths.sort((x, y) => compareNatural(x.join(' '), y.join(' ')));
}

/**
 * The path's links between two adjacent devices on it (more than one for a LAG).
 *
 * @param index - Topology index.
 * @param path - The path result.
 * @param a - One device.
 * @param b - The next device.
 * @returns The links, in natural order of `a`'s interfaces.
 */
export function linksBetween(index: TopologyIndex, path: PathResult, a: string, b: string): Link[] {
	const hopsAt = hopsOf(index);
	// A transport, with its E-Tree leaves' corners.
	const from = [...hopsAt.keys()].filter((n) => shownNode(n) === a);
	const found = new Map<string, Link>();
	for (const node of from)
		for (const { link, to } of hopsAt.get(node) ?? [])
			if (shownNode(to) === b && path.links.has(link.id)) found.set(link.id, link);
	return [...found.values()].sort((x, y) => {
		const end = (l: Link) => (l.a.device === a || !isDeviceEnd(l.b) ? l.a : l.b).interface;
		return compareNatural(end(x), end(y));
	});
}
