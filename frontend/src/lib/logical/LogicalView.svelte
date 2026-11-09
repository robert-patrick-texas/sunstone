<!--
@component
The logical view: the named networks chosen in the header, or every one,
without geography. Sites are boxes; double-click one to see its devices in
those networks, and double-click its frame to fold it again. Transports,
fabrics, and external nodes have places of their own, and so does each
resource with any member drawn, in its status color in live state. What the
networks shown ride is drawn faintly beneath, unless turned off. In live
state, tunnels spokes have built to each other are drawn too, and come and
go without moving the view. Finished layouts are kept while the page is open.
-->
<script module lang="ts">
	import type { Position } from 'cytoscape';

	const CACHE_SIZE = 20;
	const layoutCache = new Map<string, Map<string, Position>>();

	function remember(key: string, positions: Map<string, Position>): void {
		layoutCache.delete(key);
		layoutCache.set(key, positions);
		const oldest = layoutCache.keys().next().value;
		if (layoutCache.size > CACHE_SIZE && oldest !== undefined) layoutCache.delete(oldest);
	}
</script>

<script lang="ts">
	import { onMount, untrack } from 'svelte';
	import type { NodeSingular } from 'cytoscape';
	import type { StatusReport } from '../api/status.ts';
	import { GraphCanvas } from '../graph/canvas.ts';
	import { hiddenKey } from '../graph/drawn.ts';
	import type { Impact } from '../impact.ts';
	import type { LiveIndex } from '../live.ts';
	import type { PathResult } from '../paths.ts';
	import { timedAsync } from '../perf.ts';
	import { logical, logicalExpanded, ui, type AnySelection } from '../state.svelte.ts';
	import { term } from '../terms.ts';
	import type { TopologyIndex } from '../topology.ts';
	import { layoutInWorker, Superseded } from '../topo/worker.ts';
	import {
		logicalGraph,
		type BuiltTunnel,
		type LogicalGraph,
		type ResourceState
	} from './graph.ts';

	const {
		index,
		path,
		impact,
		live,
		status: report
	}: {
		index: TopologyIndex;
		path: PathResult | null;
		impact: Impact | null;
		live: LiveIndex | null;
		/** Every network's and resource's status, while live state is shown. */
		status: StatusReport | null;
	} = $props();

	let container: HTMLDivElement;
	let canvas = $state.raw<GraphCanvas | null>(null);
	let busy = $state(false);
	let unplaced = $state(false);
	let layoutProblem = $state<string | null>(null);
	let lastFocus = ui.focusRequest;
	let lastFit = ui.fitRequest;
	let draws = 0;
	/** The layout last drawn, so a redraw of the same one keeps the zoom. */
	let lastDrawn: string | null = null;

	// As a key first, so the graph is built again only when the tunnels up change.
	const builtKey = $derived(
		JSON.stringify(
			[...(live?.tunnels.values() ?? [])]
				.filter((t) => t.dynamic && t.status === 'up')
				.map((t) => ({ tunnel: t.tunnel, network: t.network }))
				.sort((x, y) => x.tunnel.localeCompare(y.tunnel))
		)
	);
	const built = $derived(JSON.parse(builtKey) as BuiltTunnel[]);
	// The same for resources: built again only when one's status changes.
	const statesKey = $derived(
		JSON.stringify(report?.resources.map((r) => ({ name: r.name, status: r.status })) ?? [])
	);
	const states = $derived(JSON.parse(statesKey) as ResourceState[]);
	const graph: LogicalGraph = $derived(
		logicalGraph(index, ui.networks, logicalExpanded, logical.under, built, states)
	);
	// What is hidden from the map is part of the key: a layout without it has no place for it.
	const key = $derived(
		JSON.stringify([ui.networks, logical.under, [...logicalExpanded].sort(), hiddenKey()])
	);
	const status = $derived.by(() => {
		const words = term(index, 'network', true).toLowerCase();
		if (graph.shown.length === 0) return '';
		const what = ui.networks.length ? graph.shown.join(', ') : `All ${words}`;
		const under = graph.under.length ? ` · over ${graph.under.join(', ')}, faintly` : '';
		const sites = graph.nodes.filter((n) => n.kind === 'site' || n.kind === 'frame').length;
		const spoke = graph.edges.reduce((n, e) => n + (e.dynamic ? (e.tunnels?.length ?? 0) : 0), 0);
		return `${what}${under} · ${sites} sites${spoke ? ` · ${spoke} spoke to spoke now` : ''}`;
	});

	onMount(() => {
		const c = new GraphCanvas(container, index, { grabbable: true, onDoubleTap });
		c.core.on('dragfree', 'node', () => remember(key, c.positions()));
		canvas = c;
		return () => c.destroy();
	});

	$effect(() => {
		const c = canvas;
		const g = graph;
		const k = key;
		if (c) untrack(() => void draw(c, g, k));
	});

	$effect(() => {
		canvas?.highlight(ui.selection, path, impact);
	});

	$effect(() => {
		canvas?.setLive(live);
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
		untrack(() => ui.selection && focusOn(c, ui.selection));
	});

	async function draw(c: GraphCanvas, g: LogicalGraph, k: string): Promise<void> {
		const run = ++draws;
		layoutProblem = null;
		const cached = layoutCache.get(k);
		c.setGraph(g.nodes, g.edges, cached);
		if (cached) {
			c.fitFrames();
			busy = unplaced = false;
			if (k !== lastDrawn) c.core.fit(undefined, 40);
			lastDrawn = k;
			return;
		}
		busy = unplaced = g.nodes.length > 0;
		if (g.nodes.length === 0) return;
		let positions: Map<string, Position>;
		try {
			positions = await timedAsync('logical layout', () =>
				layoutInWorker({ nodes: g.nodes, edges: g.edges, kind: 'force', roots: [] })
			);
		} catch (e) {
			if (e instanceof Superseded) return;
			busy = unplaced = false;
			layoutProblem = e instanceof Error ? e.message : String(e);
			return;
		}
		if (run !== draws) return;
		c.core.batch(() =>
			c.core.nodes().forEach((n) => {
				const at = positions.get(n.id());
				if (at) n.position(at);
			})
		);
		c.separateBeyond();
		c.fitFrames();
		busy = unplaced = false;
		remember(k, c.positions());
		lastDrawn = k;
		if (ui.selection) focusOn(c, ui.selection);
		else c.core.fit(undefined, 40);
	}

	function focusOn(c: GraphCanvas, selection: AnySelection): void {
		const eles = c.elementsFor(selection);
		if (eles.nonempty()) {
			c.core.animate({ fit: { eles: eles.union(eles.connectedNodes()), padding: 80 } });
		}
	}

	function onDoubleTap(node: NodeSingular): void {
		const { kind, site } = node.data();
		if (kind === 'site') logicalExpanded.add(site);
		else if (kind === 'frame' || kind === 'device') logicalExpanded.delete(site);
	}
