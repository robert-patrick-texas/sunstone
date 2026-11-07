/**
 * Nodes and edges shared by the graph views (hierarchy, topology).
 *
 * A node is a device, a collapsed site drawn as one box, the frame of an
 * expanded site that its devices sit inside, a transport (the Internet, a
 * carrier's private WAN) drawn as a cloud, or an external node someone else
 * runs. Links between the same two
 * drawn nodes are merged into one edge. Each end is labeled with its
 * interface, or with the LAG and member count for a bundle, so the drawing
 * keeps interface-level detail.
 */
import type { Device, External, Link, Role, Transport } from '../api/topology.ts';
import { isDeviceEnd, nodeKey, shortInterface, type TopologyIndex } from '../topology.ts';

export const SITE_W = 150;
export const SITE_H = 54;

export interface GraphNode {
	/**
	 * Device name, {@link siteNodeId} for a site box or frame, or
	 * `transport:NAME` or `external:NAME` for those.
	 */
	id: string;
	kind: 'device' | 'site' | 'frame' | 'transport' | 'external' | 'fabric';
	label: string;
	/** The site, or '' for a transport or external node. */
	site: string;
	/** What an external node is: a service, a partner's, or a tenant's. */
	externalKind?: External['kind'];
	/** A fabric's color, from how deep its network sits. */
	tint?: string;
	role?: Role;
	parent?: string;
	/** Size of site boxes and frames; device nodes have a fixed size. */
	w?: number;
	h?: number;
	/** Hops from the center of a neighborhood; 0 for the center itself. */
	hop?: number;
	/** Placement, when the view computes it rather than a Cytoscape layout. */
	x?: number;
	y?: number;
}

export interface GraphEdge {
	id: string;
	source: string;
	target: string;
	linkIds: string[];
	/**
	 * A cable or circuit, LAN or WAN; or, in the logical view, tunnels, a
	 * fabric member's way into its fabric, or a service reached across a transport.
	 */
	kind: 'lan' | 'wan' | 'tunnel' | 'fabric' | 'reach';
	capacityMbps: number;
	sourceLabel: string;
	targetLabel: string;
	/** In the logical view: the named network it is part of. */
	network?: string;
	/** Its network's color. */
	color?: string;
	/** Part of a network under the ones shown, drawn faintly. */
	beneath?: boolean;
	/** Tunnels it stands for, by name. */
	tunnels?: string[];
	/** The fabric it joins. */
	fabric?: string;
	/** Drawn along the edge when zoomed in. */
	label?: string;
}

/**
 * Node id of a site's box (collapsed) or frame (expanded).
 *
 * @param code - Site code.
 * @returns The node id.
 */
export function siteNodeId(code: string): string {
	return `site:${code}`;
}

/**
 * A collapsed site: one box labeled with its code, name, and device count.
 *
 * @param index - Topology index.
 * @param code - Site code.
 * @returns The node.
 */
export function siteBoxNode(index: TopologyIndex, code: string): GraphNode {
	const name = index.sites.get(code)?.name ?? code;
	const count = index.devicesBySite.get(code)?.length ?? 0;
	const label = `${code}\n${name} · ${count}`;
	return { id: siteNodeId(code), kind: 'site', label, site: code, w: SITE_W, h: SITE_H };
}

/**
 * The frame an expanded site's devices sit inside.
 *
 * @param index - Topology index.
 * @param code - Site code.
 * @returns The node.
 */
export function frameNode(index: TopologyIndex, code: string): GraphNode {
	const name = index.sites.get(code)?.name ?? code;
	return { id: siteNodeId(code), kind: 'frame', label: `${code} · ${name}`, site: code };
}

/**
 * A device.
 *
 * @param device - The device.
 * @param framed - Draw it inside its site's frame.
 * @returns The node.
 */
export function deviceNode(device: Device, framed: boolean): GraphNode {
	return {
		id: device.name,
		kind: 'device',
		label: device.name,
		site: device.site,
		role: device.role,
		...(framed ? { parent: siteNodeId(device.site) } : {})
	};
}

/**
 * A transport, drawn as a cloud.
 *
 * @param transport - The transport.
 * @returns The node.
 */
export function transportNode(transport: Transport): GraphNode {
	return {
		id: nodeKey({ transport: transport.name }),
		kind: 'transport',
		label: transport.name,
		site: '',
		w: 110,
		h: 50
	};
}

/**
 * An external node: a service, a partner's device, or a tenant's.
 *
 * @param external - The node.
 * @returns The node.
 */
export function externalNode(external: External): GraphNode {
	return {
		id: nodeKey({ external: external.name }),
		kind: 'external',
		label: external.name,
		site: '',
		externalKind: external.kind,
		w: 96,
		h: 22
	};
}

/**
 * The node for a transport or external node, by its key.
 *
 * @param index - Topology index.
 * @param key - `transport:NAME` or `external:NAME`.
 * @returns The node, or null for any other key (a site code, say).
 */
