/**
 * The logical view's graph: the named networks shown, without geography.
 *
 * Sites are boxes, or, expanded, the devices in the networks shown. A
 * transport, a fabric, and an external node each are a node of their own,
 * with an abstract place rather than a geographic one. A network's links
 * between sites, and into transports and to external nodes, are drawn as
 * they are; its tunnels as dashed edges between their ends; a fabric as a
 * node its members join, a hub's way in marked. Networks under the ones
 * shown are drawn faintly, only at the sites of the networks shown: choosing
 * a tenant's network brings forward the places of the network it rides.
 * With no network chosen, every network is shown.
 * Edges of different networks between the same nodes stay apart.
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
import { beneath, layersOf, type Slice } from '../layers.ts';
import { depthColor } from '../theme.ts';
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

/**
 * Build the logical view's graph.
 *
 * @param index - Topology index.
 * @param chosen - Networks to show; none for every one.
 * @param expanded - Sites to show device by device.
 * @param withUnder - Also draw, faintly, what the networks shown ride.
 * @returns Nodes and edges, and which networks are shown and under them.
 */
export function logicalGraph(
	index: TopologyIndex,
	chosen: string[],
	expanded: ReadonlySet<string>,
	withUnder = true
): LogicalGraph {
	const layers = layersOf(index);
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
		const id = `${slice.name}|${kind}|${source}~${target}`;
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
			...(faint ? { beneath: true } : {})
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
		const here = (device: string) => !faint || places.has(siteOf(index, device));
		for (const name of names) {
			const slice = layers.slices.get(name);
			if (!slice) continue;
			for (const id of slice.links) {
				const link = index.links.get(id);
				if (!link) continue;
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
				devices.add(t.a.device);
				if (far !== null) devices.add(far);
				const target = 'device' in t.b ? nodeOf(t.b.device) : nodeKey({ external: t.b.external });
				add(slice, faint, 'tunnel', [nodeOf(t.a.device), target], {
					tunnels: [t.name],
					label: t.name
				});
			}
			for (const f of slice.fabrics) {
				const node = `fabric:${f.name}`;
				for (const m of f.members) {
					if (!here(m.device)) continue;
					devices.add(m.device);
					add(slice, faint, 'fabric', [nodeOf(m.device), node], {
						fabric: f.name,
						...(m.role === 'hub' ? { label: 'hub' } : {})
					});
				}
			}
		}
	}
	// Services are shown reached across the transports drawn in full.
	for (const e of index.topology.externals) {
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
	return {
		nodes,
		edges: [...edges.values()].filter((e) => drawn.has(e.source) && drawn.has(e.target)),
		shown,
		under
	};
}
