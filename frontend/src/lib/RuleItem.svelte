<!--
@component
One rule: its name, what it does and matches, how it stands now (applying,
expired, or not applied and why), what it applies on, where an override or
a newer rule wins, for a lock how many the topology says otherwise of, and
what is taken out of it, each to apply on again; who made it and when, its
note and expiry; with Renew and Withdraw, which share the change with
everyone.
-->
<script lang="ts">
	import {
		includeInRule,
		renewRule,
		withdrawRule,
		type RuleNow,
		type Target
	} from './api/overrides.ts';
	import { clock } from './history.ts';
	import {
		NOUNS,
		describeRule,
		matchText,
		reloadOverrides,
		targetKey,
		targetName
	} from './overrides.svelte.ts';
	import { counted } from './ruleForm.ts';
	import { rememberName, ui } from './state.svelte.ts';
	import type { TopologyIndex } from './topology.ts';

	const {
		r,
		index,
		onselect
	}: {
		r: RuleNow;
		index: TopologyIndex;
		/** Called to show what it applies on (a device, for a rule on ports); none for no link to it. */
		onselect?: (t: Target) => void;
	} = $props();

	const RENEW: { label: string; hours: number | null }[] = [
		{ label: 'Until withdrawn', hours: null },
		{ label: '1 hour', hours: 1 },
		{ label: '8 hours', hours: 8 },
		{ label: '24 hours', hours: 24 },
		{ label: '7 days', hours: 24 * 7 }
	];
	/** How many of what it applies on are listed. */
	const LISTED = 20;

	const noun = $derived(NOUNS[r.match.of === 'port' ? 'device' : r.match.of]);
	/** For a lock, how many it applies on the topology gives another value. */
	const differ = $derived(
		r.kind === 'lock'
			? r.matches.filter((m) => m.topology_value !== null && m.topology_value !== undefined).length
			: 0
	);

	/** Who made it and when, until when it applies, and its note. */
	const byLine = $derived(
		[
			`${r.by}, ${clock(r.at)}`,
			r.expires && r.state === 'active' ? `until ${clock(r.expires)}` : '',
			r.note
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
		return act(() => renewRule(r.id, ui.person, expires));
	}
</script>

<div class="rule {r.state}" data-rule={r.id}>
	<p class="what"><strong>{r.name}</strong></p>
	<p class="does">{describeRule(r)} · {matchText(r.match)}</p>
	{#if r.state === 'expired'}
		<p class="state">Expired {r.expires ? clock(r.expires) : ''}</p>
	{:else if r.state === 'not-applied'}
		<p class="state reason">Not applied: {r.reason}</p>
	{:else if r.matches.length === 0}
		<p class="state">Applies on nothing now</p>
	{:else}
		<details>
			<summary>Applies on {counted(r.matches.length, noun)}</summary>
			<ul>
				{#each r.matches.slice(0, LISTED) as m (targetKey(m.target))}
					<li>
						{#if onselect}
							<button type="button" class="link" onclick={() => onselect(m.target)}
								>{targetName(m.target, index)}</button
							>
						{:else}
							{targetName(m.target, index)}
						{/if}
						{#if m.topology_value !== null && m.topology_value !== undefined}
							<span class="flagged"
								>· the topology says {m.topology_value === '' ? 'nothing' : m.topology_value}</span
							>
						{/if}
					</li>
				{/each}
				{#if r.matches.length > LISTED}
					<li class="state">and {r.matches.length - LISTED} more</li>
				{/if}
			</ul>
		</details>
	{/if}
	{#if r.overridden.length}
		<p class="state">{r.overridden.length} where an override or a newer rule wins</p>
	{/if}
	{#if differ}
		<p class="state flagged">The topology says otherwise of {counted(differ, noun)}</p>
	{/if}
	{#each r.excepted as e (targetKey(e.target))}
		<p class="state">
			Not on {targetName(e.target, index)} · {e.by}, {clock(e.at)}
			<button
				type="button"
				disabled={busy}
				onclick={() => act(() => includeInRule(r.id, e.target, ui.person))}>Apply here again</button
			>
		</p>
	{/each}
	<p class="by">
		{byLine}
	</p>
	{#if problem}<p class="error" role="alert">{problem}</p>{/if}
	{#if renewing}
		<p class="actions">
			<label
				>Lasts
				<select bind:value={lasts} aria-label="Lasts">
					{#each RENEW as l, i (l.label)}
						<option value={i}>{l.label}</option>
					{/each}
				</select>
			</label>
			<button type="button" disabled={busy} onclick={renew}>Renew</button>
			<button type="button" onclick={() => (renewing = false)}>Cancel</button>
		</p>
	{:else}
		<p class="actions">
			{#if r.state === 'expired' || r.expires}
				<button type="button" disabled={busy} onclick={() => (renewing = true)}>Renew…</button>
			{/if}
			<button
				type="button"
				disabled={busy}
				aria-label="Withdraw {r.name}"
				onclick={() => act(() => withdrawRule(r.id, ui.person))}>Withdraw</button
			>
		</p>
	{/if}
</div>

<style>
	.rule {
		display: flex;
		flex-direction: column;
		gap: 2px;
		padding: 4px 0;
		font-size: 12px;
	}
	p {
		margin: 0;
	}
	.what,
	.does {
		color: var(--text);
		font-size: 13px;
	}
	.expired .what,
	.not-applied .what,
	.expired .does,
	.not-applied .does {
		color: var(--muted);
	}
	.state {
		color: var(--muted);
	}
	.flagged {
		color: var(--accent);
	}
	.reason {
		white-space: pre-line;
	}
	.by {
		color: var(--muted);
	}
	summary {
		color: var(--text);
		cursor: pointer;
	}
	details ul {
		list-style: none;
		margin: 2px 0 0;
		padding-left: 14px;
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
