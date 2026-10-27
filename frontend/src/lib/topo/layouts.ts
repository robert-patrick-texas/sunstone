/**
 * Automatic layouts for the topology view.
 *
 * fcose's cost climbs steeply with size. On the 3,000-device sample, one pass
 * over the whole expanded network takes 18 s or more at default quality, and
 * its fast draft pass leaves sites piled on top of each other. Large graphs
 * are therefore laid out site by site: each expanded site's devices on their
 * own, then the sites, sized to fit their devices, among each other.
 *
 * Layouts work on plain graph data in a headless Cytoscape, so they can run
 * in a Web Worker (`layout.worker.ts`) and leave the page responsive.
 * Without a renderer, label sizes are unknown, so device nodes are given a
 * box that leaves room for their label.
 */
import cytoscape, {
	type BreadthFirstLayoutOptions,
	type EdgeSingular,
	type LayoutOptions,
	type NodeSingular,
	type Position
} from 'cytoscape';
import fcose from 'cytoscape-fcose';
import { SITE_H, SITE_W, type GraphEdge, type GraphNode } from '../graph/model.ts';
import type { TopoGraph } from './graph.ts';

cytoscape.use(fcose);

/** Above this many nodes, force-directed layouts go site by site. */
export const SITEWISE_ABOVE = 800;
/** Refining the current picture costs about three times a fresh layout, so only small graphs get it. */
export const REFINE_UP_TO = 300;

// A device node plus its label, and the room a site frame adds around its devices.
const DEVICE_W = 50;
const DEVICE_H = 30;
const FRAME_ROOM = 60;

interface Spacing {
	idealEdgeLength: number;
	nodeRepulsion: number;
	nodeSeparation: number;
}
const DEVICE_SPACING: Spacing = { idealEdgeLength: 60, nodeRepulsion: 4500, nodeSeparation: 50 };
// Sites are big boxes, nearly all linked to the same hubs; with device-sized
// spacing they pile up. fcose spreads them out, and removeOverlaps finishes
// the job, since fcose does not fully separate boxes this large.
const SITE_SPACING: Spacing = { idealEdgeLength: 400, nodeRepulsion: 200_000, nodeSeparation: 150 };
const SITE_GAP = 40;

const touchesSiteBox = (e: EdgeSingular) =>
	e.source().data('kind') === 'site' || e.target().data('kind') === 'site';

const FORCE = {
	name: 'fcose',
	animate: false,
	fit: false,
	// Collapsed site boxes get site spacing (on the 3,000-device sample this
	// took overlapping boxes from 102 pairs to 2).
	idealEdgeLength: (e: EdgeSingular) => (touchesSiteBox(e) ? SITE_SPACING.idealEdgeLength : 90),
	nodeRepulsion: (n: NodeSingular) =>
		n.data('kind') === 'site' ? SITE_SPACING.nodeRepulsion : 9000,
	nodeSeparation: 90,
	packComponents: true
};

/** What to lay out, and how: everything a layout needs, as plain data. */
export interface LayoutRequest {
	nodes: GraphNode[];
	edges: GraphEdge[];
	/**
	 * Force-directed; radial from the roots; or layered, top down from the
	 * roots (for paths).
	 */
	kind: 'force' | 'radial' | 'layered';
	/** Where radial and layered layouts start. */
	roots: string[];
	/** Current positions to adjust instead of starting over (force-directed only). */
	start?: Map<string, Position>;
}

/**
 * Lay out a graph.
 *
 * @param request - The graph and how to lay it out.
 * @returns Positions of devices and site boxes; frames follow their devices.
 */
export function layoutPositions(request: LayoutRequest): Map<string, Position> {
	const { nodes, edges, kind, roots, start } = request;
	if (kind === 'force' && nodes.length > SITEWISE_ABOVE) return sitewisePositions(request);
	const cy = cytoscape({
		headless: true,
		styleEnabled: true,
		style: [
			{ selector: 'node', style: { width: DEVICE_W, height: DEVICE_H } },
			{ selector: 'node[w]', style: { width: 'data(w)', height: 'data(h)' } },
			{ selector: ':parent', style: { padding: '20px' } }
		],
		elements: [
			...nodes.map((n) => ({ group: 'nodes' as const, data: { ...n } })),
			...edges.map((e) => ({
				group: 'edges' as const,
				data: { id: e.id, source: e.source, target: e.target }
			}))
		]
	});
	// A headless instance ignores positions given with the elements, so set them after.
	if (start) {
		cy.nodes().forEach((n) => {
			const at = start.get(n.id());
			if (at && !n.isParent()) n.position({ ...at });
		});
	}
	if (kind !== 'force') {
		const byHops: BreadthFirstLayoutOptions = {
			name: 'breadthfirst',
			roots,
			circle: kind === 'radial',
			spacingFactor: 1.3,
			avoidOverlap: true,
			animate: false,
			fit: false
		};
		cy.layout(byHops).run();
	} else {
		// fcose only refines existing positions at its slowest quality.
		const quality = start ? 'proof' : 'default';
		cy.layout({ ...FORCE, quality, randomize: !start } as LayoutOptions).run();
	}
	const positions = new Map<string, Position>();
	cy.nodes().forEach((n) => {
		if (!n.isParent()) positions.set(n.id(), { ...n.position() });
	});
	cy.destroy();
	return positions;
}

