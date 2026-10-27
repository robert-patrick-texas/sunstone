/**
 * Graphs for the topology view: the whole network, one neighborhood, or the
 * shortest paths between two devices.
 * Unlike the hierarchy, positions come from a Cytoscape layout.
 */
import type { Link } from '../api/topology.ts';
import {
	deviceNode,
	frameNode,
	mergeLinks,
	siteBoxNode,
	siteNodeId,
	type GraphEdge,
	type GraphNode
} from '../graph/model.ts';
import { siteLevels } from '../hierarchy/layout.ts';
import { ROLES, siteOf, type TopologyIndex } from '../topology.ts';
import type { PathResult } from '../paths.ts';
import type { Neighborhood } from './neighborhood.ts';

export interface TopoGraph {
	nodes: GraphNode[];
	edges: GraphEdge[];
}

/**
 * The whole network: collapsed sites as boxes, expanded sites as devices.
 *
 * @param index - Topology index.
 * @param expanded - Codes of sites to show device by device.
 * @param framed - Draw expanded sites' devices inside a frame per site.
 * @returns Nodes and merged edges.
 */
export function networkGraph(
	index: TopologyIndex,
	expanded: ReadonlySet<string>,
	framed: boolean
): TopoGraph {
	const nodes: GraphNode[] = [];
	for (const { code } of index.topology.sites) {
		if (!expanded.has(code)) {
			nodes.push(siteBoxNode(index, code));
			continue;
		}
		if (framed) nodes.push(frameNode(index, code));
		for (const device of index.devicesBySite.get(code) ?? []) {
			nodes.push(deviceNode(device, framed));
		}
	}
	const nodeOf = (device: string) => {
		const site = siteOf(index, device);
		return expanded.has(site) ? device : siteNodeId(site);
	};
	return { nodes, edges: mergeLinks(index.topology.links, nodeOf) };
}

/**
 * One neighborhood: its devices and the links among them.
 *
 * @param index - Topology index.
 * @param hood - The neighborhood.
 * @param framed - Draw devices inside a frame per site.
 * @returns Nodes carrying their hop distance, and merged edges.
 */
export function neighborhoodGraph(
	index: TopologyIndex,
	hood: Neighborhood,
	framed: boolean
): TopoGraph {
	const links = [...hood.hops.keys()].flatMap((d) => index.linksByDevice.get(d) ?? []);
	return devicesGraph(index, hood.hops, new Set(links), framed);
}

/**
 * Shortest paths: the devices on them and only the path links.
 *
 * @param index - Topology index.
 * @param path - The paths.
 * @param framed - Draw devices inside a frame per site.
 * @returns Nodes carrying their hops from the start, and merged edges.
 */
export function pathGraph(index: TopologyIndex, path: PathResult, framed: boolean): TopoGraph {
	const links = [...path.links].flatMap((id) => index.links.get(id) ?? []);
	return devicesGraph(index, path.devices, new Set(links), framed);
}

/** Devices with their hop distances, and those of `links` that join two of them. */
function devicesGraph(
	index: TopologyIndex,
	hops: Map<string, number>,
	links: Set<Link>,
	framed: boolean
): TopoGraph {
	const nodes: GraphNode[] = [];
	for (const [name, hop] of hops) {
		const device = index.devices.get(name);
		if (device) nodes.push({ ...deviceNode(device, framed), hop });
	}
	if (framed) {
		const sites = new Set(nodes.map((n) => n.site));
		nodes.unshift(...[...sites].map((code) => frameNode(index, code)));
	}
	const nodeOf = (device: string) => (hops.has(device) ? device : null);
	return { nodes, edges: mergeLinks([...links], nodeOf) };
}

/**
 * Where a radial layout starts: a neighborhood's center, or else the top
 * level of sites (as boxes, or the topmost tier of their devices).
 *
 * @param index - Topology index.
 * @param nodes - Nodes being laid out.
 * @returns Ids of the root nodes.
 */
export function radialRoots(index: TopologyIndex, nodes: GraphNode[]): string[] {
	const centers = nodes.filter((n) => n.hop === 0);
	if (centers.length > 0) return centers.map((n) => n.id);
	const top = new Set(siteLevels(index)[0] ?? []);
	const topRole = (site: string) =>
		ROLES.find((role) => index.devicesBySite.get(site)?.some((d) => d.role === role));
	return nodes
		.filter((n) => top.has(n.site))
		.filter((n) => n.kind === 'site' || (n.kind === 'device' && n.role === topRole(n.site)))
		.map((n) => n.id);
}
