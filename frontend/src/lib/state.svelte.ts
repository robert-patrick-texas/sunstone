/**
 * UI state shared by every view, so switching views keeps the user's context.
 */
import { SvelteSet } from 'svelte/reactivity';

export type View = 'geo' | 'hierarchy' | 'topology';

export type Selection =
	{ kind: 'device'; id: string } | { kind: 'site'; id: string } | { kind: 'links'; ids: string[] };

export const ui = $state({
	view: 'geo' as View,
	selection: null as Selection | null,
	/** Incremented to ask the current view to bring the selection into sight. */
	focusRequest: 0,
	/** Devices whose shortest paths are highlighted in every view. */
	path: null as { from: string; to: string } | null,
	/** Start of a path whose destination the user is choosing. */
	pathFrom: null as string | null
});

/** Sites the graph views show device by device instead of as one box. */
export const expandedSites = new SvelteSet<string>();

/** Settings of the topology view, kept across view switches. */
export const topo = $state({
	scope: 'network' as 'network' | 'neighborhood' | 'path',
	hops: 2,
	layout: 'force' as 'force' | 'radial',
	/** Draw devices inside a frame per site (force-directed layout only). */
	grouped: true,
	/** What the neighborhood is built around. */
	center: null as Selection | null
});

/**
 * Open the topology view on the neighborhood of something.
 *
 * @param center - Device, site, or links to build the neighborhood around.
 */
export function showNeighborhood(center: Selection): void {
	topo.center = center;
	topo.scope = 'neighborhood';
	ui.view = 'topology';
}

/**
 * Start a path: the next device selected becomes its destination.
 *
 * @param from - Starting device.
 */
export function startPath(from: string): void {
	ui.path = null;
	ui.pathFrom = from;
}

/** Stop showing a path, or stop choosing one. */
export function clearPath(): void {
	ui.path = null;
	ui.pathFrom = null;
}

/**
 * Change the selection.
 *
 * @param selection - What to select, or null to clear.
 * @param focus - Also move the current view to it (search results, links in the details panel).
 */
export function select(selection: Selection | null, focus = false): void {
	ui.selection = selection;
	if (focus) ui.focusRequest++;
	if (ui.pathFrom && selection?.kind === 'device' && selection.id !== ui.pathFrom) {
		ui.path = { from: ui.pathFrom, to: selection.id };
		ui.pathFrom = null;
	}
}
