<!--
@component
What discovery says about a device or links: for a device, whether it
answered the latest run, how many of its documented links devices confirm,
and the findings that involve it; for links, each one's check, with the
finding about it if there is one. A finding of the latest run that offers
a fix can be reviewed from here, or marked expected, and a link fixed in
Sunstone, or expected not to be seen, says so.
-->
<script lang="ts">
	import type { Change } from './api/changes.ts';
	import type { Comparison, Finding } from './api/discovery.ts';
	import {
		changeOf,
		CHECK_LABEL,
		deviceCheck,
		EXPECTABLE,
		expectationOf,
		findingTarget,
		linkCheck,
		NO_FIX,
		seenWhen
	} from './discovery.ts';
	import { clock } from './history.ts';
	import { reviewFix, ui, type Selection } from './state.svelte.ts';
	import { linkName, type TopologyIndex } from './topology.ts';

	const {
		index,
		comparison,
		changes,
		item
	}: {
		index: TopologyIndex;
		comparison: Comparison | null;
		/** Fixes accepted into the documentation, and findings marked expected, newest first. */
		changes: Change[];
		item: Selection;
	} = $props();

	/** Links listed one by one; a bundle of many says how many more. */
	const MAX_LINKS = 4;
</script>

{#snippet fixOf(f: Finding)}
	{#if ui.at === null && f.fix}
		<br /><button class="link" onclick={() => reviewFix(f.id, findingTarget(f))}
			>Fix: {f.fix.summary}</button
		>
	{:else if NO_FIX[f.kind]}
		<br /><span class="muted">{NO_FIX[f.kind]}</span>
	{/if}
	{#if ui.at === null && EXPECTABLE.has(f.kind)}
		<br /><button class="link" onclick={() => reviewFix(f.id, findingTarget(f), true)}
			>Mark expected…</button
		>
	{/if}
{/snippet}

{#snippet expectedBy(change: Change | undefined)}
	{#if change}
		<span class="muted">· {change.by} at {clock(change.at)}: {change.note}</span>
	{/if}
{/snippet}

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
				{@render fixOf(f)}
			</p>
		{/each}
		{#each comparison.expected.filter((f) => f.devices.includes(item.id)) as f (f.id)}
			<p class="fixed">
				Expected: {f.title}
				{@render expectedBy(changes.find((c) => c.fix.kind === 'expect' && c.finding === f.id))}
			</p>
		{/each}
	{:else}
		{#each item.ids.slice(0, MAX_LINKS) as id (id)}
			{@const link = index.links.get(id)}
			{@const check = linkCheck(comparison, id)}
			{@const finding = comparison.findings.find((f) => f.link === id)}
			{@const fixed = changeOf(changes, id)}
			<p class:finding={check !== 'confirmed'}>
				{#if item.ids.length > 1 && link}{linkName(link)}:
				{/if}<b>{CHECK_LABEL[check]}</b>
				<span class="muted">
					{#if finding}· {finding.detail}
					{:else if check === 'confirmed'}· seen at {clock(comparison.at)}
					{:else if check === 'unchecked'}· neither end answers discovery
					{/if}
				</span>
				{#if finding}{@render fixOf(finding)}{/if}
			</p>
			{@const expectation =
				check === 'expected' && link ? expectationOf(comparison, changes, link) : null}
			{#if expectation}
				<p class="fixed">
					Expected: {expectation.change?.title ?? expectation.finding.title}
					{@render expectedBy(expectation.change)}
				</p>
			{/if}
			{#if fixed}
				<p class="fixed">
					Fixed here by {fixed.by} at {clock(fixed.at)}{fixed.note ? `: ${fixed.note}` : ''}
					<span class="muted">· not yet in the source of truth</span>
				</p>
			{/if}
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
	.fixed {
		padding-left: 8px;
		border-left: 3px solid var(--drift);
	}
	.link {
		border: none;
		background: none;
		padding: 0;
		color: var(--accent);
		cursor: pointer;
		text-align: left;
	}
	.link:hover {
		text-decoration: underline;
	}
</style>
