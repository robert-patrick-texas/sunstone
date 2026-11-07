/**
 * Cytoscape setup shared by the graph views: styling, click to select,
 * interface labels, and highlighting the shared selection.
 *
 * Interface labels at each link end show for the selected device's links
 * (or the selected links), and for every link once zoomed in close. A path,
 * when one is shown, is highlighted and labeled the same way, and everything
 * off it is faded. With live state, devices and site boxes take their health
 * colors and glyphs and edges their load colors; path and selection still
 * draw on top. An impact (a problem's, or a "what if") is drawn like a path:
 * failed, cut-off, and exposed devices and lost links in their own styles,
 * everything else faded. So is discovery, when there is neither: cables seen
 * but not documented are drawn as dashed edges (with a node of its own for a
 * neighbor not in the topology), documented links not seen as documented are
 * dotted, devices involved are ringed, and everything else is faded.
 *
 * Site frames are drawn as backdrops behind their devices, never as Cytoscape
 * compound parents: on the 3,000-device sample, compound nodes doubled the
 * time to draw a graph. A frame either comes with its size (the hierarchy
 * computes it) or is fitted around its devices with {@link GraphCanvas.fitFrames},
 * and follows them when they are dragged.
 */
import cytoscape, {
	type CollectionReturnValue,
	type Core,
	type ElementDefinition,
	type NodeCollection,
	type NodeSingular,
	type Position,
	type StylesheetJson
} from 'cytoscape';
import type { Comparison } from '../api/discovery.ts';
import { deviceImpact, linksImpact, tunnelsImpact, worstImpact, type Impact } from '../impact.ts';
import {
	bundleLive,
	deviceHealth,
	groupHealth,
	linkLive,
	tunnelsLive,
	type LiveIndex
} from '../live.ts';
import type { PathResult } from '../paths.ts';
import { footprint } from '../layers.ts';
import { isPhysical, select, type AnySelection } from '../state.svelte.ts';
import {
	COLOR,
	DRIFT_COLOR,
	HEALTH_COLOR,
	HEALTH_GLYPH,
	IMPACT_COLOR,
	IMPACT_GLYPH,
	LINK_NODATA,
	LINK_UNMONITORED,
	ROLE_COLOR,
	TUNNEL_COLOR,
	utilColor
} from '../theme.ts';
import { siteOf, type TopologyIndex } from '../topology.ts';
import { timed } from '../perf.ts';
import { ghostElements, siteNodeId, type GraphEdge, type GraphNode } from './model.ts';

const LABEL_ZOOM = 2;
/** Room between a fitted frame and its devices, labels included. */
const FRAME_PAD = 20;

