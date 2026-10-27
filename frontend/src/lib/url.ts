/**
 * What is on screen, as a link, so whoever opens it sees the same thing.
 *
 * Links stay readable, and carry only what differs from how Sunstone opens:
 * `?view=hierarchy&select=device:dal-core-01&live=1&at=2026-10-27T14:05:00Z`.
 * Devices, sites, and links are written `device:NAME`, `site:CODE`, or
 * `links:ID ID`. Reading a link skips anything that no longer matches the
 * network, such as a device since renamed, rather than failing.
 */
import type { Selection, View } from './state.svelte.ts';
import type { TopologyIndex } from './topology.ts';

export interface Camera {
	lon: number;
	lat: number;
	zoom: number;
}

/** Everything a link carries. */
export interface Shared {
	view: View;
	selection: Selection | null;
	live: boolean;
	/** The replayed moment, or null for now. */
	at: string | null;
	path: { from: string; to: string } | null;
	whatIf: Selection[];
	/** The problem whose impact is shown, by id. */
	problem: string | null;
	topo: {
		scope: 'network' | 'neighborhood' | 'path';
		hops: number;
		layout: 'force' | 'radial';
		grouped: boolean;
		center: Selection | null;
	};
	/** Sites shown device by device in the graph views. */
	expanded: string[];
	/** Where the map is, in the geographic view. */
	camera: Camera | null;
	/** Wall display, and how long it shows each thing; null when off. */
	wall: { dwell: number } | null;
	/** Discovery against the documentation, shown on the map. */
	discovery: boolean;
}

export const DEFAULT_DWELL_S = 20;
const VIEWS: View[] = ['geo', 'hierarchy', 'topology'];
const SCOPES = ['network', 'neighborhood', 'path'] as const;

/**
 * Write a device, site, or links.
 *
 * @param item - The item.
 * @returns For example `device:dal-core-01`, or `links:ID ID`.
 */
export function writeItem(item: Selection): string {
	return item.kind === 'links' ? `links:${item.ids.join(' ')}` : `${item.kind}:${item.id}`;
}

/**
 * Read a device, site, or links, if they are in the network.
 *
 * @param text - As written by {@link writeItem}.
 * @param index - Topology index.
 * @returns The item, or null if it is malformed or not in the network.
 */
export function readItem(text: string, index: TopologyIndex): Selection | null {
	const colon = text.indexOf(':');
	const [kind, rest] = [text.slice(0, colon), text.slice(colon + 1)];
	if (kind === 'device') return index.devices.has(rest) ? { kind, id: rest } : null;
	if (kind === 'site') return index.sites.has(rest) ? { kind, id: rest } : null;
	if (kind !== 'links') return null;
	const ids = rest.split(' ').filter((id) => index.links.has(id));
	return ids.length ? { kind, ids } : null;
}

/**
 * The link for what is on screen.
 *
 * @param shared - What is on screen.
 * @param index - Topology index, to tell whether every site is expanded.
 * @returns The query string's parameters, defaults left out.
 */
export function toQuery(shared: Shared, index: TopologyIndex): URLSearchParams {
	const q = new URLSearchParams();
	if (shared.wall) {
		q.set('wall', '1');
		if (shared.wall.dwell !== DEFAULT_DWELL_S) q.set('dwell', String(shared.wall.dwell));
	}
	if (shared.view !== 'geo') q.set('view', shared.view);
	if (shared.selection) q.set('select', writeItem(shared.selection));
	if (shared.live) {
		q.set('live', '1');
		if (shared.at) q.set('at', shared.at);
		if (shared.problem) q.set('problem', shared.problem);
	}
	if (shared.path) {
		q.set('from', shared.path.from);
		q.set('to', shared.path.to);
	}
	for (const item of shared.whatIf) q.append('fail', writeItem(item));
	if (shared.discovery) q.set('discovery', '1');
	if (shared.view === 'topology') {
		const { scope, hops, layout, grouped, center } = shared.topo;
		if (scope !== 'network') q.set('scope', scope);
		if (scope === 'neighborhood' && center) q.set('center', writeItem(center));
		if (scope === 'neighborhood' && hops !== 2) q.set('hops', String(hops));
		if (layout !== 'force') q.set('layout', layout);
		if (!grouped) q.set('grouped', '0');
	}
	if (shared.view !== 'geo') {
		const all = shared.expanded.length === index.topology.sites.length;
		q.set('expanded', all ? 'all' : shared.expanded.length ? shared.expanded.join(',') : 'none');
	}
	if (shared.view === 'geo' && shared.camera) {
		const { lon, lat, zoom } = shared.camera;
		q.set('map', [lon.toFixed(4), lat.toFixed(4), zoom.toFixed(2)].join(','));
	}
	return q;
}

