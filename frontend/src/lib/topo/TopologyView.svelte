<!--
@component
Automatic layouts of the whole network, or of the neighborhood around a
device or site: force-directed (optionally grouped by site) or radial by
hops. Double-click a device to re-center the neighborhood on it, or a site
box to expand it. Nodes can be dragged; finished layouts are kept, so
returning to the view shows the same picture, and can be saved by name to
the backend and opened again later.
-->
<script module lang="ts">
	import type { Position } from 'cytoscape';

	const CACHE_SIZE = 30;
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
	import { GraphCanvas } from '../graph/canvas.ts';
	import type { LayoutIn, SavedLayout } from '../api/layouts.ts';
	import type { PathResult } from '../paths.ts';
	import { siteNodeId } from '../graph/model.ts';
	import { expandedSites, select, topo, ui, type Selection } from '../state.svelte.ts';
	import { siteOf, type TopologyIndex } from '../topology.ts';
	import { neighborhoodGraph, networkGraph, pathGraph, type TopoGraph } from './graph.ts';
	import LayoutMenu from './LayoutMenu.svelte';
	import { REFINE_UP_TO, runLayout, SITEWISE_ABOVE } from './layouts.ts';
	import { neighborhood, seedsOf } from './neighborhood.ts';

	const { index, path }: { index: TopologyIndex; path: PathResult | null } = $props();

	const LIMIT = 400;
	const HOPS = [1, 2, 3, 4];
	const DEVICE_FOCUS_ZOOM = 1.4;

	let container: HTMLDivElement;
	let canvas = $state.raw<GraphCanvas | null>(null);
	let busy = $state(false);
	let sitewise = $state(false);
	let lastFocus = ui.focusRequest;
	let lastPath = untrack(() => path);
	let pendingFocus = false;
	let placed = false;
	let draws = 0;
	let lastFamily: string | null = null;
	let currentKey = '';

	const framed = $derived(topo.grouped && topo.layout === 'force');
	const hood = $derived(
		topo.scope === 'neighborhood'
			? neighborhood(index, seedsOf(index, topo.center), topo.hops, LIMIT)
			: null
	);
	const graph: TopoGraph | null = $derived.by(() => {
		if (topo.scope === 'path') return path?.hops != null ? pathGraph(index, path, framed) : null;
		if (!hood) return networkGraph(index, expandedSites, framed);
		return hood.hops.size > 0 ? neighborhoodGraph(index, hood, framed) : null;
	});
	// Settings apart from which sites are expanded: within one family, expanding
	// a site adjusts the current picture instead of starting a new one.
	const family = $derived(
		JSON.stringify([
			topo.scope,
			topo.layout,
			framed,
			topo.scope === 'neighborhood' ? [topo.center, topo.hops] : null,
			topo.scope === 'path' ? [path?.from, path?.to] : null
		])
	);
	const key = $derived(
		topo.scope === 'network' ? `${family}|${[...expandedSites].sort().join(',')}` : family
	);
	const status = $derived.by(() => {
		if (topo.scope === 'path') {
			if (!path) return '';
			if (path.hops === null) return `${path.from} and ${path.to} are not connected`;
			const paths = path.count === 1 ? '1 path' : `${path.count} equal-length paths`;
			return `${path.from} → ${path.to} · ${path.hops} hops · ${paths} · ${path.devices.size} devices`;
		}
		if (!hood) {
			const text = `${index.topology.sites.length} sites, ${expandedSites.size} expanded`;
			return sitewise ? `${text} · laid out site by site above ${SITEWISE_ABOVE} nodes` : text;
		}
		if (hood.hops.size === 0) return '';
		const hops = `${hood.reached} ${hood.reached === 1 ? 'hop' : 'hops'}`;
		const text = `${centerName(topo.center)} · ${hops} · ${hood.hops.size} devices`;
		if (!hood.cut) return text;
		return `${text} — hop ${hood.reached + 1} would add ${hood.cut} more (limit ${LIMIT})`;
	});

	onMount(() => {
		const c = new GraphCanvas(container, index, { grabbable: true, onDoubleTap });
		c.core.on('dragfree', 'node', () => remember(currentKey, c.positions()));
		canvas = c;
		return () => c.destroy();
	});

	$effect(() => {
		const c = canvas;
		const g = graph;
		const k = key;
		const f = family;
		if (c) untrack(() => void draw(c, g, k, f));
	});

	$effect(() => {
		canvas?.highlight(ui.selection, path);
	});

	// A newly shown path is brought into view (the path scope fits it when drawn).
	$effect(() => {
		const [c, p] = [canvas, path];
		if (!c || p === lastPath) return;
		lastPath = p;
		if (!p || topo.scope === 'path') return;
		const eles = untrack(() => c.pathElements(p));
		if (eles.nonempty()) c.core.animate({ fit: { eles, padding: 80 } });
	});

	$effect(() => {
		const request = ui.focusRequest;
		const c = canvas;
		if (!c || request === lastFocus) return;
		lastFocus = request;
		untrack(() => ui.selection && onFocusRequest(c, ui.selection));
	});

	async function draw(c: GraphCanvas, g: TopoGraph | null, k: string, f: string): Promise<void> {
		const run = ++draws;
		currentKey = k;
		if (!g) {
			busy = false;
			c.setGraph([], []);
			return;
		}
		const cached = layoutCache.get(k);
		const incremental = !cached && f === lastFamily && g.nodes.length <= REFINE_UP_TO;
		lastFamily = f;
		// A saved layout may predate devices added since; seeded() places them by their site.
		const start = cached ?? (incremental ? c.positions() : undefined);
		c.setGraph(g.nodes, g.edges, start && seeded(g, start));
		c.core
			.nodes()
			.filter((n) => n.data('hop') === 0)
			.addClass('center');
		busy = !cached;
		sitewise = topo.layout === 'force' && g.nodes.length > SITEWISE_ABOVE;
		if (!cached) {
			// Let "Laying out…" paint before the layout blocks the page.
			await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
			if (run !== draws) return;
			const kind = topo.layout === 'force' ? 'force' : topo.scope === 'path' ? 'layered' : 'radial';
			runLayout(c.core, index, g, kind, incremental);
			busy = false;
			remember(k, c.positions());
		}
		if (topo.layout === 'radial' && topo.scope === 'neighborhood') addRings(c);
		if (pendingFocus || (!placed && ui.selection && topo.scope === 'network')) {
			pendingFocus = false;
			if (ui.selection) focusOn(c, ui.selection);
		} else {
			c.core.fit(undefined, 40);
		}
		placed = true;
	}

	/** Start new nodes where the site box they came out of was, so the picture keeps its shape. */
	function seeded(g: TopoGraph, before: Map<string, Position>): Map<string, Position> {
		const positions = new Map<string, Position>();
		for (const n of g.nodes) {
			const own = before.get(n.id);
			const site = before.get(siteNodeId(n.site));
			if (own) positions.set(n.id, own);
			else if (site) {
				positions.set(n.id, {
					x: site.x + Math.random() * 60 - 30,
					y: site.y + Math.random() * 60 - 30
				});
			}
		}
		return positions;
	}

	/** Faint labeled circles behind a radial neighborhood, one per hop. */
	function addRings(c: GraphCanvas): void {
		const centers = c.core.nodes('.center');
		if (centers.empty()) return;
		const mid = centers.boundingBox();
		const at = { x: (mid.x1 + mid.x2) / 2, y: (mid.y1 + mid.y2) / 2 };
		const radius = new Map<number, number>();
		c.core.nodes('[hop > 0]').forEach((n) => {
			const { x, y } = n.position();
			const hop: number = n.data('hop');
			radius.set(hop, Math.max(radius.get(hop) ?? 0, Math.hypot(x - at.x, y - at.y)));
		});
		c.core.add(
			[...radius].map(([hop, r]) => ({
				group: 'nodes' as const,
				data: {
					id: `ring:${hop}`,
					kind: 'ring',
					label: hop === 1 ? '1 hop' : `${hop} hops`,
					d: 2 * r
				},
				position: at,
				selectable: false,
				grabbable: false
			}))
		);
	}

	function onDoubleTap(node: NodeSingular): void {
		const { kind, id, site } = node.data();
		if (kind === 'device') {
			select({ kind: 'device', id });
			topo.center = { kind: 'device', id };
			topo.scope = 'neighborhood';
		} else if (topo.scope === 'network') {
			if (!expandedSites.delete(site)) expandedSites.add(site);
		} else {
			topo.center = { kind: 'site', id: site };
		}
	}

	function onFocusRequest(c: GraphCanvas, selection: Selection): void {
		if (topo.scope === 'neighborhood' && selection.kind !== 'links') {
			// Search in a neighborhood moves the neighborhood; the redraw fits it.
			if (JSON.stringify(topo.center) !== JSON.stringify(selection)) {
				topo.center = selection;
				return;
			}
		} else if (topo.scope === 'network' && selection.kind === 'device') {
			const site = siteOf(index, selection.id);
			if (!expandedSites.has(site)) {
				pendingFocus = true;
				expandedSites.add(site);
				return;
			}
		}
		focusOn(c, selection);
	}

	function focusOn(c: GraphCanvas, selection: Selection): void {
		const eles = c.elementsFor(selection);
		if (eles.empty()) return;
		if (selection.kind === 'device') {
			c.core.animate({ zoom: Math.max(c.core.zoom(), DEVICE_FOCUS_ZOOM), center: { eles } });
		} else {
			c.core.animate({ fit: { eles: eles.union(eles.connectedNodes()), padding: 80 } });
		}
	}

	function centerName(center: Selection | null): string {
		if (center?.kind === 'device') return center.id;
		if (center?.kind === 'site') return `Site ${center.id}`;
		return center ? `${center.ids.length} links` : '';
	}

	function toNeighborhood(): void {
		if (ui.selection) topo.center = ui.selection;
		topo.scope = 'neighborhood';
	}

	/** The current settings and node positions, for saving. */
	function snapshot(): LayoutIn {
		const positions = [...(canvas?.positions() ?? [])].filter(([id]) => !id.startsWith('ring:'));
		return {
			settings: {
				scope: topo.scope,
				layout: topo.layout,
				grouped: topo.grouped,
				hops: topo.hops,
				center: topo.scope === 'neighborhood' ? topo.center : null,
				path: topo.scope === 'path' && ui.path ? { ...ui.path } : null,
				expanded: [...expandedSites]
			},
			positions: Object.fromEntries(positions)
		};
	}

	/** Apply a saved layout's settings and draw its positions. */
	function restore(saved: SavedLayout): void {
		const { settings } = saved;
		topo.scope = settings.scope;
		topo.layout = settings.layout;
		topo.grouped = settings.grouped;
		topo.hops = settings.hops;
		topo.center = settings.center ?? null;
		if (settings.path) ui.path = { from: settings.path.from, to: settings.path.to };
		expandedSites.clear();
		for (const code of settings.expanded ?? []) expandedSites.add(code);
		// key and graph now reflect the restored settings; seed the cache so the
		// redraw uses the saved positions instead of running a layout.
		remember(key, new Map(Object.entries(saved.positions)));
		lastFamily = null;
		if (canvas && key === currentKey) void draw(canvas, graph, key, family);
	}

	function relayout(): void {
		layoutCache.delete(key);
		lastFamily = null;
		if (canvas) void draw(canvas, graph, key, family);
	}

	function setAll(expand: boolean): void {
		for (const site of index.topology.sites) {
			if (expand) expandedSites.add(site.code);
			else expandedSites.delete(site.code);
		}
	}
