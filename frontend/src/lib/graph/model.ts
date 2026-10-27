/**
 * Nodes and edges shared by the graph views (hierarchy, topology).
 *
 * A node is a device, a collapsed site drawn as one box, or the frame of an
 * expanded site that its devices sit inside. Links between the same two
 * drawn nodes are merged into one edge. Each end is labeled with its
 * interface, or with the LAG and member count for a bundle, so the drawing
 * keeps interface-level detail.
 */
import type { Device, Link, Role } from '../api/topology.ts';
import { shortInterface, type TopologyIndex } from '../topology.ts';

export const SITE_W = 150;
export const SITE_H = 54;

export interface GraphNode {
	/** Device name, or {@link siteNodeId} for a site box or frame. */
	id: string;
	kind: 'device' | 'site' | 'frame';
	label: string;
	site: string;
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
	kind: 'lan' | 'wan';
	capacityMbps: number;
	sourceLabel: string;
	targetLabel: string;
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
 * Merge links into one edge per pair of drawn nodes.
 *
 * @param links - Links to consider.
 * @param nodeOf - The drawn node a device is part of: itself, its collapsed
 *   site, or null when the device is not drawn (its links are left out).
 * @returns One edge per connected pair; links inside one node are dropped.
 */
export function mergeLinks(links: Link[], nodeOf: (device: string) => string | null): GraphEdge[] {
	const groups = new Map<string, { source: string; target: string; links: Link[] }>();
	for (const link of links) {
		const u = nodeOf(link.a.device);
		const v = nodeOf(link.b.device);
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
	const ends = links.map((l) => (l.a.device === node ? l.a : l.b.device === node ? l.b : null));
	if (ends.some((e) => e === null)) return ''; // this end is a collapsed site, not a device
	const [first] = ends;
	if (ends.length === 1 && first) return shortInterface(first.interface);
	const lags = new Set(ends.map((e) => e?.lag));
	const [lag] = lags;
	return lags.size === 1 && lag ? `${shortInterface(lag)} ×${ends.length}` : `×${ends.length}`;
}
