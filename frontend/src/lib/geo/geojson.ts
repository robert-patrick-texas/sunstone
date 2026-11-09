/**
 * GeoJSON for the geographic view.
 *
 * Zoomed out, each site is one point and the links between two sites are
 * one line. Zoomed in, a site's devices are drawn on rings around the site's
 * coordinates, upper tiers on inner rings. The rings are a drawing aid, not
 * real device locations: sources give coordinates per site, not per device.
 * Resources are points of their own amid their members' sites, with leader
 * lines to those sites; that place, too, is a drawing aid.
 *
 * Given live state, features also carry `health` (and `util`, `glyph`, or a
 * fuller site `label`) for the map's live styling; without it they carry
 * none, and the map draws structure only. Given an impact to show, affected
 * features carry `impact` (and a `glyph` and site `label` to match), and
 * unaffected ones carry neither.
 *
 * What is hidden from the map is left out, and devices are labeled by the
 * names they are shown by.
 */
import type { Feature, FeatureCollection, LineString, Point } from 'geojson';
import type { SeenLink } from '../api/discovery.ts';
import type { StatusReport } from '../api/status.ts';
import type { Link } from '../api/topology.ts';
import { deviceImpact, linksImpact, tunnelsImpact, worstImpact, type Impact } from '../impact.ts';
import {
	bundleLive,
	deviceHealth,
	groupHealth,
	linkLive,
	tunnelsLive,
	type LiveIndex
} from '../live.ts';
import { fabricTunnels, layersOf } from '../layers.ts';
import { hiddenOnMap, shown } from '../overrides.svelte.ts';
import { resourceSites, resourceStatus } from '../resources.ts';
import { STATUS_GLYPH } from '../status.ts';
import { depthColor, HEALTH_GLYPH, IMPACT_COLOR, IMPACT_GLYPH, TUNNEL_COLOR } from '../theme.ts';
import { farDevice, ROLES, siteOf, type TopologyIndex } from '../topology.ts';

/** How long, in degrees, the stub drawn for a circuit into a transport is. */
const STUB_DEG = 0.0006;

export type LonLat = [number, number];

/** Zoom at which sites open up into their devices. */
export const DEVICE_ZOOM = 13.5;

const FIRST_RING_M = 40;
const RING_GAP_M = 60;
const DEVICE_SPACING_M = 45;
const METERS_PER_DEGREE = 111_320;

/** All links between one pair of sites. */
export interface SitePair {
	key: string;
	a: string;
	b: string;
	linkIds: string[];
	capacityMbps: number;
}

/**
 * Key for an unordered pair of sites.
 *
 * @param a - One site code.
 * @param b - The other site code.
 * @returns The same key whichever order the codes come in.
 */
export function pairKey(a: string, b: string): string {
	return a < b ? `${a}|${b}` : `${b}|${a}`;
}

/**
 * Group the links that cross between sites by site pair.
 *
 * @param index - Topology index.
 * @returns One entry per connected site pair.
 */
export function sitePairs(index: TopologyIndex): SitePair[] {
	const pairs = new Map<string, SitePair>();
	const hidden = hiddenOnMap(index);
	for (const link of index.topology.links) {
		if (hidden.links.has(link.id)) continue;
		const far = farDevice(link);
		if (far === null) continue; // into a transport or to an external node
		const a = siteOf(index, link.a.device);
		const b = siteOf(index, far);
		if (a === b) continue;
		const key = pairKey(a, b);
		const pair = pairs.get(key) ?? { key, a, b, linkIds: [], capacityMbps: 0 };
		pair.linkIds.push(link.id);
		pair.capacityMbps += link.speed_mbps;
		pairs.set(key, pair);
	}
	return [...pairs.values()];
}

/**
 * Where to draw each device when zoomed in: rings around its site.
 *
 * @param index - Topology index.
 * @returns Longitude/latitude per device name.
 */