/**
 * Force-directed positions computed site by site.
 *
 * @param graph - Graph to place; frames are left to follow their devices.
 * @returns Positions of devices and collapsed site boxes.
 */
export function sitewisePositions(graph: TopoGraph): Map<string, Position> {
	const bySite = new Map<string, GraphNode[]>();
	for (const n of graph.nodes) {
		if (n.kind === 'device') bySite.set(n.site, [...(bySite.get(n.site) ?? []), n]);
	}
	const offsets = new Map<string, Position>();
	const sizes = new Map<string, { w: number; h: number }>();
	for (const [site, nodes] of bySite) {
		const ids = new Set(nodes.map((n) => n.id));
		const edges = graph.edges.filter((e) => ids.has(e.source) && ids.has(e.target));
		const boxes = nodes.map((n) => ({ id: n.id, w: DEVICE_W, h: DEVICE_H }));
		const placed = headless(boxes, edges, DEVICE_SPACING);
		const xs = [...placed.values()].map((p) => p.x);
		const ys = [...placed.values()].map((p) => p.y);
		const [x1, x2, y1, y2] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
		for (const [id, p] of placed)
			offsets.set(id, { x: p.x - (x1 + x2) / 2, y: p.y - (y1 + y2) / 2 });
		sizes.set(site, { w: x2 - x1 + DEVICE_W + FRAME_ROOM, h: y2 - y1 + DEVICE_H + FRAME_ROOM });
	}
	for (const n of graph.nodes) if (n.kind === 'site') sizes.set(n.site, { w: SITE_W, h: SITE_H });

	const siteOf = new Map(graph.nodes.map((n) => [n.id, n.site]));
	const pairs = new Map<string, { source: string; target: string }>();
	for (const e of graph.edges) {
		const [a, b] = [siteOf.get(e.source), siteOf.get(e.target)];
		if (a && b && a !== b) pairs.set(a < b ? `${a}~${b}` : `${b}~${a}`, { source: a, target: b });
	}
	const boxes = [...sizes].map(([id, size]) => ({ id, ...size }));
	const centers = headless(boxes, [...pairs.values()], SITE_SPACING);
	removeOverlaps(centers, sizes, SITE_GAP);

	const positions = new Map<string, Position>();
	for (const n of graph.nodes) {
		const center = centers.get(n.site);
		if (!center || n.kind === 'frame') continue;
		const offset = n.kind === 'device' ? offsets.get(n.id) : undefined;
		positions.set(n.id, { x: center.x + (offset?.x ?? 0), y: center.y + (offset?.y ?? 0) });
	}
	return positions;
}

/**
 * Push overlapping boxes apart, each pair along the axis needing the smaller
 * move, until none overlap; the arrangement fcose found is kept.
 */
function removeOverlaps(
	centers: Map<string, Position>,
	sizes: Map<string, { w: number; h: number }>,
	gap: number
): void {
	const boxes = [...centers].flatMap(([id, at]) => {
		const size = sizes.get(id);
		return size ? [{ at, ...size }] : [];
	});
	for (let pass = 0; pass < 200; pass++) {
		let moved = false;
		for (const [i, a] of boxes.entries()) {
			for (const b of boxes.slice(i + 1)) {
				const dx = b.at.x - a.at.x;
				const dy = b.at.y - a.at.y;
				const overlapX = (a.w + b.w) / 2 + gap - Math.abs(dx);
				const overlapY = (a.h + b.h) / 2 + gap - Math.abs(dy);
				if (overlapX <= 0 || overlapY <= 0) continue;
				moved = true;
				if (overlapX < overlapY) {
					const push = (overlapX / 2) * (dx < 0 ? -1 : 1);
					a.at.x -= push;
					b.at.x += push;
				} else {
					const push = (overlapY / 2) * (dy < 0 ? -1 : 1);
					a.at.y -= push;
					b.at.y += push;
				}
			}
		}
		if (!moved) return;
	}
}

/** Run fcose on boxes of the given sizes, off screen. */
function headless(
	nodes: { id: string; w: number; h: number }[],
	edges: { source: string; target: string }[],
	options: Spacing
): Map<string, Position> {
	const [only] = nodes;
	if (nodes.length === 1 && only) return new Map([[only.id, { x: 0, y: 0 }]]);
	const cy = cytoscape({
		headless: true,
		styleEnabled: true,
		style: [{ selector: 'node', style: { width: 'data(w)', height: 'data(h)' } }],
		elements: [
			...nodes.map((data) => ({ group: 'nodes' as const, data })),
			...edges.map((e, i) => ({ group: 'edges' as const, data: { id: `e${i}`, ...e } }))
		]
	});
	const layout = { name: 'fcose', quality: 'default', randomize: true, animate: false, fit: false };
	cy.layout({ ...layout, packComponents: true, ...options } as LayoutOptions).run();
	const positions = new Map(cy.nodes().map((n) => [n.id(), { ...n.position() }] as const));
	cy.destroy();
	return positions;
}