/**
 * What a link asks to show, as far as it matches the network.
 *
 * @param q - The query string's parameters.
 * @param index - Topology index.
 * @returns The parts the link sets; anything left out keeps its default.
 */
export function fromQuery(q: URLSearchParams, index: TopologyIndex): Partial<Shared> {
	const found: Partial<Shared> = {};
	const view = q.get('view');
	if (view && (VIEWS as string[]).includes(view)) found.view = view as View;
	const selection = q.get('select');
	if (selection) found.selection = readItem(selection, index);
	if (q.get('live') === '1') {
		found.live = true;
		const at = q.get('at');
		if (at && !Number.isNaN(Date.parse(at))) found.at = at;
		found.problem = q.get('problem');
	}
	const [from, to] = [q.get('from'), q.get('to')];
	if (from && to && index.devices.has(from) && index.devices.has(to)) found.path = { from, to };
	const whatIf = q.getAll('fail').flatMap((t) => readItem(t, index) ?? []);
	if (whatIf.length) found.whatIf = whatIf;
	if (q.get('discovery') === '1') found.discovery = true;
	const scope = q.get('scope');
	const hops = Number(q.get('hops'));
	const layout = q.get('layout');
	const center = q.get('center');
	if (scope || q.has('hops') || layout || q.has('grouped') || center) {
		found.topo = {
			scope: (SCOPES as readonly string[]).includes(scope ?? '')
				? (scope as Shared['topo']['scope'])
				: 'network',
			hops: Number.isInteger(hops) && hops >= 1 && hops <= 4 ? hops : 2,
			layout: layout === 'radial' ? 'radial' : 'force',
			grouped: q.get('grouped') !== '0',
			center: center ? readItem(center, index) : null
		};
	}
	const expanded = q.get('expanded');
	if (expanded !== null) {
		found.expanded =
			expanded === 'all'
				? index.topology.sites.map((s) => s.code)
				: expanded === 'none'
					? []
					: expanded.split(',').filter((c) => index.sites.has(c));
	}
	const [lon, lat, zoom] = (q.get('map') ?? '').split(',').map(Number);
	if (
		lon !== undefined &&
		lat !== undefined &&
		zoom !== undefined &&
		[lon, lat, zoom].every(Number.isFinite)
	) {
		if (Math.abs(lon) <= 180 && Math.abs(lat) <= 90 && zoom >= 0 && zoom <= 24) {
			found.camera = { lon, lat, zoom };
		}
	}
	if (q.get('wall') === '1') {
		const dwell = Number(q.get('dwell'));
		found.wall = { dwell: dwell >= 5 && dwell <= 600 ? dwell : DEFAULT_DWELL_S };
	}
	return found;
}

/**
 * A query string with the characters links use most left as they are:
 * `select=device:dal-core-01` rather than `select=device%3Adal-core-01`.
 * Colons, commas, and slashes need no escaping in a query string.
 *
 * @param q - The parameters.
 * @returns The query string, without its `?`.
 */
export function readable(q: URLSearchParams): string {
	return q.toString().replace(/%3A/gi, ':').replace(/%2C/gi, ',').replace(/%2F/gi, '/');
}

/**
 * How Sunstone opens, for what a link leaves out when Back or Forward goes to
 * it. The topology view's settings, expanded sites, and the map's position
 * are only in links that show them, so they stay as they are.
 */
export const OPENING = {
	view: 'geo',
	selection: null,
	live: false,
	at: null,
	path: null,
	whatIf: [],
	problem: null,
	wall: null,
	discovery: false
} satisfies Partial<Shared>;

/**
 * Whether going from one screen to another goes somewhere new, so that Back
 * should return from it: another view, neighborhood, selection, path,
 * problem, "what if", or discovery on the map. Moving the map, Live, the time, and expanded sites
 * change how the same place looks, and clearing something stays in place.
 *
 * @param before - What was on screen.
 * @param after - What is on screen now.
 * @returns True to add a step to the browser's history, false to update the current one.
 */
export function movesOn(before: Shared, after: Shared): boolean {
	const differs = (x: unknown, y: unknown) => JSON.stringify(x) !== JSON.stringify(y);
	const scope = (s: Shared) =>
		s.view === 'topology'
			? { scope: s.topo.scope, center: s.topo.scope === 'neighborhood' ? s.topo.center : null }
			: null;
	return (
		before.view !== after.view ||
		differs(scope(before), scope(after)) ||
		(after.selection !== null && differs(before.selection, after.selection)) ||
		(after.path !== null && differs(before.path, after.path)) ||
		(after.problem !== null && before.problem !== after.problem) ||
		(after.whatIf.length > 0 && differs(before.whatIf, after.whatIf)) ||
		(after.discovery && !before.discovery)
	);
}