export function devicePositions(index: TopologyIndex): Map<string, LonLat> {
	const positions = new Map<string, LonLat>();
	for (const site of index.topology.sites) {
		const devices = index.devicesBySite.get(site.code) ?? [];
		let radius = 0;
		for (const [tier, role] of ROLES.entries()) {
			const ring = devices.filter((d) => d.role === role);
			if (ring.length === 0) continue;
			const fit = (ring.length * DEVICE_SPACING_M) / (2 * Math.PI);
			radius = Math.max(radius === 0 ? FIRST_RING_M : radius + RING_GAP_M, fit);
			ring.forEach((device, i) => {
				// Each ring starts at a different angle so tiers don't line up into spokes.
				const angle = tier * 0.4 + (2 * Math.PI * i) / ring.length - Math.PI / 2;
				const east = radius * Math.cos(angle);
				const north = radius * Math.sin(angle);
				positions.set(device.name, [
					site.lon + east / (METERS_PER_DEGREE * Math.cos((site.lat * Math.PI) / 180)),
					site.lat + north / METERS_PER_DEGREE
				]);
			});
		}
	}
	return positions;
}

function collection<G extends Point | LineString>(features: Feature<G>[]): FeatureCollection<G> {
	return { type: 'FeatureCollection', features };
}

/**
 * Site points, sized by device count.
 *
 * @param index - Topology index.
 * @param live - Live state, or null for structure only.
 * @param impact - Impact to show, or null.
 * @returns One point per site; with live state, its worst device health;
 *   with an impact, its worst-affected device.
 */
export function siteFeatures(
	index: TopologyIndex,
	live: LiveIndex | null = null,
	impact: Impact | null = null
): FeatureCollection<Point> {
	const hidden = hiddenOnMap(index);
	const sites = index.topology.sites.filter((s) => !hidden.sites.has(s.code));
	return collection(
		sites.map((site) => {
			const devices = (index.devicesBySite.get(site.code) ?? []).map((d) => d.name);
			const properties: Record<string, unknown> = {
				code: site.code,
				name: site.name,
				devices: devices.length
			};
			const transports = layersOf(index)
				.transportsAt.get(site.code)
				?.filter((t) => !hidden.transports.has(t));
			if (transports?.length) properties['transports'] = transports.join(' · ');
			if (live) {
				const { health, counts } = groupHealth(live, devices);
				properties['health'] = health;
				if (counts.down) properties['label'] = `${site.code} · ${counts.down} down`;
			}
			if (impact) {
				const found = worstImpact(impact, devices);
				const lost = devices.filter((d) => impact.cutOff.has(d) || impact.failed.devices.has(d));
				delete properties['label'];
				if (found) properties['impact'] = found;
				if (lost.length) properties['label'] = `${site.code} · ${lost.length} lost`;
			}
			return {
				type: 'Feature',
				geometry: { type: 'Point', coordinates: [site.lon, site.lat] },
				properties
			};
		})
	);
}

/** How far an arc bows out from the straight line, as a share of its length. */
const BOW = 0.18;
const ARC_POINTS = 24;

/**
 * Tunnels of named networks as arcs between their sites: each network's own
 * tunnels, and the tunnels its fabrics are made of. Arcs of different
 * networks between the same two sites bow out on alternate sides, further
 * each time. A tunnel to an external node has no place on the map. With
 * live state, arcs take their tunnels' health, and spoke-to-spoke tunnels
 * built now are drawn too, thinner. With a "what if" impact, arcs whose
 * tunnels it takes down are drawn as lost, or partly lost.
 *
 * @param index - Topology index.
 * @param networks - The networks to draw.
 * @param live - Live state, or null for structure only.
 * @param impact - Impact to show, or null.
 * @returns One arc per network and site pair, with its network, color, the
 *   tunnel or fabric to select for it, whether it was built on demand, and
 *   with an impact, whether its tunnels are lost.
 */
