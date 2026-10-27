/**
 * Cytoscape setup shared by the graph views: styling, click to select,
 * interface labels, and highlighting the shared selection.
 *
 * Interface labels at each link end show for the selected device's links
 * (or the selected links), and for every link once zoomed in close. A path,
 * when one is shown, is highlighted and labeled the same way, and everything
 * off it is faded.
 */
import cytoscape, {
	type CollectionReturnValue,
	type Core,
	type ElementDefinition,
	type NodeSingular,
	type Position,
	type StylesheetJson
} from 'cytoscape';
import type { PathResult } from '../paths.ts';
import { select, type Selection } from '../state.svelte.ts';
import { COLOR, ROLE_COLOR } from '../theme.ts';
import { siteOf, type TopologyIndex } from '../topology.ts';
import { siteNodeId, type GraphEdge, type GraphNode } from './model.ts';

const LABEL_ZOOM = 2;

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
	{
		selector: 'edge.context',
		style: { opacity: 1, 'z-index': 5, 'font-size': 8, color: COLOR.text }
	},
	{ selector: 'node.center', style: { 'border-width': 2, 'border-color': COLOR.site } },
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
	private selection: Selection | null = null;
	private path: PathResult | null = null;

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
			boxSelectionEnabled: false
		});
		this.core.on('tap', (e) => {
			if (e.target === this.core) select(null);
		});
		this.core.on('tap', 'node', (e) => {
			const { kind, id, site } = e.target.data();
			select(kind === 'device' ? { kind: 'device', id } : { kind: 'site', id: site });
		});
		this.core.on('tap', 'edge', (e) => select({ kind: 'links', ids: e.target.data('linkIds') }));
		this.core.on('dbltap', 'node', (e) => options.onDoubleTap(e.target));
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
		const elements: ElementDefinition[] = [
			...nodes.map((n) => {
				const at = positions?.get(n.id) ?? (n.x !== undefined && n.y !== undefined ? n : null);
				return {
					group: 'nodes' as const,
					data: { ...n, color: n.role ? ROLE_COLOR[n.role] : COLOR.muted },
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
		this.showLabels(true);
		this.applyHighlight();
	}

	/**
	 * What a selection corresponds to in the drawing.
	 *
	 * @param selection - The selection.
	 * @returns A device's node (or its collapsed site), a site's box, frame, or
	 *   devices, or the edges carrying the selected links. Empty if none is drawn.
	 */
	elementsFor(selection: Selection | null): CollectionReturnValue {
		const core = this.core;
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
	 * Highlight the selection and a path, and label their links. Both stay
	 * highlighted when the graph is redrawn.
	 *
	 * @param selection - The selection, or null for none.
	 * @param path - Shortest paths to show, or null for none.
	 */
	highlight(selection: Selection | null, path: PathResult | null): void {
		this.selection = selection;
		this.path = path;
		this.applyHighlight();
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

	/** Positions of every node, for caching a layout. */
	positions(): Map<string, Position> {
		return new Map(this.core.nodes().map((n) => [n.id(), { ...n.position() }] as const));
	}

	destroy(): void {
		this.resize.disconnect();
		this.core.destroy();
	}

	/** A device's node, or its site's box when the site is collapsed. */
	private nodeFor(device: string): CollectionReturnValue {
		const node = this.core.getElementById(device);
		if (node.nonempty()) return node;
		return this.core.getElementById(siteNodeId(siteOf(this.index, device)));
	}

	private applyHighlight(): void {
		const core = this.core;
		core.batch(() => {
			core.elements('.selected, .path, .faded').removeClass('selected path faded');
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
			}
			const eles = this.elementsFor(this.selection);
			eles.addClass('selected').removeClass('faded');
			const links = this.selection?.kind === 'device' ? eles.connectedEdges() : eles.edges();
			links.addClass('context');
		});
	}

	private showLabels(force = false): void {
		const show = this.core.zoom() >= LABEL_ZOOM;
		if (show === this.labelsShown && !force) return;
		this.labelsShown = show;
		this.core.edges().toggleClass('labels', show);
	}
}
