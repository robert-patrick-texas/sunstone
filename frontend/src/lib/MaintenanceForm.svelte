<!--
@component
Planning a maintenance window, or changing one: what the work is, when,
what it works on, a note, and who is planning it. Saving shares it with
everyone; Check impact first shows what the work would take down.
-->
<script lang="ts">
	import { saveWindow, type Window } from './api/operations.ts';
	import { targetName } from './maintenance.ts';
	import { checkImpact, rememberName, ui } from './state.svelte.ts';
	import type { TopologyIndex } from './topology.ts';

	const { index, onsaved }: { index: TopologyIndex; onsaved: (w: Window) => void } = $props();

	let saving = $state(false);
	let problem = $state<string | null>(null);
	const selected = $derived(ui.selection);
	const canAdd = $derived(
		selected !== null &&
			!ui.planning?.targets.some((t) => JSON.stringify(t) === JSON.stringify(selected))
	);

	async function save(e: SubmitEvent): Promise<void> {
		e.preventDefault();
		const draft = ui.planning;
		if (!draft) return;
		rememberName(ui.person.trim());
		saving = true;
		problem = null;
		try {
			const saved = await saveWindow(
				{
					title: draft.title,
					start: new Date(draft.start).toISOString(),
					end: new Date(draft.end).toISOString(),
					targets: $state.snapshot(draft.targets),
					note: draft.note,
					by: ui.person
				},
				draft.id ?? undefined
			);
			ui.planning = null;
			onsaved(saved);
		} catch (err) {
			problem = err instanceof Error ? err.message : String(err);
		} finally {
			saving = false;
		}
	}
</script>

{#if ui.planning}
	{@const draft = ui.planning}
	<form onsubmit={save} aria-label={draft.id ? 'Change maintenance' : 'Plan maintenance'}>
		<h3>{draft.id ? 'Change maintenance' : 'Plan maintenance'}</h3>
		<label>
			What
			<input bind:value={draft.title} required maxlength="120" placeholder="Replace line card" />
		</label>
		<div class="when">
			<label>Starts <input type="datetime-local" bind:value={draft.start} required /></label>
			<label>Ends <input type="datetime-local" bind:value={draft.end} required /></label>
		</div>
		<fieldset>
			<legend>Works on</legend>
			{#if draft.targets.length === 0}
				<p class="muted">Select a device, site, or link, then add it here.</p>
			{/if}
			<ul>
				{#each draft.targets as target, i (JSON.stringify(target))}
					<li>
						{targetName(index, target)}
						<button
							type="button"
							class="remove"
							aria-label="Remove {targetName(index, target)}"
							onclick={() => draft.targets.splice(i, 1)}>×</button
						>
					</li>
				{/each}
			</ul>
			{#if selected && canAdd}
				<button type="button" onclick={() => draft.targets.push($state.snapshot(selected))}>
					Add {targetName(index, selected)}
				</button>
			{/if}
		</fieldset>
		<label>
			Note
			<textarea
				bind:value={draft.note}
				rows="2"
				maxlength="1000"
				placeholder="Ticket, contacts, rollback"></textarea>
		</label>
		<label>
			Your name
			<input bind:value={ui.person} required maxlength="64" autocomplete="name" />
		</label>
		{#if problem}<p class="error" role="alert">Could not save: {problem}</p>{/if}
		<p class="actions">
			<button type="submit" disabled={saving || draft.targets.length === 0}>Save</button>
			<button
				type="button"
				disabled={draft.targets.length === 0}
				onclick={() => checkImpact($state.snapshot(draft.targets))}>Check impact</button
			>
			<button type="button" onclick={() => (ui.planning = null)}>Cancel</button>
		</p>
	</form>
{/if}

<style>
	form {
		display: flex;
		flex-direction: column;
		gap: 8px;
		margin: 0 4px;
	}
	h3 {
		margin: 0;
		font-size: 13px;
	}
	label {
		display: flex;
		flex-direction: column;
		gap: 2px;
		color: var(--muted);
		font-size: 12px;
	}
	input,
	textarea {
		font: inherit;
		font-size: 13px;
		color: var(--text);
		background: var(--bg);
		border: 1px solid var(--border);
		border-radius: 4px;
		padding: 4px 6px;
	}
	.when {
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	fieldset {
		border: 1px solid var(--border);
		border-radius: 4px;
		padding: 4px 8px 8px;
		margin: 0;
	}
	legend {
		color: var(--muted);
		font-size: 12px;
	}
	ul {
		margin: 0 0 6px;
		padding-left: 16px;
	}
	.remove {
		border: none;
		background: none;
		padding: 0 4px;
		color: var(--muted);
	}
	.muted {
		margin: 0 0 6px;
		color: var(--muted);
		font-size: 12px;
	}
	.error {
		margin: 0;
		color: var(--down);
		font-size: 12px;
	}
	.actions {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		margin: 0;
	}
</style>
