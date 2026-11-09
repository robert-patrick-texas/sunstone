/**
 * The logical view's graph: the named networks shown, without geography.
 *
 * Sites are boxes, or, expanded, the devices in the networks shown. A
 * transport, a fabric, and an external node each are a node of their own,
 * with an abstract place rather than a geographic one. A network's links
 * between sites, and into transports and to external nodes, are drawn as
 * they are; its tunnels as dashed edges between their ends; a fabric as a
 * node its members join, a hub's way in marked; with live state, tunnels
 * spokes have built to each other now as thinner dashed edges between the
 * spokes. Networks under the ones
 * shown are drawn faintly, only at the sites of the networks shown: choosing
 * a tenant's network brings forward the places of the network it rides.
 * With no network chosen, every network is shown.
 * Edges of different networks between the same nodes stay apart.
 * A resource with any member drawn is a node of its own too, with a dotted
 * edge to each member drawn. What is hidden from the map is left out.
 */
import {
	beyondNode,
	deviceNode,
	frameNode,
	siteBoxNode,
	siteNodeId,
	type GraphEdge,
	type GraphNode
} from '../graph/model.ts';
import type { ResourceStatus } from '../api/status.ts';
import { drawnLinks } from '../graph/drawn.ts';
import { beneath, fabricTunnels, layersOf, type Slice } from '../layers.ts';
import { hiddenOnMap } from '../overrides.svelte.ts';
import { membersOf } from '../resources.ts';
import { STATUS_COLOR, STATUS_GLYPH } from '../status.ts';
import { COLOR, depthColor } from '../theme.ts';
import { deviceEnds, isDeviceEnd, nodeKey, siteOf, type TopologyIndex } from '../topology.ts';

export interface LogicalGraph {
	nodes: GraphNode[];
	edges: GraphEdge[];
	/** Networks drawn in full. */
	shown: string[];
	/** Networks under those, drawn faintly. */
	under: string[];
}

const FABRIC_W = 120;
const FABRIC_H = 56;
const RESOURCE_W = 30;
const RESOURCE_H = 26;

/** A tunnel spokes of a fabric built to each other on demand, `FABRIC:a~b`, and its network. */
export interface BuiltTunnel {
	tunnel: string;
	network: string;
}

/** A resource's status, while live state is shown. */
export type ResourceState = Pick<ResourceStatus, 'name' | 'status'>;

/**
 * Build the logical view's graph.
 *
 * @param index - Topology index.
 * @param chosen - Networks to show; none for every one.
 * @param expanded - Sites to show device by device.
 * @param withUnder - Also draw, faintly, what the networks shown ride.
 * @param built - Spoke-to-spoke tunnels up now, drawn for the networks shown.
 * @param states - Resources' status, to color them by; none for neutral.
 * @returns Nodes and edges, and which networks are shown and under them.
 */
