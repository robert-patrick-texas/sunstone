/**
 * Named networks and what is layered over the links.
 *
 * A network's slice is everything that carries it: the links that say so
 * (and circuits into a transport whose network it is), its own tunnels and
 * fabrics, and the devices, sites, transports, and external nodes these
 * touch. A tenant's network over one of ours has no tunnels of its own: its
 * slice is the links to its nodes, which brings forward the places of the
 * network it rides.
 *
 * Networks stack: a tunnel or fabric rides another network, and a network
 * can say what it rides itself. A network's depth is how many networks are
 * under it: 0 for one that rides nothing (the circuits), 1 for one over
 * those, and so on.
 */
import type { Fabric, FabricMember, Link, Tunnel } from './api/topology.ts';
import type { LayerSelection } from './state.svelte.ts';
import { deviceEnds, isDeviceEnd, nodeKey, siteOf, type TopologyIndex } from './topology.ts';

export interface Slice {
	name: string;
	/** Links that carry it, by id. */
	links: Set<string>;
	tunnels: Tunnel[];
	fabrics: Fabric[];
	/** Devices with any part in it. */
	devices: Set<string>;
	/** Transports and external nodes in it, by `transport:` or `external:` key. */
	nodes: Set<string>;
	sites: Set<string>;
	/** Networks it rides directly. */
	rides: Set<string>;
	/** Networks that ride it directly. */
	riders: Set<string>;
	depth: number;
}

export interface Layers {
	slices: Map<string, Slice>;
	/** Transports each site has circuits into, by site code. */
	transportsAt: Map<string, string[]>;
	/** Named networks with a part at each site, by site code. */
	networksAt: Map<string, string[]>;
}

/** A tunnel a fabric is made of, between two of its members. */
export interface FabricTunnel {
	a: FabricMember;
	b: FabricMember;
}

/** What a layer selection stands for in the physical network. */
export interface Footprint {
	devices: Set<string>;
	links: Set<string>;
	/** Transports and external nodes, by key. */
	nodes: Set<string>;
	sites: Set<string>;
}

/**
 * The named networks a link carries.
 *
 * @param index - Topology index.
 * @param link - The link.
 * @returns Those it says, and a circuit's transport's network.
 */
export function carried(index: TopologyIndex, link: Link): string[] {
	const names = link.carries.map((c) => c.network);
	if (!isDeviceEnd(link.b) && 'transport' in link.b) {
		const own = index.transports.get(link.b.transport)?.network;
		if (own && !names.includes(own)) names.push(own);
	}
	return names;
}

/**
 * The tunnels a fabric is made of.
 *
 * @param fabric - The fabric.
 * @returns Each spoke to each hub, or every pair for a full mesh; none for a
 *   group, whose members reach each other directly. Tunnels spokes build to
 *   each other on demand are not listed: see {@link onDemand}.
 */
export function fabricTunnels(fabric: Fabric): FabricTunnel[] {
	const { members } = fabric;
	if (fabric.shape === 'group') return [];
	if (fabric.shape === 'full-mesh') {
		return members.flatMap((a, i) => members.slice(i + 1).map((b) => ({ a, b })));
	}
	const hubs = members.filter((m) => m.role === 'hub');
	return members.filter((m) => m.role === 'spoke').flatMap((a) => hubs.map((b) => ({ a, b })));
}

/**
 * How many spoke-to-spoke tunnels a fabric could build on demand.
 *
 * @param fabric - The fabric.
 * @returns For a hub-spoke-dynamic fabric, every pair of spokes; else 0.
 */
export function onDemand(fabric: Fabric): number {
	if (fabric.shape !== 'hub-spoke-dynamic') return 0;
	const spokes = fabric.members.filter((m) => m.role === 'spoke').length;
	return (spokes * (spokes - 1)) / 2;
}

const cache = new WeakMap<TopologyIndex, Layers>();

/**
 * Work out every network's slice, once per topology.
 *
 * @param index - Topology index.
 * @returns The slices, and which transports and networks each site has.
 */
