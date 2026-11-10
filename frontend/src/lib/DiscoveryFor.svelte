<!--
@component
What discovery says about a device or links: for a device, whether it
answered the latest run, how many of its documented links devices confirm,
and the findings that involve it; for links, each one's check, with the
finding about it if there is one. A finding of the latest run that offers
a fix can be reviewed from here, or marked expected, and a link fixed in
Sunstone, or expected not to be seen, says so. One about a neighbor not in
the topology offers overrides, made here, and one repeated on the same port
of many devices with one role, a rule.
-->
<script lang="ts">
	import type { Change } from './api/changes.ts';
	import type { Comparison, Finding } from './api/discovery.ts';
	import type { OverrideKind } from './api/overrides.ts';
	import {
		changeOf,
		CHECK_DETAIL,
		CHECK_LABEL,
		deviceCheck,
		EXPECTABLE,
		expectationOf,
		findingTarget,
		linkCheck,
		NO_FIX,
		overrideOffers,
		seenWhen
	} from './discovery.ts';
	import { clock } from './history.ts';
	import OverrideForm from './OverrideForm.svelte';
	import { named, ruleOffers, type RuleOffer } from './overrides.svelte.ts';
	import RuleForm from './RuleForm.svelte';
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

	/** The override a finding offers being made, if any. */
	let offering = $state<{ finding: string; kind: OverrideKind } | null>(null);

	/** The overrides a finding offers, from the latest run only. */
	const offersOf = (f: Finding) => (ui.at === null ? overrideOffers(f, index) : []);

	/** The rules repeated findings offer, from the latest run only. */
	const rules = $derived(
		ui.at === null && comparison ? ruleOffers(comparison.findings, index) : []
	);
	/** The rule a finding offers being made, if any, by its key. */
	let ruling = $state<{ offer: string; finding: string } | null>(null);

	/** An offer of a rule, as the form open on it knows it. */
	const keyOf = (r: RuleOffer) => `${r.label} ${r.findings[0]}`;
</script>

{#snippet fixOf(f: Finding)}
	{#if ui.at === null && f.fix}
		<br /><button class="link" onclick={() => reviewFix(f.id, findingTarget(f))}
			>Fix: {named(f.fix.summary)}</button
		>
	{:else if NO_FIX[f.kind]}
		<br /><span class="muted">{NO_FIX[f.kind]}</span>
	{/if}
	{#if ui.at === null && EXPECTABLE.has(f.kind)}
		<br /><button class="link" onclick={() => reviewFix(f.id, findingTarget(f), true)}
			>Mark expected…</button
		>
	{/if}
	{#each offersOf(f) as o (o.kind)}
		<br /><button
			class="link"
			aria-pressed={offering?.finding === f.id && offering.kind === o.kind}
			onclick={() => {
				ruling = null;
				offering = { finding: f.id, kind: o.kind };
			}}>{o.label}</button
		>
	{/each}
	{#each rules.filter((r) => r.findings.includes(f.id)) as r (keyOf(r))}
		<br /><button
			class="link"
			aria-pressed={ruling?.finding === f.id && ruling.offer === keyOf(r)}
			onclick={() => {
				offering = null;
				ruling = { offer: keyOf(r), finding: f.id };
			}}>{r.label}</button
		>
	{/each}
{/snippet}

{#snippet overrideOf(f: Finding)}
	{@const making = offersOf(f).find((o) => offering?.finding === f.id && offering.kind === o.kind)}
	{@const ruled =
		ruling?.finding === f.id ? rules.find((r) => keyOf(r) === ruling?.offer) : undefined}
	{#if making}
		<!-- Made afresh for each offer, from its preset. -->
		{#key making.kind}
			<div class="override">
				<OverrideForm
					of={making.of}
					{index}
					kinds={[making.kind]}
					preset={{ kind: making.kind, value: making.value }}
					onmade={() => (offering = null)}
					oncancel={() => (offering = null)}
				/>
			</div>
		{/key}
	{/if}
	{#if ruled}
		<!-- Made afresh for each offer, from its draft. -->
		{#key keyOf(ruled)}
			<div class="override">
				<RuleForm
					{index}
					preset={ruled.draft}
					onmade={() => (ruling = null)}
					oncancel={() => (ruling = null)}
				/>
			</div>
		{/key}
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
			{#if check.endpoints}
				<p class="muted">
					{check.endpoints} endpoint{check.endpoints === 1 ? '' : 's'} (phones, hosts) on ports no link
					documents: access, not findings
				</p>
			{/if}
		{:else}
			<p class="muted">
				It did not answer the latest run (not polled, or down), so only its neighbors can confirm
				its links.
			</p>
		{/if}
		{#each check.findings as f (f.id)}
			{@const when = seenWhen(f, comparison.history_from)}
			<p class="finding">
				<b>{named(f.title)}</b><br /><span class="muted"
					>{named(f.detail)}{when ? ` · seen ${when}` : ''}</span
				>
				{@render fixOf(f)}
			</p>
			{@render overrideOf(f)}
		{/each}
		{#each comparison.expected.filter((f) => f.devices.includes(item.id)) as f (f.id)}
			<p class="fixed">
				Expected: {named(f.title)}
				{@render expectedBy(changes.find((c) => c.fix.kind === 'expect' && c.finding === f.id))}
			</p>
		{/each}
	{:else}
		{#each item.ids.slice(0, MAX_LINKS) as id (id)}
			{@const link = index.links.get(id)}
			{@const check = linkCheck(comparison, id)}
			{@const finding = comparison.findings.find((f) => f.link === id)}
			{@const fixed = changeOf(changes, id)}
			{#if link}
				<p class:finding={!['confirmed', 'provider', 'nothing'].includes(check)}>
					{#if item.ids.length > 1}{named(linkName(link))}:
					{/if}<b
						>{finding?.kind === 'boundary' ? 'Our own device across it' : CHECK_LABEL[check]}</b
					>
					<span class="muted">
						{#if finding}· {named(finding.detail)}
						{:else if check === 'confirmed' || check === 'provider'}· {CHECK_DETAIL[check] ??
								'seen'} at {clock(comparison.at)}
						{:else if CHECK_DETAIL[check]}· {CHECK_DETAIL[check]}
						{/if}
					</span>
					{#if finding}{@render fixOf(finding)}{/if}
				</p>
				{#if finding}{@render overrideOf(finding)}{/if}
				{@const expectation =
					check === 'expected' && link ? expectationOf(comparison, changes, link) : null}
				{#if expectation}
					<p class="fixed">
						Expected: {named(expectation.change?.title ?? expectation.finding.title)}
						{@render expectedBy(expectation.change)}
					</p>
				{/if}
				{#if fixed}
					<p class="fixed">
						Fixed here by {fixed.by} at {clock(fixed.at)}{fixed.note ? `: ${fixed.note}` : ''}
						<span class="muted">· not yet in the source of truth</span>
					</p>
				{/if}
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
	.link[aria-pressed='true'] {
		color: var(--selected);
	}
	.override {
		margin: 0 0 8px;
		padding-left: 8px;
		border-left: 3px solid var(--selected);
	}
</style>
