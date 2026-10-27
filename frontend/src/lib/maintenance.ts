/**
 * Maintenance windows as the UI shows them: whether each is open, coming
 * up, or over, which of them name a given device, site, or link, and how
 * to describe them.
 */
import type { Window } from './api/operations.ts';
import { clock } from './history.ts';
import type { Selection } from './state.svelte.ts';
import { linkName, siteOf, type TopologyIndex } from './topology.ts';

export type Phase = 'open' | 'upcoming' | 'ended';

/**
 * Where a window is in time.
 *
 * @param window - The window.
 * @param now - The moment, in milliseconds.
 * @returns Open, upcoming, or ended.
 */
export function phaseOf(window: Window, now: number): Phase {
	if (now < Date.parse(window.start)) return 'upcoming';
	return now < Date.parse(window.end) ? 'open' : 'ended';
}

/**
 * The windows that work on something: a device directly or through its
 * site, a site or any of its devices, or links or a device at their ends.
 *
 * @param index - Topology index.
 * @param windows - Every window.
 * @param item - The device, site, or links.
 * @returns The windows naming it, earliest first.
 */
export function windowsFor(index: TopologyIndex, windows: Window[], item: Selection): Window[] {
	const devices = new Set<string>();
	const sites = new Set<string>();
	const links = new Set<string>();
	if (item.kind === 'device') {
		devices.add(item.id);
		sites.add(siteOf(index, item.id));
	} else if (item.kind === 'site') {
		sites.add(item.id);
		for (const d of index.devicesBySite.get(item.id) ?? []) devices.add(d.name);
	} else {
		for (const id of item.ids) {
			links.add(id);
			const link = index.links.get(id);
			if (link) for (const d of [link.a.device, link.b.device]) devices.add(d);
		}
	}
	return windows.filter((w) =>
		w.targets.some((t) =>
			t.kind === 'device'
				? devices.has(t.id)
				: t.kind === 'site'
					? sites.has(t.id)
					: t.ids.some((id) => links.has(id))
		)
	);
}

/**
 * A short name for something a window works on.
 *
 * @param index - Topology index.
 * @param target - A device, site, or links.
 * @returns The device, the site with "(whole site)", or the link or link count.
 */
export function targetName(index: TopologyIndex, target: Selection): string {
	if (target.kind === 'device') return target.id;
	if (target.kind === 'site') return `${target.id} (whole site)`;
	const links = target.ids.flatMap((id) => index.links.get(id) ?? []);
	return links.length === 1 && links[0] ? linkName(links[0]) : `${links.length} links`;
}

/**
 * When a window runs, briefly.
 *
 * @param window - The window.
 * @returns For example `14:00 – 16:00`, with weekdays for other days.
 */
export function span(window: Window): string {
	return `${clock(window.start)} – ${clock(window.end)}`;
}