const STYLE: StylesheetJson = [
	{
		selector: 'node[kind = "device"]',
		style: {
			shape: 'round-rectangle',
			width: 22,
			height: 14,
			'background-color': 'data(color)',
			label: 'data(label)',
			color: COLOR.text,
			'font-size': 8,
			'text-valign': 'bottom',
			'text-margin-y': 3,
			'min-zoomed-font-size': 6
		}
	},
	{
		selector: 'node[kind = "site"]',
		style: {
			shape: 'round-rectangle',
			width: 'data(w)',
			height: 'data(h)',
			'background-color': COLOR.siteBox,
			'border-color': COLOR.site,
			'border-width': 1.5,
			label: 'data(label)',
			color: COLOR.text,
			'font-size': 12,
			'text-wrap': 'wrap',
			'text-valign': 'center'
		}
	},
	{
		selector: 'node[kind = "frame"]',
		style: {
			shape: 'round-rectangle',
			'background-color': COLOR.group,
			'background-opacity': 0.7,
			'border-color': COLOR.groupBorder,
			'border-style': 'dashed',
			'border-width': 1,
			label: 'data(label)',
			color: COLOR.site,
			'font-size': 14,
			'text-valign': 'top',
			'text-margin-y': -4,
			padding: '20px'
		}
	},
	{
		// A frame with its own size is a backdrop, not a compound parent.
		selector: 'node[kind = "frame"][w]',
		style: { width: 'data(w)', height: 'data(h)', 'z-compound-depth': 'bottom' }
	},
	{
		// Outside the boundary: clouds and external nodes have dashed borders.
		selector: 'node[kind = "transport"]',
		style: {
			shape: 'ellipse',
			width: 110,
			height: 50,
			'background-color': COLOR.cloud,
			'border-color': COLOR.outside,
			'border-style': 'dashed',
			'border-width': 1.5,
			label: 'data(label)',
			color: COLOR.text,
			'font-size': 12,
			'text-valign': 'center'
		}
	},
	{ selector: 'node[kind = "transport"][w]', style: { width: 'data(w)', height: 'data(h)' } },
	{
		selector: 'node[kind = "external"]',
		style: {
			shape: 'round-rectangle',
			width: 86,
			height: 20,
			'background-color': COLOR.background,
			'border-color': COLOR.outside,
			'border-style': 'dashed',
			'border-width': 1.5,
			label: 'data(label)',
			color: COLOR.muted,
			'font-size': 9,
			'text-valign': 'center'
		}
	},
	{ selector: 'node[kind = "external"][w]', style: { width: 'data(w)', height: 'data(h)' } },
	{ selector: 'node[externalKind = "service"]', style: { shape: 'round-hexagon' } },
	{ selector: 'node[externalKind = "tenant"]', style: { shape: 'round-diamond' } },
	{
		selector: 'node[kind = "ring"]',
		style: {
			shape: 'ellipse',
			width: 'data(d)',
			height: 'data(d)',
			'background-opacity': 0,
			'border-width': 1,
			'border-style': 'dashed',
			'border-color': COLOR.groupBorder,
			label: 'data(label)',
			'text-valign': 'top',
			color: COLOR.muted,
			'font-size': 11,
			events: 'no'
		}
	},
	{
		selector: 'edge',
		style: {
			'curve-style': 'straight',
			width: 'data(width)',
			'line-color': COLOR.lan,
			opacity: 0.75
		}
	},
	{
		selector: 'edge.labels, edge.context',
		style: {
			'source-label': 'data(sourceLabel)',
			'target-label': 'data(targetLabel)',
			'source-text-offset': 20,
			'target-text-offset': 20,
			'font-size': 6,
			color: COLOR.muted,
			'text-background-color': COLOR.background,
			'text-background-opacity': 0.85,
			'text-background-padding': '1px'
		}
	},
	{ selector: 'edge[kind = "wan"]', style: { 'line-color': COLOR.wan, opacity: 0.45 } },
	// The logical view: networks in their colors, parallel edges of different
	// networks fanned apart, tunnels and fabric memberships dashed.
	{
		selector: 'edge[network]',
		style: { 'line-color': 'data(color)', opacity: 0.85, 'curve-style': 'bezier' }
	},
	{
		selector: 'edge[kind = "tunnel"], edge[kind = "fabric"]',
		style: { 'line-style': 'dashed', 'line-dash-pattern': [6, 4], width: 1.6 }
	},
	{
		selector: 'edge[kind = "reach"]',
		style: { 'line-style': 'dotted', 'line-color': COLOR.outside, opacity: 0.6, width: 1 }
	},
	{
		selector: 'edge[label]',
		style: {
			label: 'data(label)',
			'font-size': 7,
			color: COLOR.muted,
			'min-zoomed-font-size': 7,
			'text-background-color': COLOR.background,
			'text-background-opacity': 0.85,
			'text-background-padding': '1px'
		}
	},
	{
		selector: 'node[kind = "fabric"]',
		style: {
			shape: 'round-hexagon',
			width: 'data(w)',
			height: 'data(h)',
			'background-color': COLOR.cloud,
			'border-color': 'data(tint)',
			'border-width': 2,
			label: 'data(label)',
			color: COLOR.text,
			'font-size': 11,
			'text-valign': 'center',
			'text-wrap': 'wrap'
		}
	},
	{
		selector: 'edge.context',
		style: { opacity: 1, 'z-index': 5, 'font-size': 8, color: COLOR.text }
	},
	{
		selector: 'node.live[kind = "device"]',
		style: { 'background-color': 'data(liveColor)', label: 'data(liveLabel)' }
	},
	{
		selector: 'node.live-down[kind = "device"]',
		style: { shape: 'octagon', width: 24, height: 18 }
	},
	{
		selector: 'node.live-nodata[kind = "device"]',
		style: { 'border-width': 1.5, 'border-style': 'dashed', 'border-color': COLOR.text }
	},
	{
		selector: 'node.live-unmonitored[kind = "device"]',
		style: {
			'background-opacity': 0,
			'border-width': 1,
			'border-color': HEALTH_COLOR.unmonitored
		}
	},
	{
		selector: 'node.live[kind = "site"]',
		style: { 'border-color': 'data(liveColor)', 'border-width': 2.5, label: 'data(liveLabel)' }
	},
	{ selector: 'edge.live', style: { 'line-color': 'data(liveColor)', opacity: 0.9 } },
	{
		selector: 'edge.live-down, edge.live-partial',
		style: { 'line-style': 'dashed', 'line-dash-pattern': [6, 3] }
	},
	{ selector: 'edge.live-nodata', style: { 'line-style': 'dotted', opacity: 0.8 } },
	{ selector: 'edge.live-unmonitored', style: { opacity: 0.6 } },
	{
		selector: 'node.impact[kind = "device"]',
		style: { label: 'data(impactLabel)', 'background-opacity': 1, 'border-width': 0 }
	},
	{
		selector: 'node.impact-failed[kind = "device"]',
		style: {
			'background-color': IMPACT_COLOR.failed,
			shape: 'octagon',
			width: 24,
			height: 18
		}
	},
	{
		selector: 'node.impact-cutoff[kind = "device"]',
		style: {
			'background-color': COLOR.background,
			'border-width': 2,
			'border-style': 'solid',
			'border-color': IMPACT_COLOR.cutoff
		}
	},
	{
		selector: 'node.impact-exposed[kind = "device"]',
		style: { 'background-color': IMPACT_COLOR.exposed }
	},
	{
		selector: 'node.impact[kind = "site"]',
		style: { 'border-width': 3, 'border-color': 'data(impactColor)', label: 'data(impactLabel)' }
	},
	{
		selector: 'edge.impact',
		style: { 'line-style': 'dashed', 'line-dash-pattern': [6, 3], opacity: 1, 'z-index': 6 }
	},
	{ selector: 'edge.impact-lost', style: { 'line-color': IMPACT_COLOR.failed } },
	{ selector: 'edge.impact-partial', style: { 'line-color': IMPACT_COLOR.exposed } },
	{
		selector: 'edge.ghost',
		style: {
			'line-color': DRIFT_COLOR,
			'line-style': 'dashed',
			'line-dash-pattern': [8, 4],
			width: 2,
			'curve-style': 'bezier',
			opacity: 1,
			'z-index': 7
		}
	},
	{
		selector: 'node.ghost',
		style: {
			shape: 'round-rectangle',
			width: 18,
			height: 12,
			'background-opacity': 0,
			'border-width': 1.5,
			'border-style': 'dashed',
			'border-color': DRIFT_COLOR,
			label: 'data(label)',
			color: COLOR.text,
			'font-size': 9
		}
	},
	{
		selector: 'edge.drift',
		style: { 'line-color': DRIFT_COLOR, 'line-style': 'dotted', opacity: 1, 'z-index': 6 }
	},
	{ selector: 'node.drift', style: { 'border-width': 3, 'border-color': DRIFT_COLOR } },
	{ selector: 'node.center', style: { 'border-width': 2, 'border-color': COLOR.site } },
	{ selector: 'edge[?beneath]', style: { opacity: 0.25 } },
	{ selector: '.faded', style: { opacity: 0.15 } },
	{ selector: 'node.path', style: { 'border-width': 3, 'border-color': COLOR.path } },
	{
		selector: 'edge.path',
		style: { 'line-color': COLOR.path, opacity: 1, 'z-index': 8 }
	},
	{ selector: 'node.selected', style: { 'border-width': 3, 'border-color': COLOR.selected } },
	{
		selector: 'edge.selected',
		style: { 'line-color': COLOR.selected, opacity: 1, 'z-index': 10 }
	}
];

