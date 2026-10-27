/**
 * Devices within N hops of a starting set, for the device-centric view.
 *
 * A hop is one link. Hops are added whole: when the next hop would take the
 * neighborhood past the size limit, it is left out and reported instead, so
 * the view never shows half of a ring of neighbors.
 */
import type { Selection } from '../state.svelte.ts';
import type { TopologyIndex } from '../topology.ts';

export interface Neighborhood {
	/** Hop distance of each device included; the starting devices are 0. */
	hops: Map<string, number>;
	/** Hops included, which is fewer than asked when the next one was cut. */
	reached: number;
	/** Devices the next hop would have added when it was cut, else 0. */
	cut: number;
}

/**
 * The devices a selection starts a neighborhood from.
 *
 * @param index - Topology index.
 * @param selection - A device, a site (all its devices), or links (their ends).
 * @returns Device names; empty for no selection.
 */
export function seedsOf(index: TopologyIndex, selection: Selection | null): string[] {
	if (!selection) return [];
	if (selection.kind === 'device') return index.devices.has(selection.id) ? [selection.id] : [];
	if (selection.kind === 'site') {
		return (index.devicesBySite.get(selection.id) ?? []).map((d) => d.name);
	}
	const ends = selection.ids.flatMap((id) => {
		const link = index.links.get(id);
		return link ? [link.a.device, link.b.device] : [];
	});
	return [...new Set(ends)];
}

/**
 * Walk outward from the seeds one hop at a time.
 *
 * @param index - Topology index.
 * @param seeds - Starting devices.
 * @param maxHops - Hops to walk at most.
 * @param limit - Most devices to include.
 * @returns The devices reached and how far.
 */
export function neighborhood(
	index: TopologyIndex,
	seeds: string[],
	maxHops: number,
	limit: number
): Neighborhood {
	const hops = new Map(seeds.map((s) => [s, 0]));
	let frontier = seeds;
	let reached = 0;
	while (reached < maxHops) {
		const next = new Set<string>();
		for (const device of frontier) {
			for (const link of index.linksByDevice.get(device) ?? []) {
				const other = link.a.device === device ? link.b.device : link.a.device;
				if (!hops.has(other)) next.add(other);
			}
		}
		if (next.size === 0) break;
		if (hops.size + next.size > limit) return { hops, reached, cut: next.size };
		reached++;
		for (const device of next) hops.set(device, reached);
		frontier = [...next];
	}
	return { hops, reached, cut: 0 };
}
