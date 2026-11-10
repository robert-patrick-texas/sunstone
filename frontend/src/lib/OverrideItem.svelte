<!--
@component
One override: what it does, how it stands now (applying, expired, or not
applied and why, and for a lock what the topology says), who made it and
when, its note and expiry; with Renew and Withdraw, which share the change
with everyone, and where asked, making a rule like it.
-->
<script lang="ts">
	import { renewOverride, withdrawOverride, type OverrideNow } from './api/overrides.ts';
	import { clock } from './history.ts';
	import { rememberName, ui } from './state.svelte.ts';
	import { describe, reloadOverrides, targetName } from './overrides.svelte.ts';
	import type { TopologyIndex } from './topology.ts';

	const {
		o,
		index,
		withTarget = false,
		onselect,
		onrule
	}: {
		o: OverrideNow;
		index: TopologyIndex;
		/** Say what it is on, as the list of every override does. */
		withTarget?: boolean;
		/** Called to show what it is on; none for no link to it. */
		onselect?: (o: OverrideNow) => void;
		/** Called to make a rule like it ("Make a rule like this…"); none to offer none. */
		onrule?: (o: OverrideNow) => void;
	} = $props();

	const RENEW: { label: string; hours: number | null }[] = [
		{ label: 'Until withdrawn', hours: null },
		{ label: '1 hour', hours: 1 },
		{ label: '8 hours', hours: 8 },
		{ label: '24 hours', hours: 24 },
		{ label: '7 days', hours: 24 * 7 }
	];

	/** Who made it and when, until when it applies, and its note. */
	const byLine = $derived(
		[
			`${o.by}, ${clock(o.at)}`,
			o.expires && o.state === 'active' ? `until ${clock(o.expires)}` : '',
			o.note
		]
			.filter(Boolean)
			.join(' · ')
	);

	let busy = $state(false);
	let renewing = $state(false);
	let lasts = $state(0);
	let problem = $state<string | null>(null);

	async function act(run: () => Promise<unknown>): Promise<void> {
		if (!ui.person.trim()) {
			problem = 'Give your name first';
			return;
		}
		rememberName(ui.person.trim());
		busy = true;
		problem = null;
		try {
			await run();
			renewing = false;
			await reloadOverrides();
		} catch (err) {
			problem = err instanceof Error ? err.message : String(err);
		} finally {
			busy = false;
		}
	}

	function renew(): Promise<void> {
		const hours = RENEW[lasts]?.hours ?? null;
		const expires = hours ? new Date(Date.now() + hours * 3_600_000).toISOString() : null;
		return act(() => renewOverride(o.id, ui.person, expires));
	}
</script>

<div class="override {o.state}" data-override={o.id}>
	<p class="what">
		{#if withTarget}
			{#if onselect}
				<button type="button" class="link" onclick={() => onselect(o)}
					>{targetName(o.target, index)}</button
				>
			{:else}
				<span class="target">{targetName(o.target, index)}</span>
			{/if}
			·
		{/if}
		{describe(o)}
	</p>
	{#if o.state === 'expired'}
		<p class="state">Expired {o.expires ? clock(o.expires) : ''}</p>
	{:else if o.state === 'not-applied'}
		<p class="state">Not applied: {o.reason}</p>
	{:else if o.kind === 'lock' && o.topology_value !== null && o.topology_value !== undefined}
		<p class="state flagged">
			Locked here · the topology says {o.topology_value === '' ? 'nothing' : o.topology_value}
		</p>
	{/if}
	<p class="by">
		{byLine}
	</p>
	{#if problem}<p class="error" role="alert">{problem}</p>{/if}
	{#if renewing}
		<p class="actions">
			<label
				>Lasts
				<select bind:value={lasts} aria-label="Lasts">
					{#each RENEW as r, i (r.label)}
						<option value={i}>{r.label}</option>
					{/each}
				</select>
			</label>
			<button type="button" disabled={busy} onclick={renew}>Renew</button>
			<button type="button" onclick={() => (renewing = false)}>Cancel</button>
		</p>
	{:else}
		<p class="actions">
			{#if o.state === 'expired' || o.expires}
				<button type="button" disabled={busy} onclick={() => (renewing = true)}>Renew…</button>
			{/if}
			<button
				type="button"
				disabled={busy}
				aria-label="Withdraw {describe(o)}"
				onclick={() => act(() => withdrawOverride(o.id, ui.person))}>Withdraw</button
			>
			{#if onrule}
				<button
					type="button"
					aria-label="Make a rule like this: {describe(o)}"
					onclick={() => onrule(o)}>Make a rule like this…</button
				>
			{/if}
		</p>
	{/if}
</div>

<style>
	.override {
		display: flex;
		flex-direction: column;
		gap: 2px;
		padding: 4px 0;
		font-size: 12px;
	}
	p {
		margin: 0;
	}
	.what {
		color: var(--text);
		font-size: 13px;
	}
	.expired .what,
	.not-applied .what {
		color: var(--muted);
	}
	.state {
		color: var(--muted);
	}
	.flagged {
		color: var(--accent);
	}
	.by {
		color: var(--muted);
	}
	.link {
		border: none;
		background: none;
		padding: 0;
		font: inherit;
		color: var(--accent);
		cursor: pointer;
	}
	.error {
		color: var(--down);
	}
	.actions {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 6px;
		margin-top: 2px;
	}
	label {
		display: flex;
		gap: 4px;
		align-items: center;
		color: var(--muted);
	}
	select {
		font: inherit;
		color: var(--text);
		background: var(--bg);
		border: 1px solid var(--border);
		border-radius: 4px;
		padding: 2px 4px;
	}
</style>
