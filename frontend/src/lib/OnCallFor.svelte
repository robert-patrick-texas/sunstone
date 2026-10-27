<!--
@component
Who owns a device, site, or links, and who is on call for it at the moment
shown; for circuits, how to reach the carrier's NOC. The team's name opens
it in the on-call list.
-->
<script lang="ts">
	import type { OnCall, Ownership, Person } from './api/oncall.ts';
	import { clock } from './history.ts';
	import { carriersFor, linksOf, ownerOf, personOf } from './oncall.ts';
	import { showTeam, type Selection } from './state.svelte.ts';
	import type { TopologyIndex } from './topology.ts';

	const {
		index,
		oncall,
		ownership,
		item
	}: {
		index: TopologyIndex;
		oncall: OnCall | null;
		ownership: Ownership | null;
		item: Selection;
	} = $props();

	/** Circuits listed one by one; a bundle of many says how many more. */
	const MAX_CIRCUITS = 4;

	const team = $derived.by(() => {
		if (!oncall || !ownership) return undefined;
		const id = ownerOf(ownership, item);
		return oncall.teams.find((t) => t.id === id);
	});
	const carriers = $derived(oncall ? carriersFor(oncall, index, linksOf(item)) : []);
</script>

{#snippet phone(person: Person)}
	{#if person.phone}<a class="mono" href="tel:{person.phone.replaceAll(' ', '')}">{person.phone}</a
		>{/if}
{/snippet}

{#if oncall && (team || carriers.length)}
	<h3>On call</h3>
	{#if team}
		{@const primary = personOf(oncall, team.now.primary)}
		<p>
			<button class="link" onclick={() => showTeam(team.id)}>{team.name}</button>
			<span class="muted">· until {clock(team.now.until)}</span>
		</p>
		<dl class="duty">
			<dt>Primary</dt>
			<dd>
				{primary.name}{#if team.now.cover}<span class="muted">{' (covering)'}</span>{/if}
				{@render phone(primary)}
			</dd>
			{#if team.now.secondary}
				{@const secondary = personOf(oncall, team.now.secondary)}
				<dt>Secondary</dt>
				<dd>{secondary.name} {@render phone(secondary)}</dd>
			{/if}
		</dl>
	{/if}
	{#each carriers.slice(0, MAX_CIRCUITS) as c (c.circuit)}
		<p>
			{c.provider} <span class="muted">· circuit {c.circuit}</span>
			{#if c.carrier}
				<br /><span class="muted">NOC</span>
				<a class="mono" href="tel:{c.carrier.phone.replaceAll(' ', '')}">{c.carrier.phone}</a>
				{#if c.carrier.portal}
					· <a href={c.carrier.portal} target="_blank" rel="noreferrer">portal</a>
				{/if}
			{/if}
		</p>
	{/each}
	{#if carriers.length > MAX_CIRCUITS}
		<p class="muted">and {carriers.length - MAX_CIRCUITS} more circuits</p>
	{/if}
{/if}

<style>
	p {
		margin: 4px 0;
	}
	.duty {
		display: grid;
		grid-template-columns: max-content 1fr;
		gap: 2px 10px;
		margin: 4px 0;
	}
	dt {
		color: var(--muted);
	}
	dd {
		margin: 0;
	}
	a {
		color: var(--accent);
	}
	.mono {
		margin-left: 6px;
		font-family: ui-monospace, monospace;
		font-size: 12px;
	}
	.link {
		border: none;
		background: none;
		padding: 0;
		color: var(--accent);
		cursor: pointer;
	}
	.muted {
		color: var(--muted);
	}
	/* As the details panel's own headings. */
	h3 {
		margin: 16px 0 6px;
		font-size: 13px;
		color: var(--muted);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}
</style>