export function beyondNode(index: TopologyIndex, key: string): GraphNode | null {
	const transport = key.startsWith('transport:') && index.transports.get(key.slice(10));
	if (transport) return transportNode(transport);
	const external = key.startsWith('external:') && index.externals.get(key.slice(9));
	return external ? externalNode(external) : null;
}

/**
 * Merge links into one edge per pair of drawn nodes.
 *
 * @param links - Links to consider.
 * @param nodeOf - The drawn node a device is part of: itself, its collapsed
 *   site, or null when the device is not drawn (its links are left out).
 *   A transport or external node at a link's end is drawn as itself, by
 *   its `transport:` or `external:` key.
 * @returns One edge per connected pair; links inside one node are dropped.
 */
export function mergeLinks(links: Link[], nodeOf: (device: string) => string | null): GraphEdge[] {
	const groups = new Map<string, { source: string; target: string; links: Link[] }>();
	for (const link of links) {
		const u = nodeOf(link.a.device);
		const v = isDeviceEnd(link.b) ? nodeOf(link.b.device) : nodeKey(link.b);
		if (u === null || v === null || u === v) continue;
		const [source, target] = u < v ? [u, v] : [v, u];
		const key = `${source}~${target}`;
		const group = groups.get(key) ?? { source, target, links: [] };
		group.links.push(link);
		groups.set(key, group);
	}
	return [...groups].map(([id, { source, target, links }]) => ({
		id,
		source,
		target,
		linkIds: links.map((l) => l.id),
		kind: links.some((l) => l.kind === 'wan') ? 'wan' : 'lan',
		capacityMbps: links.reduce((s, l) => s + l.speed_mbps, 0),
		sourceLabel: endLabel(links, source),
		targetLabel: endLabel(links, target)
	}));
}

/** Label for one end of a merged edge: the interface, or the LAG and member count. */
function endLabel(links: Link[], node: string): string {
	const ends = links.map((l) =>
		l.a.device === node ? l.a : isDeviceEnd(l.b) && l.b.device === node ? l.b : null
	);
	if (ends.some((e) => e === null)) return ''; // this end is a collapsed site, not a device
	const [first] = ends;
	if (ends.length === 1 && first) return shortInterface(first.interface);
	const lags = new Set(ends.map((e) => e?.lag));
	const [lag] = lags;
	return lags.size === 1 && lag ? `${shortInterface(lag)} ×${ends.length}` : `×${ends.length}`;
}

/** A cable discovery sees that the documentation does not have as it is. */
export interface SeenEnds {
	id: string;
	a: { device: string; interface: string };
	b: { device: string; interface: string };
	known: boolean;
	finding: string;
}

/** A Cytoscape element for something seen but not documented. */
export interface GhostElement {
	group: 'nodes' | 'edges';
	data: Record<string, unknown>;
	position?: { x: number; y: number };
	classes: string;
}

/** How far from its device a neighbor not in the topology is drawn. */
const GHOST_OFFSET = { x: 70, y: -45 };

/**
 * Elements for cables discovery sees that the documentation does not have:
 * an edge between the nodes their devices are drawn in, and for a neighbor
 * not in the topology, a node of its own beside the device it hangs off.
 *
 * @param seen - The cables.
 * @param nodeOf - The node a device is drawn in (its own, or its collapsed
 *   site's), or null if it is not drawn.
 * @param positionOf - Where a node is.
 * @returns Nodes and edges marked `ghost`; a cable inside one collapsed
 *   site, or to a device not drawn, is left out.
 */
export function ghostElements(
	seen: SeenEnds[],
	nodeOf: (device: string) => string | null,
	positionOf: (node: string) => { x: number; y: number }
): GhostElement[] {
	const elements: GhostElement[] = [];
	const added = new Set<string>();
	for (const s of seen) {
		const source = nodeOf(s.a.device);
		if (!source || added.has(s.id)) continue;
		const target = s.known ? nodeOf(s.b.device) : `ghost:${s.b.device}@${s.a.device}`;
		if (!target || target === source) continue;
		if (!s.known && !added.has(target)) {
			const at = positionOf(source);
			elements.push({
				group: 'nodes',
				data: { id: target, kind: 'ghost', label: s.b.device, device: s.a.device },
				position: { x: at.x + GHOST_OFFSET.x, y: at.y + GHOST_OFFSET.y },
				classes: 'ghost'
			});
			added.add(target);
		}
		elements.push({
			group: 'edges',
			data: {
				id: s.id,
				source,
				target,
				kind: 'ghost',
				linkIds: [],
				device: s.a.device,
				finding: s.finding,
				sourceLabel: shortInterface(s.a.interface),
				targetLabel: shortInterface(s.b.interface)
			},
			classes: 'ghost'
		});
		added.add(s.id);
	}
	return elements;
}
