<!--
@component
Top-down hierarchy view. Sites are boxes until expanded (double-click, or
the details panel); expanded sites show devices in tier rows. Interface
labels at each link end show for the selected device's links, and for
every link once zoomed in close.
-->
<script lang="ts">
	import { onMount, tick, untrack } from 'svelte';
	import cytoscape, { type Core, type ElementDefinition, type StylesheetJson } from 'cytoscape';
	import { expandedSites, select, ui, type Selection } from '../state.svelte.ts';
	import { COLOR, ROLE_COLOR } from '../theme.ts';
	import { siteOf, type TopologyIndex } from '../topology.ts';
	import { buildHierarchy, siteNodeId, type HierarchyGraph } from './layout.ts';

	const { index }: { index: TopologyIndex } = $props();

	const DEVICE_FOCUS_ZOOM = 1.4;
	// Every link's interface labels show from this zoom; below it, only the selection's.
	const LABEL_ZOOM = 2;

	let container: HTMLDivElement;
	let cy = $state.raw<Core | null>(null);
	let edgeOfLink = new Map<string, string>();
	let lastFocus = ui.focusRequest;
	let placed = false;

	const style: StylesheetJson = [
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
			style: {
				opacity: 1,
				'z-index': 5,
				'font-size': 8,
				color: COLOR.text
			}
		},
		{ selector: 'node.selected', style: { 'border-width': 3, 'border-color': COLOR.selected } },
		{
			selector: 'edge.selected',
			style: { 'line-color': COLOR.selected, opacity: 1, 'z-index': 10 }
		}
	];

	onMount(() => {
		const core = cytoscape({
			container,
			style,
			minZoom: 0.02,
			maxZoom: 4,
			autoungrabify: true,
			boxSelectionEnabled: false
		});
		core.on('tap', (e) => {
			if (e.target === core) select(null);
		});
		core.on('tap', 'node', (e) => {
			const { kind, id, site } = e.target.data();
			select(kind === 'device' ? { kind: 'device', id } : { kind: 'site', id: site });
		});
		core.on('tap', 'edge', (e) => select({ kind: 'links', ids: e.target.data('linkIds') }));
		core.on('zoom', () => showLabels(core));
		core.on('dbltap', 'node[kind = "site"], node[kind = "frame"]', (e) => {
			const site: string = e.target.data('site');
			if (!expandedSites.delete(site)) expandedSites.add(site);
		});
		const resize = new ResizeObserver(() => core.resize());
		resize.observe(container);
		cy = core;
		return () => {
			resize.disconnect();
			core.destroy();
		};
	});

	$effect(() => {
		const core = cy;
		if (!core) return;
		const graph = buildHierarchy(index, expandedSites);
		untrack(() => render(core, graph));
	});

	function render(core: Core, graph: HierarchyGraph): void {
		const elements: ElementDefinition[] = [
			...graph.nodes.map((n) => ({
				group: 'nodes' as const,
				data: { ...n, color: n.role ? ROLE_COLOR[n.role] : COLOR.muted },
				position: { x: n.x, y: n.y }
			})),
			...graph.edges.map((e) => ({
				group: 'edges' as const,
				data: { ...e, width: Math.min(6, 1 + 1.5 * Math.log10(e.capacityMbps / 1000 + 1)) }
			}))
		];
		edgeOfLink = new Map(graph.edges.flatMap((e) => e.linkIds.map((id) => [id, e.id] as const)));
		core.batch(() => {
			core.elements().remove();
			core.add(elements);
		});
		markSelection(core, ui.selection);
		showLabels(core, true);
		if (!placed) {
			placed = true;
			if (ui.selection) void focus(core, ui.selection);
			else core.fit(undefined, 40);
		}
	}

	$effect(() => {
		const core = cy;
		const selection = ui.selection;
		if (core) markSelection(core, selection);
	});

	$effect(() => {
		const request = ui.focusRequest;
		const core = cy;
		if (!core || request === lastFocus) return;
		lastFocus = request;
		untrack(() => ui.selection && focus(core, ui.selection));
	});

	function selected(core: Core, selection: Selection | null) {
		if (selection?.kind === 'device') {
			const node = core.getElementById(selection.id);
			return node.nonempty() ? node : core.getElementById(siteNodeId(siteOf(index, selection.id)));
		}
		if (selection?.kind === 'site') return core.getElementById(siteNodeId(selection.id));
		const ids = new Set(selection?.ids.map((id) => edgeOfLink.get(id)));
		return core.edges().filter((e) => ids.has(e.id()));
	}

	let labelsShown = false;

	function showLabels(core: Core, force = false): void {
		const show = core.zoom() >= LABEL_ZOOM;
		if (show === labelsShown && !force) return;
		labelsShown = show;
		core.edges().toggleClass('labels', show);
	}

	function markSelection(core: Core, selection: Selection | null): void {
		core.elements('.selected').removeClass('selected');
		core.edges('.context').removeClass('context');
		const eles = selected(core, selection);
		eles.addClass('selected');
		// Label the selected device's links (or the selected links) at a readable zoom.
		(selection?.kind === 'device' ? eles.connectedEdges() : eles.edges()).addClass('context');
	}

	async function focus(core: Core, selection: Selection): Promise<void> {
		if (selection.kind === 'device') {
			const site = siteOf(index, selection.id);
			if (!expandedSites.has(site)) {
				expandedSites.add(site);
				await tick();
			}
			const node = core.getElementById(selection.id);
			core.animate({
				zoom: Math.max(core.zoom(), DEVICE_FOCUS_ZOOM),
				center: { eles: node }
			});
			return;
		}
		const eles = selected(core, selection);
		if (eles.nonempty()) {
			core.animate({ fit: { eles: eles.union(eles.connectedNodes()), padding: 80 } });
		}
	}

	function setAll(expand: boolean): void {
		for (const site of index.topology.sites) {
			if (expand) expandedSites.add(site.code);
			else expandedSites.delete(site.code);
		}
	}
</script>

<div class="graph" bind:this={container}></div>
<div class="tools">
	<button onclick={() => setAll(true)}>Expand all</button>
	<button onclick={() => setAll(false)}>Collapse all</button>
	<button onclick={() => cy?.animate({ fit: { eles: cy.elements(), padding: 40 } })}>Fit</button>
	<span class="hint">Double-click a site to expand or collapse it</span>
</div>

<style>
	.graph {
		position: absolute;
		inset: 0;
	}
	.tools {
		position: absolute;
		top: 12px;
		left: 12px;
		display: flex;
		align-items: center;
		gap: 6px;
	}
	.hint {
		color: var(--muted);
		font-size: 12px;
		margin-left: 6px;
	}
</style>
