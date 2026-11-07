<!--
@component
Choose which named networks every view shows: none for the network as a
whole, or one or more (blue and black together, say). Networks are listed
from the bottom of the stack up, each with what it rides and its color, which
says how deep it sits. A network's name selects it.
-->
<script lang="ts">
	import { layersOf } from './layers.ts';
	import { select, ui } from './state.svelte.ts';
	import { term } from './terms.ts';
	import { depthColor } from './theme.ts';
	import { compareNatural, type TopologyIndex } from './topology.ts';

	const { index }: { index: TopologyIndex } = $props();

	let root: HTMLDivElement;
	let open = $state(false);
	const layers = $derived(layersOf(index));
	const networks = $derived(
		[...layers.slices.values()].sort((x, y) => x.depth - y.depth || compareNatural(x.name, y.name))
	);
	const label = $derived(
		ui.networks.length === 0
			? term(index, 'network', true)
			: ui.networks.length <= 2
				? ui.networks.join(', ')
				: `${ui.networks.length} ${term(index, 'network', true).toLowerCase()}`
	);

	function toggle(name: string): void {
		ui.networks = ui.networks.includes(name)
			? ui.networks.filter((n) => n !== name)
			: [...ui.networks, name];
	}

	function onWindowClick(e: MouseEvent): void {
		if (open && e.target instanceof Node && !root.contains(e.target)) open = false;
	}
</script>

<svelte:window onclick={onWindowClick} />

<div class="menu" bind:this={root}>
	<button
		aria-expanded={open}
		aria-pressed={ui.networks.length > 0}
		title="Show named networks in every view"
		onclick={() => (open = !open)}
	>
		{label}
	</button>
	{#if open}
		<div class="popover" role="dialog" aria-label={term(index, 'network', true)}>
			<p class="hint">
				Show in every view. Each is colored by how deep it sits: over the circuits, over another, or
				deeper.
			</p>
			<ul>
				{#each networks as n (n.name)}
					<li>
						<label>
							<input
								type="checkbox"
								checked={ui.networks.includes(n.name)}
								onchange={() => toggle(n.name)}
							/>
							<span class="dot" style:--depth={depthColor(n.depth)}></span>
						</label>
						<button
							class="name"
							onclick={() => {
								select({ kind: 'network', id: n.name }, true);
								open = false;
							}}>{n.name}</button
						>
						<span class="hint">
							{n.rides.size ? `over ${[...n.rides].sort(compareNatural).join(', ')}` : 'circuits'}
							· {n.sites.size} sites
						</span>
					</li>
				{/each}
			</ul>
			<p class="actions">
				<button disabled={ui.networks.length === 0} onclick={() => (ui.networks = [])}>
					Whole network
				</button>
				<button
					onclick={() => {
						ui.view = 'logical';
						open = false;
					}}
					disabled={ui.view === 'logical'}>Logical view</button
				>
			</p>
		</div>
	{/if}
</div>

<style>
	.menu {
		position: relative;
	}
	.popover {
		position: absolute;
		top: calc(100% + 6px);
		left: 0;
		z-index: 20;
		width: 320px;
		padding: 10px;
		background: var(--panel);
		border: 1px solid var(--border);
		border-radius: 8px;
		box-shadow: 0 8px 24px rgb(0 0 0 / 0.4);
	}
	ul {
		list-style: none;
		margin: 8px 0;
		padding: 0;
		max-height: 340px;
		overflow-y: auto;
	}
	li {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 2px 0;
	}
	label {
		display: flex;
		align-items: center;
		gap: 6px;
	}
	.dot {
		width: 10px;
		height: 10px;
		border-radius: 50%;
		background: var(--depth);
	}
	.name {
		border: none;
		background: none;
		padding: 0;
		color: var(--text);
		font-weight: 600;
	}
	.name:hover {
		text-decoration: underline;
	}
	.hint {
		color: var(--muted);
		font-size: 12px;
		margin: 0;
	}
	.actions {
		display: flex;
		gap: 6px;
		margin: 4px 0 0;
	}
</style>
