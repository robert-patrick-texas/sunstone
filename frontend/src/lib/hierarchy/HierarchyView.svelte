<!--
@component
Top-down hierarchy view. Sites are boxes until expanded (double-click, or
the details panel); expanded sites show devices in tier rows.
-->
<script lang="ts">
	import { onMount, tick, untrack } from 'svelte';
	import { GraphCanvas } from '../graph/canvas.ts';
	import { expandedSites, ui, type Selection } from '../state.svelte.ts';
	import { siteOf, type TopologyIndex } from '../topology.ts';
	import { buildHierarchy } from './layout.ts';

	const { index }: { index: TopologyIndex } = $props();

	const DEVICE_FOCUS_ZOOM = 1.4;

	let container: HTMLDivElement;
	let canvas = $state.raw<GraphCanvas | null>(null);
	let lastFocus = ui.focusRequest;
	let placed = false;

	onMount(() => {
		const c = new GraphCanvas(container, index, {
			grabbable: false,
			onDoubleTap: (node) => {
				if (node.data('kind') === 'device') return;
				const site: string = node.data('site');
				if (!expandedSites.delete(site)) expandedSites.add(site);
			}
		});
		canvas = c;
		return () => c.destroy();
	});

	$effect(() => {
		const c = canvas;
		if (!c) return;
		const graph = buildHierarchy(index, expandedSites);
		untrack(() => {
			c.setGraph(graph.nodes, graph.edges);
			c.mark(ui.selection);
			if (placed) return;
			placed = true;
			if (ui.selection) void focus(c, ui.selection);
			else c.core.fit(undefined, 40);
		});
	});

	$effect(() => {
		const selection = ui.selection;
		canvas?.mark(selection);
	});

	$effect(() => {
		const request = ui.focusRequest;
		const c = canvas;
		if (!c || request === lastFocus) return;
		lastFocus = request;
		untrack(() => ui.selection && focus(c, ui.selection));
	});

	async function focus(c: GraphCanvas, selection: Selection): Promise<void> {
		if (selection.kind === 'device') {
			const site = siteOf(index, selection.id);
			if (!expandedSites.has(site)) {
				expandedSites.add(site);
				await tick();
			}
			c.core.animate({
				zoom: Math.max(c.core.zoom(), DEVICE_FOCUS_ZOOM),
				center: { eles: c.core.getElementById(selection.id) }
			});
			return;
		}
		const eles = c.elementsFor(selection);
		if (eles.nonempty()) {
			c.core.animate({ fit: { eles: eles.union(eles.connectedNodes()), padding: 80 } });
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
	<button
		onclick={() => canvas?.core.animate({ fit: { eles: canvas.core.elements(), padding: 40 } })}
	>
		Fit
	</button>
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