export function layersOf(index: TopologyIndex): Layers {
	const known = cache.get(index);
	if (known) return known;
	const slices = new Map<string, Slice>(
		index.topology.networks.map((n) => [
			n.name,
			{
				name: n.name,
				links: new Set(),
				tunnels: [],
				fabrics: [],
				devices: new Set(),
				nodes: new Set(),
				sites: new Set(),
				rides: new Set(n.rides),
				riders: new Set(),
				depth: 0
			}
		])
	);
	const slice = (name: string) => slices.get(name);
	const transportsAt = new Map<string, string[]>();
	for (const link of index.topology.links) {
		const external = !isDeviceEnd(link.b) && 'external' in link.b ? link.b.external : null;
		const names = carried(index, link);
		// A link to a tenant's node is part of the tenant's network too.
		const own = external ? index.externals.get(external)?.network : null;
		if (own && !names.includes(own)) names.push(own);
		for (const name of names) {
			const s = slice(name);
			if (!s) continue;
			s.links.add(link.id);
			for (const e of deviceEnds(link)) s.devices.add(e.device);
			if (!isDeviceEnd(link.b)) s.nodes.add(nodeKey(link.b));
		}
		if (!isDeviceEnd(link.b) && 'transport' in link.b) {
			const site = siteOf(index, link.a.device);
			const here = transportsAt.get(site) ?? [];
			if (!here.includes(link.b.transport)) here.push(link.b.transport);
			transportsAt.set(site, here);
		}
	}
	for (const tunnel of index.topology.tunnels) {
		const s = slice(tunnel.network);
		if (!s) continue;
		s.tunnels.push(tunnel);
		s.rides.add(tunnel.rides);
		s.devices.add(tunnel.a.device);
		if ('device' in tunnel.b) s.devices.add(tunnel.b.device);
		else s.nodes.add(nodeKey({ external: tunnel.b.external }));
	}
	for (const fabric of index.topology.fabrics) {
		const s = slice(fabric.network);
		if (!s) continue;
		s.fabrics.push(fabric);
		s.rides.add(fabric.rides);
		for (const m of fabric.members) s.devices.add(m.device);
	}
	for (const t of index.topology.transports) {
		if (t.network) slice(t.network)?.nodes.add(nodeKey({ transport: t.name }));
	}
	for (const e of index.topology.externals) {
		if (e.network) slice(e.network)?.nodes.add(nodeKey({ external: e.name }));
	}
	const networksAt = new Map<string, string[]>();
	for (const s of slices.values()) {
		for (const d of s.devices) s.sites.add(siteOf(index, d));
		for (const site of s.sites) networksAt.set(site, [...(networksAt.get(site) ?? []), s.name]);
		for (const r of s.rides) slice(r)?.riders.add(s.name);
	}
	// Depth, from the bottom up; the loader has ruled out networks that ride themselves.
	const depthOf = (name: string, seen: Set<string>): number => {
		const s = slice(name);
		if (!s || seen.has(name)) return 0;
		const under = [...s.rides].map((r) => depthOf(r, new Set([...seen, name])) + 1);
		return Math.max(0, ...under);
	};
	for (const s of slices.values()) s.depth = depthOf(s.name, new Set());
	const layers = { slices, transportsAt, networksAt };
	cache.set(index, layers);
	return layers;
}

/**
 * Every network some networks ride, at any depth.
 *
 * @param layers - From {@link layersOf}.
 * @param names - The networks.
 * @returns The networks under them, not counting any of them.
 */
export function beneath(layers: Layers, names: Iterable<string>): Set<string> {
	const chosen = new Set(names);
	const found = new Set<string>();
	const stack = [...chosen];
	while (stack.length > 0) {
		const name = stack.pop() ?? '';
		for (const r of layers.slices.get(name)?.rides ?? []) {
			if (found.has(r)) continue;
			found.add(r);
			stack.push(r);
		}
	}
	for (const name of chosen) found.delete(name);
	return found;
}

/**
 * What a transport, external node, network, tunnel, fabric, or tenant
 * stands for in the physical network.
 *
 * @param index - Topology index.
 * @param selection - The selection.
 * @returns Its devices, links, transports and external nodes, and sites;
 *   empty for a name not in the topology.
 */
export function footprint(index: TopologyIndex, selection: LayerSelection): Footprint {
	const found: Footprint = {
		devices: new Set(),
		links: new Set(),
		nodes: new Set(),
		sites: new Set()
	};
	const addLinks = (key: string) => {
		for (const link of index.linksByNode.get(key) ?? []) {
			found.links.add(link.id);
			found.devices.add(link.a.device);
		}
	};
	const addSlice = (s: Slice | undefined) => {
		if (!s) return;
		for (const id of s.links) found.links.add(id);
		for (const d of s.devices) found.devices.add(d);
		for (const n of s.nodes) found.nodes.add(n);
	};
	const { id } = selection;
	if (selection.kind === 'transport' || selection.kind === 'external') {
		const key = nodeKey(selection.kind === 'transport' ? { transport: id } : { external: id });
		if (index.linksByNode.has(key) || index.transports.has(id) || index.externals.has(id)) {
			found.nodes.add(key);
		}
		addLinks(key);
		for (const t of index.topology.tunnels) {
			if ('external' in t.b && t.b.external === id) found.devices.add(t.a.device);
		}
	} else if (selection.kind === 'network') {
		addSlice(layersOf(index).slices.get(id));
	} else if (selection.kind === 'tunnel') {
		const t = index.tunnels.get(id);
		if (t) {
			found.devices.add(t.a.device);
			if ('device' in t.b) found.devices.add(t.b.device);
			else found.nodes.add(nodeKey({ external: t.b.external }));
		}
	} else if (selection.kind === 'fabric') {
		for (const m of index.fabrics.get(id)?.members ?? []) found.devices.add(m.device);
	} else {
		const layers = layersOf(index);
		for (const n of index.topology.networks) {
			if (n.tenant === id) addSlice(layers.slices.get(n.name));
		}
		for (const e of index.topology.externals) {
			if (e.tenant !== id) continue;
			const key = nodeKey({ external: e.name });
			found.nodes.add(key);
			addLinks(key);
		}
	}
	for (const d of found.devices) found.sites.add(siteOf(index, d));
	return found;
}
