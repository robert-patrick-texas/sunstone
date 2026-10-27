/**
 * Shortest paths between two devices, counted in hops (links).
 *
 * Sunstone has no routing metrics, so "shortest" means fewest links. Networks
 * are built with redundancy, so there are usually several equally short
 * paths, and all of them are found: someone tracing a problem needs every
 * way traffic could go. Parallel links (LAG members) are one hop, and every
 * member is part of the path.
 */
import type { Link } from './api/topology.ts';
import { compareNatural, type TopologyIndex } from './topology.ts';

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

const other = (link: Link, device: string) =>
	link.a.device === device ? link.b.device : link.a.device;

/**
 * Find every shortest path between two devices.
 *
 * @param index - Topology index.
 * @param from - Starting device.
 * @param to - Destination device.
 * @returns The paths; `hops` is null when `to` cannot be reached.
 */
export function shortestPaths(index: TopologyIndex, from: string, to: string): PathResult {
	const dist = new Map([[from, 0]]);
	for (let frontier = [from]; frontier.length > 0 && !dist.has(to);) {
		const next: string[] = [];
		for (const device of frontier) {
			for (const link of index.linksByDevice.get(device) ?? []) {
				const neighbor = other(link, device);
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
			for (const link of index.linksByDevice.get(device) ?? []) {
				const neighbor = other(link, device);
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
	return {
		from,
		to,
		hops,
		devices,
		links,
		count: ways.get(to) ?? 0,
		listed: list(from, to, previous)
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
	return (index.linksByDevice.get(a) ?? [])
		.filter((l) => other(l, a) === b && path.links.has(l.id))
		.sort((x, y) => {
			const end = (l: Link) => (l.a.device === a ? l.a : l.b).interface;
			return compareNatural(end(x), end(y));
		});
}