export interface CanvasOptions {
	/** Let the user drag nodes around. */
	grabbable: boolean;
	onDoubleTap: (node: NodeSingular) => void;
}

/** A Cytoscape instance drawing topology graphs, wired to the shared selection. */
export class GraphCanvas {
	readonly core: Core;
	private readonly index: TopologyIndex;
	private readonly resize: ResizeObserver;
	private edgeOfLink = new Map<string, string>();
	private labelsShown = false;
	private selection: AnySelection | null = null;
	private path: PathResult | null = null;
	private impact: Impact | null = null;
	private discovery: Comparison | null = null;
	private live: LiveIndex | null = null;

	/**
	 * @param container - Element to draw in; the canvas follows its size.
	 * @param index - Topology index.
	 * @param options - Behavior that differs between views.
	 */
	constructor(container: HTMLElement, index: TopologyIndex, options: CanvasOptions) {
		this.index = index;
		this.core = cytoscape({
			container,
			style: STYLE,
			minZoom: 0.02,
			maxZoom: 4,
			autoungrabify: !options.grabbable,
			boxSelectionEnabled: false,
			// While panning and zooming, move a picture of the graph instead of
			// redrawing thousands of elements every frame.
			textureOnViewport: true
		});
		this.core.on('tap', (e) => {
			if (e.target === this.core) select(null);
		});
		this.core.on('tap', 'node', (e) => {
			const { kind, id, site, device } = e.target.data();
			// Something only discovery sees selects the device it hangs off.
			if (kind === 'ghost') select({ kind: 'device', id: device });
			else if (kind === 'transport' || kind === 'external' || kind === 'fabric') {
				select({ kind, id: id.slice(kind.length + 1) });
			} else select(kind === 'device' ? { kind: 'device', id } : { kind: 'site', id: site });
		});
		this.core.on('tap', 'edge', (e) => {
			const { kind, linkIds, device, tunnels, fabric, network, source } = e.target.data();
			if (kind === 'ghost') select({ kind: 'device', id: device });
			else if (kind === 'tunnel') {
				select(
					tunnels.length === 1
						? { kind: 'tunnel', id: tunnels[0] }
						: { kind: 'network', id: network }
				);
			} else if (kind === 'fabric') select({ kind: 'fabric', id: fabric });
			else if (kind === 'reach') select({ kind: 'external', id: source.slice('external:'.length) });
			else select({ kind: 'links', ids: linkIds });
		});
		this.core.on('dbltap', 'node[kind != "ghost"]', (e) => options.onDoubleTap(e.target));
		// A dragged device takes its frame along; a dragged frame takes its devices.
		this.core.on('drag', 'node[kind = "device"]', (e) => this.fitFrames([e.target.data('site')]));
		this.core.on('grab', 'node[kind = "frame"]', (e) => {
			e.target.scratch('_from', { ...e.target.position() });
		});
		this.core.on('drag', 'node[kind = "frame"]', (e) => {
			const frame: NodeSingular = e.target;
			const from: Position = frame.scratch('_from');
			const at = frame.position();
			this.membersOf(frame.data('site')).shift({ x: at.x - from.x, y: at.y - from.y });
			frame.scratch('_from', { ...at });
		});
		this.core.on('zoom', () => this.showLabels());
		this.resize = new ResizeObserver(() => this.core.resize());
		this.resize.observe(container);
	}