export function networkArcs(
	index: TopologyIndex,
	networks: string[],
	live: LiveIndex | null = null,
	impact: Impact | null = null
): FeatureCollection<LineString> {
	const layers = layersOf(index);
	const hidden = hiddenOnMap(index);
	const arcs = new Map<
		string,
		{ a: string; b: string; tunnels: string[]; properties: Record<string, string | boolean> }
	>();
	const add = (
		x: string,
		y: string,
		network: string,
		id: string,
		ref: Record<string, string | boolean>
	) => {
		if (hidden.devices.has(x) || hidden.devices.has(y)) return;
		const [a, b] = [siteOf(index, x), siteOf(index, y)];
		if (a === b) return;
		const key = `${network}|${pairKey(a, b)}${ref['dynamic'] ? '|on demand' : ''}`;
		const found = arcs.get(key);
		if (found) {
			found.tunnels.push(id);
			return;
		}
		arcs.set(key, { a, b, tunnels: [id], properties: { id: key, network, ...ref } });
	};
	for (const name of networks) {
		const slice = layers.slices.get(name);
		if (!slice) continue;
		for (const t of slice.tunnels) {
			if (hidden.tunnels.has(t.name)) continue;
			if ('device' in t.b) add(t.a.device, t.b.device, name, t.name, { tunnel: t.name });
		}
		for (const f of slice.fabrics) {
			if (hidden.fabrics.has(f.name)) continue;
			for (const { a, b } of fabricTunnels(f)) {
				add(a.device, b.device, name, `${f.name}:${a.device}~${b.device}`, { fabric: f.name });
			}
		}
		for (const t of live?.tunnels.values() ?? []) {
			if (t.network !== name || !t.dynamic || t.status !== 'up') continue;
			const fabric = t.tunnel.slice(0, t.tunnel.indexOf(':'));
			const [a, b] = t.tunnel.slice(fabric.length + 1).split('~');
			if (!a || !b || hidden.fabrics.has(fabric)) continue;
			add(a, b, name, t.tunnel, { fabric, dynamic: true });
		}
	}
	const seen = new Map<string, number>();
	const features = [...arcs.values()].flatMap(({ a, b, tunnels, properties }) => {
		const [from, to] = [index.sites.get(a), index.sites.get(b)];
		if (!from || !to) return [];
		const n = seen.get(pairKey(a, b)) ?? 0;
		seen.set(pairKey(a, b), n + 1);
		// Bow to alternate sides, further for each network after the first two.
		const bow = BOW * (1 + Math.floor(n / 2)) * (n % 2 ? -1 : 1);
		const depth = layers.slices.get(String(properties['network']))?.depth ?? 0;
		const lost = impact ? tunnelsImpact(impact, tunnels) : null;
		const color = lost
			? IMPACT_COLOR[lost === 'lost' ? 'failed' : 'exposed']
			: live
				? TUNNEL_COLOR[tunnelsLive(live, tunnels)]
				: depthColor(depth);
		return [
			{
				type: 'Feature' as const,
				geometry: { type: 'LineString' as const, coordinates: arc(from, to, bow) },
				properties: {
					...properties,
					color,
					dynamic: properties['dynamic'] === true,
					...(lost ? { impact: lost } : {})
				}
			}
		];
	});
	return collection(features);
}

/** Points along a quadratic curve from one site to another, bowed out by a share of its length. */
function arc(
	from: { lon: number; lat: number },
	to: { lon: number; lat: number },
	bow: number
): LonLat[] {
	const [x1, y1, x2, y2] = [from.lon, from.lat, to.lon, to.lat];
	const [cx, cy] = [(x1 + x2) / 2 - (y2 - y1) * bow, (y1 + y2) / 2 + (x2 - x1) * bow];
	return Array.from({ length: ARC_POINTS + 1 }, (_, i) => {
		const t = i / ARC_POINTS;
		const u = 1 - t;
		return [u * u * x1 + 2 * u * t * cx + t * t * x2, u * u * y1 + 2 * u * t * cy + t * t * y2];
	});
}

/**
 * One line per connected site pair, carrying the pair's total capacity.
 *
 * @param index - Topology index.
 * @param pairs - Site pairs from {@link sitePairs}.
 * @param live - Live state, or null for structure only.
 * @param impact - Impact to show, or null.
 * @returns One line per pair; with live state, the busiest link's load;
 *   with an impact, whether its links are lost.
 */
export function sitePairFeatures(
	index: TopologyIndex,
	pairs: SitePair[],
	live: LiveIndex | null = null,
	impact: Impact | null = null,
	drift: Set<string> | null = null
): FeatureCollection<LineString> {
	const coords = (code: string): LonLat => {
		const site = index.sites.get(code);
		return site ? [site.lon, site.lat] : [0, 0];
	};
	return collection(
		pairs.map((pair) => ({
			type: 'Feature',
			geometry: { type: 'LineString', coordinates: [coords(pair.a), coords(pair.b)] },
			properties: {
				key: pair.key,
				links: pair.linkIds.length,
				capacity: pair.capacityMbps,
				...(live ? bundleProperties(index, live, pair.linkIds) : {}),
				...(impact
					? lostProperty(
							impact,
							pair.linkIds.flatMap((id) => index.links.get(id) ?? [])
						)
					: {}),
				...(drift && pair.linkIds.some((id) => drift.has(id)) ? { drift: true } : {})
			}
		}))
	);
}

