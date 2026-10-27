/**
 * UI state shared by every view, so switching views keeps the user's context.
 */
import { SvelteSet } from 'svelte/reactivity';
import { DEFAULT_DWELL_S, type Camera } from './url.ts';

export type View = 'geo' | 'hierarchy' | 'topology';

export type Selection =
	{ kind: 'device'; id: string } | { kind: 'site'; id: string } | { kind: 'links'; ids: string[] };

/** A maintenance window being planned (no id yet) or changed. */
export interface WindowDraft {
	id: string | null;
	title: string;
	/** Local date and time, as a datetime-local input holds them. */
	start: string;
	end: string;
	targets: Selection[];
	note: string;
}

const NAME_KEY = 'sunstone.name';

/** The name this browser last signed something with, if it can remember. */
function rememberedName(): string {
	try {
		return localStorage.getItem(NAME_KEY) ?? '';
	} catch {
		// Storage can be off (private windows, blocked site data); then ask each time.
		return '';
	}
}

/**
 * Remember the name people sign maintenance and acknowledgements with.
 *
 * @param name - Their name.
 */
export function rememberName(name: string): void {
	ui.person = name;
	try {
		localStorage.setItem(NAME_KEY, name);
	} catch {
		// Remembered for this visit only.
	}
}

export const ui = $state({
	view: 'geo' as View,
	selection: null as Selection | null,
	/** Incremented to ask the current view to bring the selection into sight. */
	focusRequest: 0,
	/** Devices whose shortest paths are highlighted in every view. */
	path: null as { from: string; to: string } | null,
	/** Start of a path whose destination the user is choosing. */
	pathFrom: null as string | null,
	/** Show live state (device status, link load) over the structure. */
	live: false,
	/** Show the list of problems in live state. */
	problemsOpen: true,
	/** Which list the side panel shows. */
	sideTab: 'problems' as 'problems' | 'events' | 'maintenance',
	/** Who is using Sunstone, for signing maintenance and acknowledgements. */
	person: rememberedName(),
	/** The maintenance window being planned or changed, if any. */
	planning: null as WindowDraft | null,
	/** Where the map is, kept so a link can carry it. */
	camera: null as Camera | null,
	/** Incremented to ask the map to go where `fromLink.camera` says (Back and Forward). */
	cameraRequest: 0,
	/** Incremented to ask the current view to show everything. */
	fitRequest: 0,
	/** The NOC wall display: on, how long it shows each thing, and paused. */
	wall: { on: false, dwell: DEFAULT_DWELL_S, paused: false },
	/** The earlier moment whose live state is shown (ISO time), or null for now. */
	at: null as string | null,
	/** The problem whose impact is shown, by id. */
	problem: null as string | null,
	/** Devices, sites, and links supposed to fail, to see what that would do. */
	whatIf: [] as Selection[]
});

/**
 * Where a link put the map, for the map to go to once: when it opens, or
 * when asked to with `ui.cameraRequest`. Not reactive.
 */
export const fromLink: { camera: Camera | null } = { camera: null };

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
	ui.problem = null;
	ui.whatIf = [];
}

/** Stop showing a path, or stop choosing one. */
export function clearPath(): void {
	ui.path = null;
	ui.pathFrom = null;
}

/**
 * Add something to the "what if" failures, unless it is already there.
 *
 * @param item - Device, site, or links to suppose failed.
 */
export function addFailure(item: Selection): void {
	clearPath();
	ui.problem = null;
	const key = JSON.stringify(item);
	if (!ui.whatIf.some((f) => JSON.stringify(f) === key)) ui.whatIf.push(item);
}

/**
 * Start planning maintenance, in the side panel.
 *
 * @param targets - What will be worked on, to start with.
 */
export function planMaintenance(targets: Selection[]): void {
	// Start at the next 5-minute mark, for an hour.
	const step = 5 * 60_000;
	const start = new Date(Math.ceil(Date.now() / step) * step);
	const end = new Date(start.getTime() + 60 * 60_000);
	ui.planning = {
		id: null,
		title: '',
		start: localTime(start),
		end: localTime(end),
		targets,
		note: ''
	};
	ui.sideTab = 'maintenance';
	ui.problemsOpen = true;
}

/**
 * Show what failing some items would do, in place of any path or problem.
 *
 * @param targets - Devices, sites, and links.
 */
export function checkImpact(targets: Selection[]): void {
	clearPath();
	ui.problem = null;
	ui.whatIf = targets;
}

/**
 * A moment as a datetime-local input wants it: local time, to the minute.
 *
 * @param at - The moment.
 * @returns For example `2026-10-27T14:05`.
 */
export function localTime(at: Date): string {
	const local = new Date(at.getTime() - at.getTimezoneOffset() * 60_000);
	return local.toISOString().slice(0, 16);
}

/**
 * Show a problem's impact, or stop showing it if it is already shown.
 *
 * @param problem - The problem's id, and what to select for it.
 */
export function showProblem(problem: { id: string; target: Selection }): void {
	if (ui.problem === problem.id) {
		ui.problem = null;
		return;
	}
	clearPath();
	ui.whatIf = [];
	ui.problem = problem.id;
	select(problem.target, true);
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