</script>

<div class="logical">
	<div class="tools">
		<label title="Draw the networks under the ones shown, faintly">
			<input type="checkbox" bind:checked={logical.under} disabled={ui.networks.length === 0} />
			Show what they ride
		</label>
		<button disabled={logicalExpanded.size === 0} onclick={() => logicalExpanded.clear()}>
			Collapse all
		</button>
		<button
			onclick={() => canvas?.core.animate({ fit: { eles: canvas.core.elements(), padding: 40 } })}
		>
			Fit
		</button>
	</div>
	<p class="status" role="status">{busy ? 'Laying out…' : (layoutProblem ?? status)}</p>
	<div class="graph" class:unplaced bind:this={container}></div>
	{#if index.topology.networks.length === 0}
		<p class="empty">
			This topology names no {term(index, 'network', true).toLowerCase()}. Give it networks,
			transports, tunnels, and fabrics, as the layered sample does, to see them here.
		</p>
	{/if}
</div>

<style>
	.logical {
		position: absolute;
		inset: 0;
		display: flex;
		flex-direction: column;
	}
	.tools {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 6px 10px;
		padding: 12px 60px 0 12px;
	}
	label {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		color: var(--muted);
	}
	.status {
		margin: 6px 12px 0;
		color: var(--muted);
		font-size: 12px;
		min-height: 1.4em;
	}
	.graph {
		position: relative;
		flex: 1;
		min-height: 0;
	}
	.graph.unplaced {
		visibility: hidden;
	}
	.empty {
		position: absolute;
		top: 40%;
		left: 50%;
		transform: translateX(-50%);
		max-width: 420px;
		text-align: center;
		color: var(--muted);
	}
</style>
