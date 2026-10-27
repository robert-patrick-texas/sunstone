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
	import Legend from '#lib/Legend.svelte';
	import SearchBox from '#lib/SearchBox.svelte';
	import { expandedSites, select, ui, type View } from '#lib/state.svelte.ts';
	import { indexTopology, type TopologyIndex } from '#lib/topology.ts';

	// Small networks open fully expanded in the hierarchy; larger ones start as one box per site.
	const EXPAND_ALL_UP_TO = 400;
	const VIEWS: { id: View; label: string }[] = [
		{ id: 'geo', label: 'Geographic' },
		{ id: 'hierarchy', label: 'Hierarchy' }
	];

	let index = $state.raw<TopologyIndex | null>(null);
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
		if (e.key === 'Escape' && !(e.target instanceof HTMLInputElement)) select(null);
	}
</script>

<svelte:window onkeydown={onKeydown} />

<div class="app">
	<header>
		<h1><img src="/favicon.svg" alt="" width="22" height="22" />Sunstone</h1>
		<div class="views" role="group" aria-label="View">
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
						<GeoView {index} />
					{:else}
						<HierarchyView {index} />
					{/if}
				{/key}
				<Legend />
			</section>
			<DetailsPanel {index} />
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
	.views {
		display: flex;
	}
	.views button {
		border-radius: 0;
	}
	.views button:first-child {
		border-radius: 6px 0 0 6px;
	}
	.views button:last-child {
		border-radius: 0 6px 6px 0;
		border-left: none;
	}
	.views button[aria-pressed='true'] {
		background: var(--accent);
		border-color: var(--accent);
		color: #1a1300;
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
		overflow: hidden;
	}
	.message {
		padding: 24px;
		color: var(--muted);
	}
</style>