export function logicalGraph(
	index: TopologyIndex,
	chosen: string[],
	expanded: ReadonlySet<string>,
	withUnder = true,
	built: BuiltTunnel[] = [],
	states: ResourceState[] = []
): LogicalGraph {
	const layers = layersOf(index);
	const hidden = hiddenOnMap(index);
	const drawable = new Set(drawnLinks(index).map((l) => l.id));
	const shown = chosen.length
		? chosen.filter((n) => layers.slices.has(n))
		: [...layers.slices.keys()];
	const under = chosen.length && withUnder ? [...beneath(layers, shown)] : [];
	const nodeOf = (device: string) => {
		const site = siteOf(index, device);
		return expanded.has(site) ? device : siteNodeId(site);
	};
	const edges = new Map<string, GraphEdge>();
	const used = new Set<string>();
	/** Nodes an edge of a network shown in full reaches. */
	const full = new Set<string>();
	const devices = new Set<string>();
	const add = (
		slice: Slice,
		faint: boolean,
		kind: GraphEdge['kind'],
		[u, v]: [string, string],
		more: Partial<GraphEdge>
	) => {
		if (u === v) return;
		const [source, target] = u < v ? [u, v] : [v, u];
		// Tunnels built on demand are an edge of their own, apart from the fixed ones.
		const id = `${slice.name}|${kind}|${source}~${target}${more.dynamic ? '|on demand' : ''}`;
		const edge = edges.get(id) ?? {
			id,
			source,
			target,
			linkIds: [],
			kind,
			capacityMbps: 0,
			sourceLabel: '',
			targetLabel: '',
			network: slice.name,
			color: depthColor(slice.depth),
			...(faint ? { beneath: true } : {}),
			...(more.dynamic ? { dynamic: true } : {})
		};
		edge.linkIds.push(...(more.linkIds ?? []));
		edge.capacityMbps += more.capacityMbps ?? 0;
		if (more.tunnels) edge.tunnels = [...(edge.tunnels ?? []), ...more.tunnels];
		if (more.fabric) edge.fabric = more.fabric;
		if (more.label && !edge.label) edge.label = more.label;
		edges.set(id, edge);
		used.add(u).add(v);
		if (!faint) full.add(u).add(v);
	};

	// What the networks shown ride is drawn only at their own sites: the
	// places they bring forward, not the whole of the network under them.
	const places = new Set(shown.flatMap((n) => [...(layers.slices.get(n)?.sites ?? [])]));
	for (const [names, faint] of [
		[under, true],
		[shown, false]
	] as const) {
		const here = (device: string) =>
			!hidden.devices.has(device) && (!faint || places.has(siteOf(index, device)));
		for (const name of names) {
			const slice = layers.slices.get(name);
			if (!slice) continue;
			for (const id of slice.links) {
				const link = index.links.get(id);
				if (!link || !drawable.has(id)) continue;
				const ends = deviceEnds(link).map((e) => e.device);
				if (!ends.every(here)) continue;
				const far = isDeviceEnd(link.b) ? nodeOf(link.b.device) : nodeKey(link.b);
				for (const d of ends) devices.add(d);
				add(slice, faint, link.kind, [nodeOf(link.a.device), far], {
					linkIds: [id],
					capacityMbps: link.speed_mbps
				});
			}
			for (const t of slice.tunnels) {
				const far = 'device' in t.b ? t.b.device : null;
				if (!here(t.a.device) || (far !== null && !here(far))) continue;
				const gone = 'external' in t.b && hidden.externals.has(t.b.external);
				if (gone || hidden.tunnels.has(t.name)) continue;
				devices.add(t.a.device);
				if (far !== null) devices.add(far);
				const target = 'device' in t.b ? nodeOf(t.b.device) : nodeKey({ external: t.b.external });
				add(slice, faint, 'tunnel', [nodeOf(t.a.device), target], {
					tunnels: [t.name],
					label: t.name
				});
			}
			for (const f of slice.fabrics) {
				if (hidden.fabrics.has(f.name)) continue;
				const node = `fabric:${f.name}`;
				// Each member's way in stands for the fabric's tunnels it ends.
				const ends = new Map<string, string[]>();
				for (const { a, b } of fabricTunnels(f)) {
					const id = `${f.name}:${a.device}~${b.device}`;
					for (const d of [a.device, b.device]) ends.set(d, [...(ends.get(d) ?? []), id]);
				}
				for (const m of f.members) {
					if (!here(m.device)) continue;
					devices.add(m.device);
					add(slice, faint, 'fabric', [nodeOf(m.device), node], {
						fabric: f.name,
						tunnels: ends.get(m.device) ?? [],
						...(m.role === 'hub' ? { label: 'hub' } : {})
					});
				}
			}
		}
	}
	for (const { tunnel, network } of built) {
		const slice = layers.slices.get(network);
		if (!slice || !shown.includes(network)) continue;
		const colon = tunnel.indexOf(':');
		const fabric = tunnel.slice(0, colon);
		const [a, b] = tunnel.slice(colon + 1).split('~');
		if (!a || !b || !index.devices.has(a) || !index.devices.has(b)) continue;
		if (hidden.devices.has(a) || hidden.devices.has(b) || hidden.fabrics.has(fabric)) continue;
		devices.add(a).add(b);
		add(slice, false, 'tunnel', [nodeOf(a), nodeOf(b)], {
			tunnels: [tunnel],
			fabric,
			dynamic: true
		});
	}
	// Services are shown reached across the transports drawn in full.
	for (const e of index.topology.externals) {
		if (hidden.externals.has(e.name)) continue;
		for (const t of e.reached_over) {
			const cloud = nodeKey({ transport: t });
			if (!full.has(cloud)) continue;
			const key = nodeKey({ external: e.name });
			const id = `reach|${key}~${cloud}`;
			edges.set(id, {
				id,
				source: key,
				target: cloud,
				linkIds: [],
				kind: 'reach',
				capacityMbps: 0,
				sourceLabel: '',
				targetLabel: ''
			});
			used.add(key);
		}
	}

	const nodes: GraphNode[] = [];
	const sites = new Set([...devices].map((d) => siteOf(index, d)));
	for (const { code } of index.topology.sites) {
		if (!sites.has(code)) continue;
		if (!expanded.has(code)) {
			if (used.has(siteNodeId(code))) nodes.push(siteBoxNode(index, code));
			continue;
		}
		nodes.push(frameNode(index, code));
		for (const device of index.devicesBySite.get(code) ?? []) {
			if (devices.has(device.name)) nodes.push(deviceNode(device, true));
		}
	}
	for (const id of used) {
		if (id.startsWith('fabric:')) {
			const fabric = index.fabrics.get(id.slice(7));
			const depth = layers.slices.get(fabric?.network ?? '')?.depth ?? 0;
			nodes.push({
				id,
				kind: 'fabric',
				label: id.slice(7),
				site: '',
				w: FABRIC_W,
				h: FABRIC_H,
				tint: depthColor(depth)
			});
			continue;
		}
		const beyond = beyondNode(index, id);
		if (beyond) nodes.push(beyond);
	}
	const drawn = new Set(nodes.map((n) => n.id));
	const kept = [...edges.values()].filter((e) => drawn.has(e.source) && drawn.has(e.target));
	const resources = resourceParts(index, kept, drawn, nodeOf, states);
	return {
		nodes: [...nodes, ...resources.nodes],
		edges: [...kept, ...resources.edges],
		shown,
		under
	};
}

