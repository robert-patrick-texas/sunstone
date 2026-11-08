/**
 * What the networks chosen in the header take in, for the lists that follow
 * them (problems and events), and the regions those lists group and filter by.
 *
 * The rule is the logical view's: something belongs to the networks chosen
 * if it is part of one, or of a network beneath one at that network's sites.
 * With no network chosen, everything belongs.
 *
 * The regions are the chosen network's own, if exactly one is chosen and it
 * names some (grey-west, grey-east); otherwise the topology's, by the region
 * each site is in. Sites in none are in "No region".
 */
import { beneath, layersOf } from './layers.ts';
import { deviceEnds, siteOf, type TopologyIndex } from './topology.ts';

/** The region of sites no region names. */
export const NO_REGION = 'No region';

export interface Region {
	name: string;
	sites: Set<string>;
}

export interface Scope {
	/** The networks chosen; none for the network as a whole. */
	networks: string[];
	/** The networks beneath those, at any depth. */
	under: Set<string>;
	/** Regions with sites in scope, in the order the topology lists them, "No region" last. */
	regions: Region[];
	/**
	 * Whether any of some devices, links, or tunnels belong.
	 *
	 * @param devices - Device names.
	 * @param links - Link ids.
	 * @param tunnels - Tunnel names, or `FABRIC:a~b` for one a fabric is made of.
	 */
	has(devices: Iterable<string>, links: Iterable<string>, tunnels?: Iterable<string>): boolean;
	/** The region a site is in: one of {@link Scope.regions}, or "No region". */
	regionOf(site: string): string;
}

/**
 * Work out what some networks take in.
 *
 * @param index - Topology index.
 * @param networks - The networks chosen in the header; none for everything.
 * @returns The scope.
 */
export function scopeOf(index: TopologyIndex, networks: string[]): Scope {
	const { slices } = layersOf(index);
	const chosen = networks.filter((n) => slices.has(n));
	const under = beneath(layersOf(index), chosen);
	const places = new Set(chosen.flatMap((n) => [...(slices.get(n)?.sites ?? [])]));
	const here = (device: string) => places.has(siteOf(index, device));
	const devices = new Set<string>();
	const links = new Set<string>();
	for (const name of chosen) {
		for (const d of slices.get(name)?.devices ?? []) devices.add(d);
		for (const l of slices.get(name)?.links ?? []) links.add(l);
	}
	for (const name of under) {
		for (const d of slices.get(name)?.devices ?? []) if (here(d)) devices.add(d);
		for (const id of slices.get(name)?.links ?? []) {
			const link = index.links.get(id);
			if (link && deviceEnds(link).every((e) => here(e.device))) links.add(id);
		}
	}
	const tunnelIn = (id: string): boolean => {
		const tunnel = index.tunnels.get(id);
		const colon = id.indexOf(':');
		const network = tunnel?.network ?? index.fabrics.get(id.slice(0, colon))?.network;
		if (network === undefined) return false;
		if (chosen.includes(network)) return true;
		if (!under.has(network)) return false;
		const ends = tunnel
			? [tunnel.a.device, ...('device' in tunnel.b ? [tunnel.b.device] : [])]
			: id.slice(colon + 1).split('~');
		return ends.every(here);
	};

	const regions = regionsOf(index, chosen, places);
	const regionBySite = new Map<string, string>();
	for (const r of regions)
		for (const s of r.sites) if (!regionBySite.has(s)) regionBySite.set(s, r.name);
	return {
		networks: chosen,
		under,
		regions,
		has(ds, ls, ts = []) {
			if (chosen.length === 0) return true;
			for (const d of ds) if (devices.has(d)) return true;
			for (const l of ls) if (links.has(l)) return true;
			for (const t of ts) if (tunnelIn(t)) return true;
			return false;
		},
		regionOf: (site) => regionBySite.get(site) ?? NO_REGION
	};
}

/**
 * The regions to group by.
 *
 * @param index - Topology index.
 * @param chosen - The networks chosen, those in the topology.
 * @param places - Their sites; with none chosen, every site counts.
 * @returns The regions with sites in scope, and "No region" for the rest, if any.
 */
function regionsOf(index: TopologyIndex, chosen: string[], places: Set<string>): Region[] {
	const inScope = chosen.length ? [...places] : index.topology.sites.map((s) => s.code);
	const own = chosen.length === 1 ? index.networks.get(chosen[0] ?? '')?.regions : undefined;
	// Without regions listed, the regions are the names the sites give.
	const names = new Set(index.topology.regions.map((r) => r.name));
	for (const s of index.topology.sites) if (s.region) names.add(s.region);
	const named: Region[] =
		own && Object.keys(own).length
			? Object.entries(own).map(([name, sites]) => ({ name, sites: new Set(sites) }))
			: [...names].map((name) => ({
					name,
					sites: new Set(index.topology.sites.filter((s) => s.region === name).map((s) => s.code))
				}));
	const found = named
		.map((r) => ({ name: r.name, sites: new Set(inScope.filter((s) => r.sites.has(s))) }))
		.filter((r) => r.sites.size > 0);
	const placed = new Set(found.flatMap((r) => [...r.sites]));
	const rest = inScope.filter((s) => !placed.has(s));
	return rest.length ? [...found, { name: NO_REGION, sites: new Set(rest) }] : found;
}