	/**
	 * Replace everything drawn.
	 *
	 * @param nodes - Nodes; each is placed at `positions` if listed there, else at its own x and y.
	 * @param edges - Edges between them.
	 * @param positions - Placements that override the nodes' own (for example a cached layout).
	 */
	setGraph(nodes: GraphNode[], edges: GraphEdge[], positions?: Map<string, Position>): void {
		timed('graph draw', () => this.draw(nodes, edges, positions));
	}

	private draw(nodes: GraphNode[], edges: GraphEdge[], positions?: Map<string, Position>): void {
		const elements: ElementDefinition[] = [
			...nodes.map((n) => {
				const at = positions?.get(n.id) ?? (n.x !== undefined && n.y !== undefined ? n : null);
				return {
					group: 'nodes' as const,
					// Frames are backdrops, not compound parents (see the module comment).
					data: { ...n, parent: undefined, color: n.role ? ROLE_COLOR[n.role] : COLOR.muted },
					...(at ? { position: { x: at.x ?? 0, y: at.y ?? 0 } } : {})
				};
			}),
			...edges.map((e) => ({
				group: 'edges' as const,
				data: { ...e, width: Math.min(6, 1 + 1.5 * Math.log10(e.capacityMbps / 1000 + 1)) }
			}))
		];
		this.edgeOfLink = new Map(edges.flatMap((e) => e.linkIds.map((id) => [id, e.id] as const)));
		this.core.batch(() => {
			this.core.elements().remove();
			this.core.add(elements);
		});
		this.drawGhosts();
		this.showLabels(true);
		this.applyLive();
		this.applyHighlight();
	}

