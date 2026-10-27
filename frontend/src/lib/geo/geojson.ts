/**
 * GeoJSON for the geographic view.
 *
 * Zoomed out, each site is one point and the links between two sites are
 * one line. Zoomed in, a site's devices are drawn on rings around the site's
 * coordinates, upper tiers on inner rings. The rings are a drawing aid, not
 * real device locations: sources give coordinates per site, not per device.
 *
 * Given live state, features also carry `health` (and `util`, `glyph`, or a
 * fuller site `label`) for the map's live styling; without it they carry
 * none, and the map draws structure only. Given an impact to show, affected
 * features carry `impact` (and a `glyph` and site `label` to match), and
 * unaffected ones carry neither.
 */
import type { Feature, FeatureCollection, LineString, Point } from 'geojson';
import type { SeenLink } from '../api/discovery.ts';
import type { Link } from '../api/topology.ts';
import { deviceImpact, linksImpact, worstImpact, type Impact } from '../impact.ts';
import { bundleLive, deviceHealth, groupHealth, linkLive, type LiveIndex } from '../live.ts';
import { HEALTH_GLYPH, IMPACT_GLYPH } from '../theme.ts';
import { ROLES, siteOf, type TopologyIndex } from '../topology.ts';

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
	for (const link of index.topology.links) {
		const a = siteOf(index, link.a.device);
		const b = siteOf(index, link.b.device);
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
	return collection(
		index.topology.sites.map((site) => {
			const devices = (index.devicesBySite.get(site.code) ?? []).map((d) => d.name);
			const properties: Record<string, unknown> = {
				code: site.code,
				name: site.name,
				devices: devices.length
			};
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
	return collection(
		index.topology.devices.map((device) => {
			const properties: Record<string, unknown> = { name: device.name, role: device.role };
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
	return collection(
		links.map((link) => ({
			type: 'Feature',
			geometry: {
				type: 'LineString',
				coordinates: [
					positions.get(link.a.device) ?? [0, 0],
					positions.get(link.b.device) ?? [0, 0]
				]
			},
			properties: {
				id: link.id,
				kind: link.kind,
				speed: link.speed_mbps,
				...(live ? liveProperties(linkLive(live, link)) : {}),
				...(impact ? lostProperty(impact, [link]) : {}),
				...(drift?.has(link.id) ? { drift: true } : {})
			}
		}))
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
	for (const s of seen) {
		const from = positions.get(s.a.device);
		if (!from) continue;
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
