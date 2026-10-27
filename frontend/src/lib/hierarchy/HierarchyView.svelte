<!--
@component
Top-down hierarchy view. Sites are boxes until expanded (double-click, or
the details panel); expanded sites show devices in tier rows.
-->
<script lang="ts">
	import { onMount, tick, untrack } from 'svelte';
	import { GraphCanvas } from '../graph/canvas.ts';
	import type { Impact } from '../impact.ts';
	import type { LiveIndex } from '../live.ts';
	import type { PathResult } from '../paths.ts';
	import { timed } from '../perf.ts';
	import { expandedSites, ui, type Selection } from '../state.svelte.ts';
	import { siteOf, type TopologyIndex } from '../topology.ts';
	import { buildHierarchy } from './layout.ts';

	const {
		index,
		path,
		impact,
		live
	}: {
		index: TopologyIndex;
		path: PathResult | null;
		impact: Impact | null;
		live: LiveIndex | null;
	} = $props();

	const DEVICE_FOCUS_ZOOM = 1.4;

	let container: HTMLDivElement;
	let canvas = $state.raw<GraphCanvas | null>(null);
	let lastFocus = ui.focusRequest;
	let lastFit = ui.fitRequest;
	let lastPath = untrack(() => path);
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
		const graph = timed('hierarchy layout', () => buildHierarchy(index, expandedSites));
		untrack(() => {
			c.setGraph(graph.nodes, graph.edges);
			if (placed) return;
			placed = true;
			// On opening, a shown path matters more than the selection (often its end).
			const onPath = path ? c.pathElements(path) : null;
			if (onPath?.nonempty()) c.core.fit(onPath, 80);
			else if (ui.selection) void focus(c, ui.selection);
			else c.core.fit(undefined, 40);
		});
	});

	$effect(() => {
		canvas?.highlight(ui.selection, path, impact);
	});

	$effect(() => {
		canvas?.setLive(live);
	});

	// A newly shown path is brought into view.
	$effect(() => {
		const [c, p] = [canvas, path];
		if (!c || p === lastPath) return;
		lastPath = p;
		const eles = p ? untrack(() => c.pathElements(p)) : null;
		if (eles?.nonempty()) c.core.animate({ fit: { eles, padding: 80 } });
	});

	$effect(() => {
		const request = ui.fitRequest;
		const c = canvas;
		if (!c || request === lastFit) return;
		lastFit = request;
		c.core.animate({ fit: { eles: c.core.elements(), padding: 40 } });
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