/**
 * Device points at their ring positions.
 *
 * @param index - Topology index.
 * @param positions - From {@link devicePositions}.
 * @param live - Live state, or null for structure only.
 * @param impact - Impact to show, or null.
 * @returns One point per device; with live state, its health and glyph;
 *   with an impact, how it is affected, and that glyph instead.
 */
export function deviceFeatures(
	index: TopologyIndex,
	positions: Map<string, LonLat>,
	live: LiveIndex | null = null,
	impact: Impact | null = null
): FeatureCollection<Point> {
	const hidden = hiddenOnMap(index);
	const devices = index.topology.devices.filter((d) => !hidden.devices.has(d.name));
	return collection(
		devices.map((device) => {
			const properties: Record<string, unknown> = {
				name: device.name,
				label: shown(device.name),
				role: device.role
			};
			if (live) {
				const health = deviceHealth(live, device.name);
				properties['health'] = health;
				if (HEALTH_GLYPH[health]) properties['glyph'] = HEALTH_GLYPH[health];
			}
			if (impact) {
				const found = deviceImpact(impact, device.name);
				delete properties['glyph'];
				if (found) properties['impact'] = found;
				if (found && IMPACT_GLYPH[found]) properties['glyph'] = IMPACT_GLYPH[found];
			}
			return {
				type: 'Feature',
				geometry: { type: 'Point', coordinates: positions.get(device.name) ?? [0, 0] },
				properties
			};
		})
	);
}

/**
 * Every link as a line between its two devices' ring positions.
 *
 * @param links - Links to draw.
 * @param positions - From {@link devicePositions}.
 * @param live - Live state, or null for structure only.
 * @param impact - Impact to show, or null.
 * @param drift - Links discovery does not see as documented, while it is shown.
 * @returns One line per link; with live state, its health and load; with an
 *   impact, whether it is lost; and whether discovery disagrees about it.
 */
export function linkFeatures(
	links: Link[],
	positions: Map<string, LonLat>,
	live: LiveIndex | null = null,
	impact: Impact | null = null,
	drift: Set<string> | null = null
): FeatureCollection<LineString> {
	// A link into a transport or to an external node is a short stub out
	// from its device, each of a device's stubs at its own angle.
	const stubs = new Map<string, number>();
	const farEnd = (link: Link, from: LonLat): LonLat => {
		const device = farDevice(link);
		if (device !== null) return positions.get(device) ?? [0, 0];
		const n = stubs.get(link.a.device) ?? 0;
		stubs.set(link.a.device, n + 1);
		const angle = Math.PI / 4 + (n * Math.PI) / 3;
		return [from[0] + STUB_DEG * Math.cos(angle), from[1] + STUB_DEG * Math.sin(angle)];
	};
	return collection(
		links.map((link) => {
			const from = positions.get(link.a.device) ?? [0, 0];
			return {
				type: 'Feature',
				geometry: { type: 'LineString', coordinates: [from, farEnd(link, from)] },
				properties: {
					id: link.id,
					kind: link.kind,
					speed: link.speed_mbps,
					...(live ? liveProperties(linkLive(live, link)) : {}),
					...(impact ? lostProperty(impact, [link]) : {}),
					...(drift?.has(link.id) ? { drift: true } : {})
				}
			} as Feature<LineString>;
		})
	);
}

function bundleProperties(index: TopologyIndex, live: LiveIndex, ids: string[]) {
	const links = ids.flatMap((id) => index.links.get(id) ?? []);
	return liveProperties(bundleLive(links.map((l) => linkLive(live, l))));
}

function lostProperty(impact: Impact, links: Link[]) {
	const lost = linksImpact(impact, links);
	return lost ? { impact: lost } : {};
}

/** Health always; load only when measured, so "no data" never reads as 0%. */
function liveProperties({ health, utilPct }: { health: string; utilPct: number | null }) {
	return utilPct === null ? { health } : { health, util: utilPct };
}

/**
 * Cables discovery sees that the documentation does not have: a line
 * between the two devices, and for a neighbor not in the topology, a point
 * beyond the device it hangs off, away from the middle of its site.
 *
 * @param index - Topology index.
 * @param seen - The cables.
 * @param positions - Where each device is drawn.
 * @returns Lines and points, each naming the device it hangs off.
 */