	/**
	 * Show where discovery and the documentation disagree, when no path or
	 * impact is shown; or stop.
	 *
	 * @param discovery - The latest comparison, or null.
	 */
	setDiscovery(discovery: Comparison | null): void {
		this.discovery = discovery;
		timed('graph discovery', () => {
			this.drawGhosts();
			this.showLabels(true);
			this.applyHighlight();
		});
	}

	/**
	 * Draw what discovery sees but the documentation does not have, beside
	 * the nodes as they are now placed. Call again after moving nodes.
	 */
	drawGhosts(): void {
		const core = this.core;
		core.batch(() => {
			core.elements('.ghost').remove();
			if (!this.discovery) return;
			const nodeOf = (device: string) => {
				const node = this.nodeFor(device);
				return node.nonempty() ? node.id() : null;
			};
			const at = (id: string) => ({ ...core.getElementById(id).position() });
			core.add(ghostElements(this.discovery.seen, nodeOf, at));
		});
	}

	/**
	 * Show live state, or go back to structure only.
	 *
	 * @param live - The latest snapshot, or null.
	 */
	setLive(live: LiveIndex | null): void {
		this.live = live;
		timed('graph live', () => this.applyLive());
	}

	/**
	 * What a selection corresponds to in the drawing.
	 *
	 * @param selection - The selection.
	 * @returns A device's node (or its collapsed site), a site's box, frame, or
	 *   devices, or the edges carrying the selected links. Empty if none is drawn.
	 */
	elementsFor(selection: AnySelection | null): CollectionReturnValue {
		const core = this.core;
		if (selection && !isPhysical(selection)) {
			// A network, transport, tunnel, and so on: everything it stands for.
			const where = footprint(this.index, selection);
			const edgeIds = new Set([...where.links].map((id) => this.edgeOfLink.get(id)));
			// In the logical view, its own edges and node too.
			const { kind, id } = selection;
			for (const e of core.edges('[network]')) {
				const d = e.data();
				const own =
					(kind === 'network' && d.network === id) ||
					(kind === 'tunnel' && d.tunnels?.includes(id)) ||
					(kind === 'fabric' && d.fabric === id);
				if (own) edgeIds.add(e.id());
			}
			if (kind === 'fabric') where.nodes.add(`fabric:${id}`);
			const beyond = [...where.nodes].reduce(
				(all, key) => all.union(core.getElementById(key)),
				core.edges().filter((e) => edgeIds.has(e.id()))
			);
			return [...where.devices].reduce((all, device) => all.union(this.nodeFor(device)), beyond);
		}
		if (selection?.kind === 'device') return this.nodeFor(selection.id);
		if (selection?.kind === 'site') {
			const node = core.getElementById(siteNodeId(selection.id));
			if (node.nonempty()) return node;
			return core.nodes().filter((n) => n.data('site') === selection.id);
		}
		const ids = new Set(selection?.ids.map((id) => this.edgeOfLink.get(id)));
		return core.edges().filter((e) => ids.has(e.id()));
	}

	/**
	 * Highlight the selection and a path or an impact, and label their links.
	 * They stay highlighted when the graph is redrawn.
	 *
	 * @param selection - The selection, or null for none.
	 * @param path - Shortest paths to show, or null for none.
	 * @param impact - Impact to show when there is no path, or null for none.
	 */
	highlight(selection: AnySelection | null, path: PathResult | null, impact: Impact | null): void {
		this.selection = selection;
		this.path = path;
		this.impact = impact;
		timed('graph highlight', () => this.applyHighlight());
	}

	/**
	 * The drawn nodes and edges a path runs through.
	 *
	 * @param path - Shortest paths.
	 * @returns Device nodes (site boxes for collapsed sites) and edges carrying path links.
	 */
	pathElements(path: PathResult): CollectionReturnValue {
		const core = this.core;
		const edgeIds = new Set([...path.links].map((id) => this.edgeOfLink.get(id)));
		return [...path.devices.keys()].reduce(
			(all, device) => all.union(this.nodeFor(device)),
			core.edges().filter((e) => edgeIds.has(e.id()))
		);
	}