</script>

<div class="topology">
	<div class="tools">
		<div class="segmented" role="group" aria-label="Scope">
			<button aria-pressed={topo.scope === 'network'} onclick={() => (topo.scope = 'network')}>
				Whole network
			</button>
			<button aria-pressed={topo.scope === 'neighborhood'} onclick={toNeighborhood}>
				Neighborhood
			</button>
			<button aria-pressed={topo.scope === 'path'} onclick={() => (topo.scope = 'path')}>
				Path
			</button>
		</div>
		{#if topo.scope === 'neighborhood'}
			<label>
				Hops
				<select bind:value={topo.hops}>
					{#each HOPS as hops (hops)}<option value={hops}>{hops}</option>{/each}
				</select>
			</label>
		{:else if topo.scope === 'network'}
			<button onclick={() => setAll(true)}>Expand all</button>
			<button onclick={() => setAll(false)}>Collapse all</button>
		{/if}
		<div class="segmented" role="group" aria-label="Layout">
			<button aria-pressed={topo.layout === 'force'} onclick={() => (topo.layout = 'force')}>
				Force-directed
			</button>
			<button aria-pressed={topo.layout === 'radial'} onclick={() => (topo.layout = 'radial')}>
				{topo.scope === 'path' ? 'Layered' : 'Radial'}
			</button>
		</div>
		<label title="Applies to the force-directed layout">
			<input type="checkbox" bind:checked={topo.grouped} disabled={topo.layout !== 'force'} />
			Group by site
		</label>
		<button onclick={relayout}>Re-layout</button>
		<LayoutMenu {snapshot} onOpen={restore} />
		<button
			onclick={() => canvas?.core.animate({ fit: { eles: canvas.core.elements(), padding: 40 } })}
		>
			Fit
		</button>
	</div>
	<p class="status" role="status">{busy ? 'Laying out…' : status}</p>
	<div class="graph" bind:this={container}></div>
	{#if topo.scope === 'neighborhood' && !graph}
		<p class="empty">
			Select a device or site, then choose Neighborhood. Double-clicking a device anywhere in this
			view also opens its neighborhood.
		</p>
	{:else if topo.scope === 'path' && !path}
		<p class="empty">
			Choose Path from here on a device in the details panel, then click or search for the
			destination.
		</p>
	{/if}
</div>

<style>
	.topology {
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
	select {
		font: inherit;
		color: var(--text);
		background: var(--panel);
		border: 1px solid var(--border);
		border-radius: 6px;
		padding: 3px 6px;
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
