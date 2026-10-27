/**
 * Layout for the top-down hierarchy view.
 *
 * Sites are stacked in levels: sites with a core tier on top, the rest by
 * WAN hops from those. A collapsed site is one box. An expanded site is a
 * frame with its devices in fixed tier rows (WAN edge, core, distribution,
 * access). A general layered-graph algorithm would put every link between
 * two different rows, splitting a redundant pair joined by a peer link onto
 * different rows; fixed tier rows keep such pairs side by side.
 *
 * Each level is wrapped into lines. One line width is used for every level,
 * chosen so the busiest level comes out about as wide as a screen is.
 */
import type { Device } from '../api/topology.ts';
import {
	deviceNode,
	frameNode,
	mergeLinks,
	SITE_H,
	SITE_W,
	siteBoxNode,
	siteNodeId,
	type GraphEdge,
	type GraphNode
} from '../graph/model.ts';
import { compareNatural, ROLES, siteOf, type TopologyIndex } from '../topology.ts';
const DX = 76;
const DY = 64;
const TIER_GAP = 36;
const MAX_PER_ROW = 12;
const DEVICE_W = 50;
const DEVICE_H = 28;
const FRAME_PAD = 28;
const FRAME_LABEL = 24;
const CELL_GAP = 60;
const LINE_GAP = 70;
const LEVEL_GAP = 170;
const MIN_LINE_W = 2400;
const SCREEN_ASPECT = 1.8;

/** A node with the position this layout gives it. */
export type HNode = GraphNode & { x: number; y: number };

export interface HierarchyGraph {
	nodes: HNode[];
	edges: GraphEdge[];
}

interface Block {
	code: string;
	w: number;
	h: number;
	devices: { device: Device; x: number; y: number }[];
}

/**
 * Group sites into levels, top first.
 *
 * @param index - Topology index.
 * @returns Site codes per level, ordered to keep links between levels short.
 */
export function siteLevels(index: TopologyIndex): string[][] {
	const codes = index.topology.sites.map((s) => s.code);
	const adjacent = new Map(codes.map((c) => [c, new Set<string>()]));
	for (const link of index.topology.links) {
		const a = siteOf(index, link.a.device);
		const b = siteOf(index, link.b.device);
		if (a === b) continue;
		adjacent.get(a)?.add(b);
		adjacent.get(b)?.add(a);
	}
	const degree = (c: string) => adjacent.get(c)?.size ?? 0;
	let roots = codes.filter((c) => index.devicesBySite.get(c)?.some((d) => d.role === 'core'));
	if (roots.length === 0) {
		const max = Math.max(...codes.map(degree));
		roots = codes.filter((c) => degree(c) === max);
	}

	const level = new Map(roots.map((c) => [c, 0]));
	for (let frontier = roots; frontier.length > 0;) {
		const next: string[] = [];
		for (const c of frontier) {
			for (const n of adjacent.get(c) ?? []) {
				if (level.has(n)) continue;
				level.set(n, (level.get(c) ?? 0) + 1);
				next.push(n);
			}
		}
		frontier = next;
	}
	// Sites with no path to the top go on one extra level at the bottom.
	const unreached = Math.max(0, ...level.values()) + 1;
	const levels: string[][] = [];
	for (const c of codes) (levels[level.get(c) ?? unreached] ??= []).push(c);

	const region = (c: string) => index.sites.get(c)?.region ?? '';
	for (let i = 1; i < levels.length; i++) {
		const above = new Map((levels[i - 1] ?? []).map((c, k) => [c, k]));
		const barycenter = (c: string) =>
			average([...(adjacent.get(c) ?? [])].map((n) => above.get(n)));
		levels[i]?.sort(
			(x, y) =>
				barycenter(x) - barycenter(y) || region(x).localeCompare(region(y)) || compareNatural(x, y)
		);
	}
	return levels.filter((l) => l !== undefined);
}

/** Mean of the defined values, or Infinity (sorts last) if there are none. */
function average(values: (number | undefined)[]): number {
	const known = values.filter((v) => v !== undefined);
	return known.length ? known.reduce((s, v) => s + v, 0) / known.length : Infinity;
}