export function seenFeatures(
	index: TopologyIndex,
	seen: SeenLink[],
	positions: Map<string, LonLat>
): FeatureCollection<LineString | Point> {
	const features: Feature<LineString | Point>[] = [];
	const hidden = hiddenOnMap(index);
	for (const s of seen) {
		const from = positions.get(s.a.device);
		if (!from || hidden.devices.has(s.a.device)) continue;
		if (s.known && hidden.devices.has(s.b.device)) continue;
		let to = s.known ? positions.get(s.b.device) : undefined;
		if (!s.known) {
			const site = index.sites.get(siteOf(index, s.a.device));
			const [dx, dy] = site ? [from[0] - site.lon, from[1] - site.lat] : [0, 0];
			// Beyond the device on its ring; a device in the middle gets a nudge east.
			to = dx || dy ? [from[0] + 0.8 * dx, from[1] + 0.8 * dy] : [from[0] + 0.0005, from[1]];
			features.push({
				type: 'Feature',
				geometry: { type: 'Point', coordinates: to },
				properties: { id: `${s.id}:point`, device: s.a.device, label: s.b.device }
			});
		}
		if (!to) continue;
		features.push({
			type: 'Feature',
			geometry: { type: 'LineString', coordinates: [from, to] },
			properties: { id: s.id, device: s.a.device }
		});
	}
	return { type: 'FeatureCollection', features };
}

/** How far a resource moves off a spot already taken, as a share of the span of all sites. */
const RESOURCE_STEP = 0.03;

/**
 * Where to draw each resource: in the middle of its members' sites. A spot
 * a site or a resource placed before already takes moves it north, a step
 * at a time, so a resource at one site sits just above it and none hides
 * another.
 *
 * @param index - Topology index.
 * @returns Longitude/latitude per resource name; none for a resource at no site.
 */
export function resourcePositions(index: TopologyIndex): Map<string, LonLat> {
	const { sites } = index.topology;
	const lons = sites.map((s) => s.lon);
	const lats = sites.map((s) => s.lat);
	const span = Math.max(
		Math.max(...lons) - Math.min(...lons),
		Math.max(...lats) - Math.min(...lats)
	);
	const step = RESOURCE_STEP * (span || 1);
	const taken: LonLat[] = sites.map((s) => [s.lon, s.lat]);
	const positions = new Map<string, LonLat>();
	for (const { name } of index.topology.resources) {
		const at = resourceSites(index, name).flatMap((code) => index.sites.get(code) ?? []);
		if (at.length === 0) continue;
		const lon = at.reduce((sum, s) => sum + s.lon, 0) / at.length;
		let lat = at.reduce((sum, s) => sum + s.lat, 0) / at.length;
		while (taken.some(([x, y]) => Math.hypot(x - lon, y - lat) < 0.75 * step)) lat += step;
		taken.push([lon, lat]);
		positions.set(name, [lon, lat]);
	}
	return positions;
}

/**
 * Resources as a point each, with a leader line from it to each of its
 * members' sites.
 *
 * @param index - Topology index.
 * @param positions - From {@link resourcePositions}.
 * @param report - Status, while live state is shown; or null.
 * @returns Points named for their resource, and with a report, its status
 *   and glyph; lines naming their resource and site.
 */
export function resourceFeatures(
	index: TopologyIndex,
	positions: Map<string, LonLat>,
	report: StatusReport | null = null
): FeatureCollection<Point | LineString> {
	const features: Feature<Point | LineString>[] = [];
	const hidden = hiddenOnMap(index);
	for (const [name, at] of positions) {
		if (hidden.resources.has(name)) continue;
		for (const code of resourceSites(index, name)) {
			const site = index.sites.get(code);
			if (!site || hidden.sites.has(code)) continue;
			features.push({
				type: 'Feature',
				geometry: { type: 'LineString', coordinates: [at, [site.lon, site.lat]] },
				properties: { id: `${name}|${code}`, resource: name, site: code }
			});
		}
		const properties: Record<string, unknown> = { id: name, name };
		const status = resourceStatus(report, name)?.status;
		if (status) properties['status'] = status;
		if (status && STATUS_GLYPH[status]) properties['glyph'] = STATUS_GLYPH[status];
		features.push({ type: 'Feature', geometry: { type: 'Point', coordinates: at }, properties });
	}
	return collection(features);
}
