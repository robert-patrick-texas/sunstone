<!--
@component
The app: header with view switch and search, the current view, the legend,
and the details panel for whatever is selected.
-->
<script lang="ts">
	import '../app.css';
	import { onMount } from 'svelte';
	import { fetchTopology } from '#lib/api/topology.ts';
	import DetailsPanel from '#lib/DetailsPanel.svelte';
	import GeoView from '#lib/geo/GeoView.svelte';
	import HierarchyView from '#lib/hierarchy/HierarchyView.svelte';
	import TopologyView from '#lib/topo/TopologyView.svelte';
	import Legend from '#lib/Legend.svelte';
	import { shortestPaths } from '#lib/paths.ts';
	import SearchBox from '#lib/SearchBox.svelte';
	import { expandedSites, select, ui, type View } from '#lib/state.svelte.ts';
	import { indexTopology, type TopologyIndex } from '#lib/topology.ts';

	// Small networks open fully expanded in the hierarchy; larger ones start as one box per site.
	const EXPAND_ALL_UP_TO = 400;
	const VIEWS: { id: View; label: string }[] = [
		{ id: 'geo', label: 'Geographic' },
		{ id: 'hierarchy', label: 'Hierarchy' },
		{ id: 'topology', label: 'Topology' }
	];

	let index = $state.raw<TopologyIndex | null>(null);
	const path = $derived(index && ui.path ? shortestPaths(index, ui.path.from, ui.path.to) : null);
	let problem = $state<string | null>(null);

	onMount(async () => {
		try {
			const topology = await fetchTopology();
			if (topology.devices.length <= EXPAND_ALL_UP_TO) {
				for (const site of topology.sites) expandedSites.add(site.code);
			}
			index = indexTopology(topology);
		} catch (e) {
			problem = e instanceof Error ? e.message : String(e);
		}
	});

	function onKeydown(e: KeyboardEvent): void {
		if (e.key !== 'Escape' || e.target instanceof HTMLInputElement) return;
		// Escape first cancels choosing a path's destination, then clears the selection.
		if (ui.pathFrom) ui.pathFrom = null;
		else select(null);
	}
</script>

<svelte:window onkeydown={onKeydown} />

<div class="app">
	<header>
		<h1><img src="/favicon.svg" alt="" width="22" height="22" />Sunstone</h1>
		<div class="segmented" role="group" aria-label="View">
			{#each VIEWS as view (view.id)}
				<button aria-pressed={ui.view === view.id} onclick={() => (ui.view = view.id)}>
					{view.label}
				</button>
			{/each}
		</div>
		{#if index}
			<SearchBox {index} />
			<span class="stats">
				{index.topology.sites.length} sites · {index.topology.devices.length} devices ·
				{index.topology.links.length} links
			</span>
		{/if}
	</header>
	<main>
		{#if problem}
			<p class="message">Could not load the topology: {problem}</p>
		{:else if !index}
			<p class="message">Loading topology…</p>
		{:else}
			<section class="view">
				{#key ui.view}
					{#if ui.view === 'geo'}
						<GeoView {index} {path} />
					{:else if ui.view === 'hierarchy'}
						<HierarchyView {index} {path} />
					{:else}
						<TopologyView {index} {path} />
					{/if}
				{/key}
				<Legend />
				{#if ui.pathFrom}
					<p class="picking" aria-live="polite">
						Choose the destination for a path from <strong>{ui.pathFrom}</strong>: click a device or
						search. Esc cancels.
					</p>
				{/if}
			</section>
			<DetailsPanel {index} {path} />
		{/if}
	</main>
</div>

<style>
	.app {
		display: flex;
		flex-direction: column;
		height: 100%;
	}
	header {
		display: flex;
		align-items: center;
		gap: 16px;
		padding: 8px 14px;
		background: var(--panel);
		border-bottom: 1px solid var(--border);
	}
	h1 {
		display: flex;
		align-items: center;
		gap: 8px;
		margin: 0;
		font-size: 17px;
		font-weight: 600;
		letter-spacing: 0.02em;
	}
	.stats {
		margin-left: auto;
		color: var(--muted);
		font-size: 12px;
		white-space: nowrap;
	}
	main {
		display: flex;
		flex: 1;
		min-height: 0;
	}
	.view {
		position: relative;
		flex: 1;
		min-width: 0;
		/* clip, not hidden: a hidden overflow can still be scrolled, for example
		   by focusing a field in a popover that pokes past the edge. */
		overflow: clip;
	}
	.picking {
		position: absolute;
		bottom: 56px;
		left: 50%;
		transform: translateX(-50%);
		margin: 0;
		padding: 8px 14px;
		background: var(--panel);
		border: 1px solid var(--path);
		border-radius: 6px;
		box-shadow: 0 8px 24px rgb(0 0 0 / 0.4);
	}
	.message {
		padding: 24px;
		color: var(--muted);
	}
</style>