	/**
	 * Size and place frames around their sites' devices.
	 *
	 * @param sites - Sites whose frames to fit, or all of them.
	 */
	fitFrames(sites?: Iterable<string>): void {
		const only = sites ? new Set(sites) : null;
		this.core.batch(() => {
			this.core.nodes('[kind = "frame"]').forEach((frame) => {
				const site: string = frame.data('site');
				if (only && !only.has(site)) return;
				const members = this.membersOf(site);
				if (members.empty()) return;
				const box = members.boundingBox({ includeLabels: true });
				frame.data({ w: box.w + 2 * FRAME_PAD, h: box.h + 2 * FRAME_PAD });
				frame.position({ x: (box.x1 + box.x2) / 2, y: (box.y1 + box.y2) / 2 });
			});
		});
	}

	/**
	 * Move transports, fabrics, and external nodes off anything a layout put
	 * them on. A transport joins the sites whose circuits go into it, so a
	 * force-directed layout puts it in their middle, often on the hubs or on
	 * a fabric over it joining the same sites.
	 */
	separateBeyond(): void {
		const beyond = this.core.nodes('[kind = "transport"], [kind = "fabric"], [kind = "external"]');
		const others = this.core
			.nodes('[kind != "frame"][kind != "ring"]')
			.difference(beyond)
			.map((n) => n.boundingBox());
		const placed: typeof others = [];
		const overlaps = (a: (typeof others)[0], b: (typeof others)[0]) =>
			a.x1 < b.x2 && b.x1 < a.x2 && a.y1 < b.y2 && b.y1 < a.y2;
		beyond.forEach((n) => {
			let box = n.boundingBox();
			for (let tries = 0; tries < 50; tries++) {
				if (![...others, ...placed].some((b) => overlaps(box, b))) break;
				n.shift({ x: 0, y: box.h + 12 });
				box = n.boundingBox();
			}
			placed.push(box);
		});
	}

	/** Positions of every node, for caching a layout. */
	positions(): Map<string, Position> {
		return new Map(this.core.nodes().map((n) => [n.id(), { ...n.position() }] as const));
	}

	destroy(): void {
		this.resize.disconnect();
		this.core.destroy();
	}

	private membersOf(site: string): NodeCollection {
		return this.core.nodes(`[kind = "device"][site = "${site}"]`);
	}

	/** A device's node, or its site's box when the site is collapsed. */
	private nodeFor(device: string): CollectionReturnValue {
		const node = this.core.getElementById(device);
		if (node.nonempty()) return node;
		return this.core.getElementById(siteNodeId(siteOf(this.index, device)));
	}

	private applyLive(): void {
		const { core, live, index } = this;
		core.batch(() => {
			core.elements('.live').removeClass(LIVE_CLASSES);
			if (!live) return;
			core.nodes('[kind = "device"]').forEach((n) => {
				const health = deviceHealth(live, n.id());
				const liveLabel = glyphed(HEALTH_GLYPH[health], n.data('label'));
				n.data({ liveColor: HEALTH_COLOR[health], liveLabel });
				n.addClass(`live live-${health}`);
			});
			core.nodes('[kind = "site"]').forEach((n) => {
				const site: string = n.data('site');
				const devices = (index.devicesBySite.get(site) ?? []).map((d) => d.name);
				const { health, counts } = groupHealth(live, devices);
				const down = counts.down ? `\n${counts.down} down` : '';
				n.data({ liveColor: HEALTH_COLOR[health], liveLabel: `${n.data('label')}${down}` });
				n.addClass(`live live-${health}`);
			});
			core.edges().forEach((e) => {
				// Tunnels by their own health, still dashed; a fabric member's way in
				// by the tunnels it ends; one the source does not report is neutral.
				if (['tunnel', 'fabric', 'reach'].includes(e.data('kind'))) {
					const health = tunnelsLive(live, e.data('tunnels') ?? []);
					e.data('liveColor', TUNNEL_COLOR[health]);
					e.addClass('live');
					return;
				}
				const ids: string[] = e.data('linkIds');
				const links = ids.flatMap((id) => index.links.get(id) ?? []);
				const { health, utilPct } = bundleLive(links.map((l) => linkLive(live, l)));
				const color =
					health === 'down'
						? HEALTH_COLOR.down
						: health === 'nodata'
							? LINK_NODATA
							: health === 'unmonitored'
								? LINK_UNMONITORED
								: utilColor(utilPct ?? 0);
				e.data('liveColor', color);
				e.addClass(`live live-${health}`);
			});
		});
	}