/** An expanded site: devices in tier rows, each ordered under its upper neighbors. */
function expandedBlock(index: TopologyIndex, code: string): Block {
	const devices = index.devicesBySite.get(code) ?? [];
	const x = new Map<string, number>();
	const placed: Block['devices'] = [];
	let y = 0;
	let widest = 1;
	for (const role of ROLES) {
		const tier = devices.filter((d) => d.role === role);
		if (tier.length === 0) continue;
		if (placed.length > 0) y += TIER_GAP;
		const barycenter = (name: string) =>
			average(
				(index.linksByDevice.get(name) ?? []).map((l) =>
					x.get(l.a.device === name ? l.b.device : l.a.device)
				)
			);
		tier.sort((p, q) => barycenter(p.name) - barycenter(q.name) || compareNatural(p.name, q.name));
		for (let start = 0; start < tier.length; start += MAX_PER_ROW) {
			const row = tier.slice(start, start + MAX_PER_ROW);
			widest = Math.max(widest, row.length);
			row.forEach((d, i) => {
				const dx = (i - (row.length - 1) / 2) * DX;
				x.set(d.name, dx);
				placed.push({ device: d, x: dx, y });
			});
			y += DY;
		}
	}
	const w = (widest - 1) * DX + DEVICE_W + 2 * FRAME_PAD;
	const h = y - DY + DEVICE_H + 2 * FRAME_PAD + FRAME_LABEL;
	for (const d of placed) {
		d.x += w / 2;
		d.y += FRAME_LABEL + FRAME_PAD + DEVICE_H / 2;
	}
	return { code, w, h, devices: placed };
}

/** Split blocks into lines no wider than `width` (a block wider than that gets its own line). */
function packLines(blocks: Block[], width: number): Block[][] {
	const lines: Block[][] = [];
	let line: Block[] = [];
	let used = 0;
	for (const block of blocks) {
		if (line.length > 0 && used + CELL_GAP + block.w > width) {
			lines.push(line);
			line = [];
			used = 0;
		}
		used += (line.length > 0 ? CELL_GAP : 0) + block.w;
		line.push(block);
	}
	if (line.length > 0) lines.push(line);
	return lines;
}

/**
 * Lay out the hierarchy.
 *
 * @param index - Topology index.
 * @param expanded - Codes of sites to show device by device.
 * @returns Positioned nodes (centers) and merged edges.
 */
export function buildHierarchy(
	index: TopologyIndex,
	expanded: ReadonlySet<string>
): HierarchyGraph {
	const levels = siteLevels(index).map((level) =>
		level.map((code) =>
			expanded.has(code) ? expandedBlock(index, code) : { code, w: SITE_W, h: SITE_H, devices: [] }
		)
	);
	const blocks = levels.flat();
	const busiest = Math.max(
		...levels.map((l) => l.reduce((s, b) => s + (b.w + CELL_GAP) * (b.h + LINE_GAP), 0))
	);
	const lineWidth = Math.max(
		MIN_LINE_W,
		...blocks.map((b) => b.w),
		Math.sqrt(busiest * SCREEN_ASPECT)
	);
	const nodes: HNode[] = [];
	let top = 0;
	for (const level of levels) {
		for (const line of packLines(level, lineWidth)) {
			let left = -(line.reduce((s, b) => s + b.w, 0) + CELL_GAP * (line.length - 1)) / 2;
			for (const block of line) {
				nodes.push(...blockNodes(index, block, expanded.has(block.code), left, top));
				left += block.w + CELL_GAP;
			}
			top += Math.max(...line.map((b) => b.h)) + LINE_GAP;
		}
		top += LEVEL_GAP - LINE_GAP;
	}
	const nodeOf = (device: string) => {
		const site = siteOf(index, device);
		return expanded.has(site) ? device : siteNodeId(site);
	};
	return { nodes, edges: mergeLinks(index.topology.links, nodeOf) };
}

function blockNodes(
	index: TopologyIndex,
	block: Block,
	expanded: boolean,
	left: number,
	top: number
): HNode[] {
	const { code, w, h } = block;
	const center = { x: left + w / 2, y: top + h / 2, w, h };
	if (!expanded) return [{ ...siteBoxNode(index, code), ...center }];
	// The frame is sized here, so it is drawn as a plain node behind the devices rather
	// than as their compound parent, which costs Cytoscape dearly on large graphs.
	return [
		{ ...frameNode(index, code), ...center },
		...block.devices.map((d) => ({
			...deviceNode(d.device, false),
			x: left + d.x,
			y: top + d.y
		}))
	];
}