/**
 * The resources with any member drawn, inner resources' included: a node
 * each, and a dotted edge from it to each member drawn: a circuit's devices
 * and a tunnel's own ends (or their collapsed sites), a fabric's node, and
 * an inner resource's node.
 */
function resourceParts(
	index: TopologyIndex,
	edges: GraphEdge[],
	drawn: Set<string>,
	nodeOf: (device: string) => string,
	states: ResourceState[]
): { nodes: GraphNode[]; edges: GraphEdge[] } {
	const hidden = hiddenOnMap(index);
	const links = new Set(edges.flatMap((e) => e.linkIds));
	const tunnels = new Set(edges.flatMap((e) => e.tunnels ?? []));
	// The drawn nodes each resource's own members are at.
	const at = new Map<string, Set<string>>();
	for (const r of index.topology.resources) {
		const found = new Set<string>();
		for (const m of membersOf(index, r)) {
			if (m.kind === 'circuit' && m.link && links.has(m.link.id)) {
				for (const e of deviceEnds(m.link)) found.add(nodeOf(e.device));
			} else if (m.kind === 'tunnel' && tunnels.has(m.name)) {
				const t = index.tunnels.get(m.name);
				if (t) found.add(nodeOf(t.a.device));
				if (t && 'device' in t.b) found.add(nodeOf(t.b.device));
			} else if (m.kind === 'fabric') {
				found.add(`fabric:${m.name}`);
			}
		}
		at.set(r.name, new Set([...found].filter((n) => drawn.has(n))));
	}
	// Shown when anything inside is drawn and it is not hidden; the topology has
	// no resource inside itself.
	const shows = (name: string): boolean =>
		!hidden.resources.has(name) &&
		((at.get(name)?.size ?? 0) > 0 || (index.resources.get(name)?.resources ?? []).some(shows));
	const nodes: GraphNode[] = [];
	const members: GraphEdge[] = [];
	for (const r of index.topology.resources) {
		if (!shows(r.name)) continue;
		const id = `resource:${r.name}`;
		const status = states.find((s) => s.name === r.name)?.status;
		const glyph = status ? STATUS_GLYPH[status] : '';
		nodes.push({
			id,
			kind: 'resource',
			label: glyph ? `${glyph} ${r.name}` : r.name,
			site: '',
			w: RESOURCE_W,
			h: RESOURCE_H,
			tint: status ? STATUS_COLOR[status] : COLOR.muted
		});
		const inner = r.resources.filter(shows).map((n) => `resource:${n}`);
		for (const target of [...(at.get(r.name) ?? []), ...inner]) {
			members.push({
				id: `member|${id}~${target}`,
				source: id,
				target,
				linkIds: [],
				kind: 'member',
				capacityMbps: 0,
				sourceLabel: '',
				targetLabel: ''
			});
		}
	}
	return { nodes, edges: members };
}
