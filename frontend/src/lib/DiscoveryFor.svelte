<!--
@component
What discovery says about a device or links: for a device, whether it
answered the latest run, how many of its documented links devices confirm,
and the findings that involve it; for links, each one's check, with the
finding about it if there is one.
-->
<script lang="ts">
	import type { Comparison } from './api/discovery.ts';
	import { CHECK_LABEL, deviceCheck, linkCheck, seenWhen } from './discovery.ts';
	import { clock } from './history.ts';
	import type { Selection } from './state.svelte.ts';
	import { linkName, type TopologyIndex } from './topology.ts';

	const {
		index,
		comparison,
		item
	}: {
		index: TopologyIndex;
		comparison: Comparison | null;
		item: Selection;
	} = $props();

	/** Links listed one by one; a bundle of many says how many more. */
	const MAX_LINKS = 4;
</script>

{#if comparison && item.kind !== 'site'}
	<h3>Discovery</h3>
	{#if item.kind === 'device'}
		{@const check = deviceCheck(comparison, index, item.id)}
		{#if check.polled}
			<p>
				{check.confirmed} of {check.links} documented links confirmed
				<span class="muted">· at {clock(comparison.at)}</span>
			</p>
		{:else}
			<p class="muted">
				It did not answer the latest run (not polled, or down), so only its neighbors can confirm
				its links.
			</p>
		{/if}
		{#each check.findings as f (f.id)}
			{@const when = seenWhen(f, comparison.history_from)}
			<p class="finding">
				<b>{f.title}</b><br /><span class="muted">{f.detail}{when ? ` · seen ${when}` : ''}</span>
			</p>
		{/each}
	{:else}
		{#each item.ids.slice(0, MAX_LINKS) as id (id)}
			{@const link = index.links.get(id)}
			{@const check = linkCheck(comparison, id)}
			{@const finding = comparison.findings.find((f) => f.link === id)}
			<p class:finding={check !== 'confirmed'}>
				{#if item.ids.length > 1 && link}{linkName(link)}:
				{/if}<b>{CHECK_LABEL[check]}</b>
				<span class="muted">
					{#if finding}· {finding.detail}
					{:else if check === 'confirmed'}· seen at {clock(comparison.at)}
					{:else if check === 'unchecked'}· neither end answers discovery
					{/if}
				</span>
			</p>
		{/each}
		{#if item.ids.length > MAX_LINKS}
			<p class="muted">and {item.ids.length - MAX_LINKS} more links</p>
		{/if}
	{/if}
{/if}

<style>
	/* As the details panel's own headings. */
	h3 {
		margin: 16px 0 6px;
		font-size: 13px;
		color: var(--muted);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}
	p {
		margin: 4px 0;
	}
	.finding {
		padding-left: 8px;
		border-left: 3px solid var(--selected);
	}
	.muted {
		color: var(--muted);
	}
</style>