	private applyHighlight(): void {
		const core = this.core;
		core.batch(() => {
			core.elements('.selected, .path, .faded, .drift').removeClass('selected path faded drift');
			core.elements('.impact').removeClass(IMPACT_CLASSES);
			core.edges('.context').removeClass('context');
			if (this.path) {
				const onPath = this.pathElements(this.path);
				onPath.addClass('path');
				onPath.edges().addClass('context');
				// Site frames stay as they are, so the sites around the path stay readable.
				core
					.elements()
					.difference(onPath)
					.filter((e) => e.data('kind') !== 'frame')
					.addClass('faded');
			} else if (this.impact) {
				this.applyImpact(this.impact);
			} else if (this.discovery) {
				this.applyDiscovery(this.discovery);
			}
			const eles = this.elementsFor(this.selection);
			eles.addClass('selected').removeClass('faded');
			const links = this.selection?.kind === 'device' ? eles.connectedEdges() : eles.edges();
			links.addClass('context');
		});
	}

	private applyImpact(impact: Impact): void {
		const index = this.index;
		this.core.nodes('[kind = "device"]').forEach((n) => {
			const found = deviceImpact(impact, n.id());
			if (found) {
				n.data('impactLabel', glyphed(IMPACT_GLYPH[found], n.data('label')));
				n.addClass(`impact impact-${found}`);
			} else n.addClass('faded');
		});
		// A collapsed site shows its worst-affected device, and how many it loses.
		this.core.nodes('[kind = "site"]').forEach((n) => {
			const devices = (index.devicesBySite.get(n.data('site')) ?? []).map((d) => d.name);
			const found = worstImpact(impact, devices);
			if (!found) {
				n.addClass('faded');
				return;
			}
			const lost = devices.filter((d) => impact.cutOff.has(d) || impact.failed.devices.has(d));
			const label: string = n.data('label');
			n.data({
				impactColor: IMPACT_COLOR[found],
				impactLabel: lost.length ? `${label}\n${lost.length} lost` : label
			});
			n.addClass(`impact impact-${found}`);
		});
		this.core.edges().forEach((e) => {
			// Tunnels, and a fabric member's way in, by the tunnels they stand for.
			const tunnels: string[] = e.data('tunnels') ?? [];
			const ids: string[] = e.data('linkIds') ?? [];
			const found = tunnels.length
				? tunnelsImpact(impact, tunnels)
				: linksImpact(
						impact,
						ids.flatMap((id) => index.links.get(id) ?? [])
					);
			if (found) e.addClass(`impact impact-${found}`);
			else e.addClass('faded');
		});
	}

	private applyDiscovery(discovery: Comparison): void {
		const drift = new Set(
			Object.entries(discovery.links)
				.filter(([, check]) => check === 'mismatch' || check === 'not-seen')
				.map(([id]) => id)
		);
		const involved = new Set(discovery.findings.flatMap((f) => f.devices));
		this.core.edges('[kind != "ghost"]').forEach((e) => {
			const ids: string[] = e.data('linkIds');
			e.addClass(ids.some((id) => drift.has(id)) ? 'drift' : 'faded');
		});
		this.core.nodes('[kind = "device"]').forEach((n) => {
			n.addClass(involved.has(n.id()) ? 'drift' : 'faded');
		});
		this.core.nodes('[kind = "site"]').forEach((n) => {
			const devices = this.index.devicesBySite.get(n.data('site')) ?? [];
			n.addClass(devices.some((d) => involved.has(d.name)) ? 'drift' : 'faded');
		});
	}

	private showLabels(force = false): void {
		const show = this.core.zoom() >= LABEL_ZOOM;
		if (show === this.labelsShown && !force) return;
		this.labelsShown = show;
		this.core.edges().toggleClass('labels', show);
	}
}

const LIVE_CLASSES = [
	'live',
	...['up', 'degraded', 'down', 'nodata', 'unmonitored', 'ok', 'partial'].map((h) => `live-${h}`)
].join(' ');

const IMPACT_CLASSES = [
	'impact',
	...['failed', 'cutoff', 'exposed', 'lost', 'partial'].map((i) => `impact-${i}`)
].join(' ');

/** A device label with a glyph in front, if there is one. */
function glyphed(glyph: string, label: string): string {
	return glyph ? `${glyph} ${label}` : label;
}
