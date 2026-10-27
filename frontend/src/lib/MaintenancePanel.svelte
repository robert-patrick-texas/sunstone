<!--
@component
Maintenance windows: open now, coming up, and ended in the last day. Each
can show what its work takes down (Check impact), be changed, or be
deleted; deleting asks once more. Planning a new one opens the form, with
the current selection as what it works on.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import { deleteWindow, type Window } from './api/operations.ts';
	import { phaseOf, span, targetName, type Phase } from './maintenance.ts';
	import MaintenanceForm from './MaintenanceForm.svelte';
	import {
		checkImpact,
		localTime,
		planMaintenance,
		select,
		ui,
		type Selection
	} from './state.svelte.ts';
	import type { TopologyIndex } from './topology.ts';

	const {
		index,
		windows,
		problem,
		onchange
	}: {
		index: TopologyIndex;
		windows: Window[];
		/** Why the windows could not be loaded, if they could not. */
		problem: string | null;
		/** Called after a window is saved or deleted, to load them again. */
		onchange: () => void;
	} = $props();

	const DAY_MS = 24 * 60 * 60_000;
	const GROUPS: { phase: Phase; label: string }[] = [
		{ phase: 'open', label: 'Open now' },
		{ phase: 'upcoming', label: 'Coming up' },
		{ phase: 'ended', label: 'Ended in the last day' }
	];

	let now = $state(Date.now());
	let confirming = $state<string | null>(null);
	let failure = $state<string | null>(null);
	const groups = $derived(
		GROUPS.map((g) => ({
			...g,
			items: windows
				.filter((w) => phaseOf(w, now) === g.phase)
				.filter((w) => g.phase !== 'ended' || now - Date.parse(w.end) < DAY_MS)
				.sort((x, y) =>
					g.phase === 'ended' ? y.end.localeCompare(x.end) : x.start.localeCompare(y.start)
				)
		})).filter((g) => g.items.length > 0)
	);

	// Windows open and close as time passes.
	onMount(() => {
		const timer = setInterval(() => (now = Date.now()), 30_000);
		return () => clearInterval(timer);
	});

	function change(w: Window): void {
		ui.planning = {
			id: w.id,
			title: w.title,
			start: localTime(new Date(w.start)),
			end: localTime(new Date(w.end)),
			targets: w.targets,
			note: w.note ?? ''
		};
	}

	async function remove(w: Window): Promise<void> {
		if (confirming !== w.id) {
			confirming = w.id;
			return;
		}
		confirming = null;
		try {
			await deleteWindow(w.id);
			onchange();
		} catch (e) {
			failure = e instanceof Error ? e.message : String(e);
		}
	}

	function follow(target: Selection): void {
		select(target, true);
	}
</script>

<section class="maintenance" aria-label="Maintenance">
	{#if ui.planning}
		<MaintenanceForm {index} onsaved={onchange} />
	{:else}
		<p class="actions">
			<button onclick={() => planMaintenance(ui.selection ? [$state.snapshot(ui.selection)] : [])}>
				Plan maintenance
			</button>
		</p>
		{#if problem}<p class="muted">Maintenance unavailable: {problem}</p>{/if}
		{#if failure}<p class="muted" role="alert">Could not delete: {failure}</p>{/if}
		{#if groups.length === 0 && !problem}
			<p class="muted">No maintenance open, coming up, or ended in the last day.</p>
		{/if}
		{#each groups as group (group.phase)}
			<h3>{group.label} ({group.items.length})</h3>
			<ul>
				{#each group.items as w (w.id)}
					<li class="window" class:open={group.phase === 'open'}>
						<p><b>{w.title}</b></p>
						<p class="muted">{span(w)} · planned by {w.by}</p>
						<p class="targets">
							{#each w.targets as t (JSON.stringify(t))}
								<button class="link" onclick={() => follow(t)}>{targetName(index, t)}</button>
							{/each}
						</p>
						{#if w.note}<p class="note">{w.note}</p>{/if}
						<p class="actions">
							<button onclick={() => checkImpact(w.targets)}>Check impact</button>
							{#if group.phase !== 'ended'}<button onclick={() => change(w)}>Change</button>{/if}
							<button onclick={() => remove(w)}>
								{confirming === w.id ? 'Really delete?' : 'Delete'}
							</button>
						</p>
					</li>
				{/each}
			</ul>
		{/each}
	{/if}
</section>

<style>
	h3 {
		margin: 14px 4px 4px;
		font-size: 12px;
		font-weight: normal;
		color: var(--muted);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}
	ul {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	.window {
		margin: 0 0 8px;
		padding: 6px 8px;
		border: 1px solid var(--border);
		border-left: 3px solid var(--border);
		border-radius: 4px;
	}
	.window.open {
		border-left-color: var(--live);
	}
	p {
		margin: 2px 0;
	}
	.muted {
		margin: 2px 4px;
		color: var(--muted);
		font-size: 12px;
	}
	.window .muted {
		margin: 2px 0;
	}
	.targets {
		display: flex;
		flex-wrap: wrap;
		gap: 2px 10px;
	}
	.link {
		border: none;
		background: none;
		padding: 0;
		color: var(--accent);
		cursor: pointer;
	}
	.note {
		font-size: 12px;
		white-space: pre-wrap;
	}
	.actions {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		margin: 6px 0 0;
	}
	.maintenance > .actions {
		margin: 0 4px 6px;
	}
	.actions button {
		padding: 2px 8px;
		font-size: 12px;
	}
</style>
