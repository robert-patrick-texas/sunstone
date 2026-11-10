<!--
@component
Where the documentation and the network disagree, as of the latest
discovery run, or the run in effect at the moment replayed: how many
documented links devices confirm, then each finding, most misleading
first, with when it was seen, then findings seen earlier in the day but
no longer. Clicking one shows discovery on the map, selects the link it
is about, or the device, and brings it into view; Show on the map turns
that on and off. A finding of the latest run that the documentation can
settle offers a fix, reviewed here before it is accepted; the fixes
accepted are listed with who accepted them, and can be reverted. What
discovery cannot see, or is not meant to be documented, can be marked
expected with a note instead, and is then listed apart, to be withdrawn.
A neighbor not in the topology, seen where the topology is right, offers
overrides instead: another name for the documented device, one device on
the port, or ignoring the neighbor there. The same finding on the same port
of many devices with one role offers a rule, above the findings and on each
of them.
-->
<script lang="ts">
	import { revertChange, type Change } from './api/changes.ts';
	import type { Comparison, Finding, LinkCheck, TunnelCheck } from './api/discovery.ts';
	import type { OverrideKind } from './api/overrides.ts';
	import {
		changedTarget,
		changeLine,
		CHECK_LABEL,
		EXPECTABLE,
		TUNNEL_CHECK_LABEL,
		findingTarget,
		groupFindings,
		overrideOffers,
		seenWhen
	} from './discovery.ts';
	import FixReview from './FixReview.svelte';
	import { clock } from './history.ts';
	import OverrideForm from './OverrideForm.svelte';
	import { named, ruleOffers, type RuleOffer } from './overrides.svelte.ts';
	import RuleForm from './RuleForm.svelte';
	import { reviewFix, select, showDiscovery, ui, type Selection } from './state.svelte.ts';
	import type { TopologyIndex } from './topology.ts';

	const {
		index,
		comparison,
		problem,
		changes,
		ondocumented
	}: {
		index: TopologyIndex;
		comparison: Comparison | null;
		/** Why discovery could not be loaded, if it could not. */
		problem: string | null;
		/** Fixes accepted into the documentation, and findings marked expected, newest first. */
		changes: Change[];
		/** Called once the documentation has changed, with what to select then. */
		ondocumented: (target: Selection | null) => void;
	} = $props();

	// Fixes are offered, and accepted, from the latest run only.
	const latest = $derived(ui.at === null);
	const reviewing = $derived(
		latest && ui.fixing
			? (comparison?.findings.find((f) => f.id === ui.fixing?.finding) ?? null)
			: null
	);
	const fixes = $derived(changes.filter((c) => c.fix.kind !== 'expect'));
	const expectations = $derived(changes.filter((c) => c.fix.kind === 'expect'));
	let revertProblem = $state<string | null>(null);
	/** The override a finding offers being made, if any. */
	let offering = $state<{ finding: string; kind: OverrideKind } | null>(null);
	/** The rules repeated findings offer, from the latest run only. */
	const rules = $derived(latest && comparison ? ruleOffers(comparison.findings, index) : []);
	/** The rule offered being made, if any, by its key: above the findings, or under one. */
	let ruling = $state<{ offer: string; finding: string | null } | null>(null);

	/** An offer of a rule, as the form open on it knows it. */
	const keyOf = (r: RuleOffer) => `${r.label} ${r.findings[0]}`;

	/** Make the rule offered, above the findings or under one; only one form is open. */
	function offerRule(r: RuleOffer, finding: string | null): void {
		offering = null;
		ruling = { offer: keyOf(r), finding };
	}

	async function revert(change: Change): Promise<void> {
		try {
			await revertChange(change.id);
			revertProblem = null;
			ondocumented(changedTarget(change.fix.before, change.fix.after));
		} catch (err) {
			revertProblem = err instanceof Error ? err.message : String(err);
		}
	}

	const groups = $derived(comparison ? groupFindings(comparison.findings) : []);
	const counts = $derived.by(() => {
		const found = new Map<LinkCheck, number>();
		for (const check of Object.values(comparison?.links ?? {})) {
			if (check) found.set(check, (found.get(check) ?? 0) + 1);
		}
		return [...found].filter(([, n]) => n > 0);
	});

	/** Tunnels CDP runs over, and MACsec: how many are confirmed, and the rest by check. */
	const tunnels = $derived.by(() => {
		const found = new Map<TunnelCheck, number>();
		for (const check of Object.values(comparison?.tunnels ?? {})) {
			if (check) found.set(check, (found.get(check) ?? 0) + 1);
		}
		const total = [...found.values()].reduce((sum, n) => sum + n, 0);
		const confirmed = found.get('confirmed') ?? 0;
		found.delete('confirmed');
		return { total, confirmed, rest: [...found] };
	});

	const endpoints = $derived(
		Object.values(comparison?.endpoints ?? {}).reduce((sum, n) => sum + n, 0)
	);

	function show(finding: Finding): void {
		showDiscovery(findingTarget(finding));
	}

	const shown = (finding: Finding) =>
		JSON.stringify(findingTarget(finding)) === JSON.stringify(ui.selection);
</script>

{#snippet when(finding: Finding)}
	{@const text = seenWhen(finding, comparison?.history_from)}
	{#if text}<span class="when">Seen {text}</span>{/if}
{/snippet}

{#snippet ruleForm(finding: string | null)}
	{@const making =
		ruling?.finding === finding ? rules.find((r) => keyOf(r) === ruling?.offer) : undefined}
	{#if making}
		<!-- Made afresh for each offer, from its draft. -->
		{#key keyOf(making)}
			<div class="override">
				<RuleForm
					{index}
					preset={making.draft}
					onmade={() => (ruling = null)}
					oncancel={() => (ruling = null)}
				/>
			</div>
		{/key}
	{/if}
{/snippet}

<section aria-label="Discovery">
	{#if problem}
		<p class="muted">Discovery unavailable: {problem}</p>
	{:else if !comparison}
		<p class="muted">Loading discovery…</p>
	{:else}
		<p class="muted">
			{comparison.source} LLDP and CDP at {clock(comparison.at)}{ui.at ? ' (replaying)' : ''} ·
			{comparison.polled.length} devices answered
		</p>
		<p class="summary">
			<b>{comparison.confirmed}</b> of {index.topology.links.length} documented links confirmed{#each counts as [check, n] (check)}<span
					class="muted">{` · ${n} ${CHECK_LABEL[check].toLowerCase()}`}</span
				>{/each}{#if endpoints}<span class="muted"
					>{` · ${endpoints} endpoints on access ports`}</span
				>{/if}
		</p>
		{#if tunnels.total}
			<p class="summary">
				<b>{tunnels.confirmed}</b> of {tunnels.total} tunnels confirmed over CDP or inside MACsec{#each tunnels.rest as [check, n] (check)}<span
						class="muted"
						>{` · ${n} ${TUNNEL_CHECK_LABEL[check].charAt(0).toLowerCase()}${TUNNEL_CHECK_LABEL[check].slice(1)}`}</span
					>{/each}
			</p>
		{/if}
		<p class="actions">
			<button
				aria-pressed={ui.discovery}
				onclick={() => (ui.discovery ? (ui.discovery = false) : showDiscovery(null))}
				>Show on the map</button
			>
		</p>
		{#if reviewing}
			<FixReview
				finding={reviewing}
				expect={ui.fixing?.expect ?? false}
				onaccepted={(c) =>
					ondocumented(
						c.fix.kind === 'expect'
							? findingTarget(reviewing)
							: changedTarget(c.fix.after, c.fix.before)
					)}
			/>
		{:else if latest && ui.fixing}
			<p class="muted">
				That finding is not in the latest run any more.
				<button class="link" onclick={() => (ui.fixing = null)}>Close</button>
			</p>
		{/if}
		{#if groups.length === 0}
			<p class="muted">Everything discovery can see matches the documentation.</p>
		{/if}
		{#if rules.length}
			<p class="rules">
				{#each rules as r (keyOf(r))}
					<button
						class="fix"
						aria-pressed={ruling?.offer === keyOf(r) && ruling.finding === null}
						onclick={() => offerRule(r, null)}
						>{r.label} · {r.findings.length} finding{r.findings.length === 1 ? '' : 's'}</button
					>
				{/each}
			</p>
			{@render ruleForm(null)}
		{/if}
		{#each groups as group (group.kind)}
			<h3>{group.label} ({group.items.length})</h3>
			<ul>
				{#each group.items as finding (finding.id)}
					{@const offers = latest ? overrideOffers(finding, index) : []}
					{@const making = offers.find(
						(o) => offering?.finding === finding.id && offering.kind === o.kind
					)}
					{@const ruled = rules.filter((r) => r.findings.includes(finding.id))}
					<li>
						<button class="finding" aria-pressed={shown(finding)} onclick={() => show(finding)}>
							<span class="title">{named(finding.title)}</span>
							<span class="detail">{named(finding.detail)}</span>
							{@render when(finding)}
						</button>
						{#if latest && (finding.fix || EXPECTABLE.has(finding.kind) || offers.length || ruled.length)}
							<p class="offers">
								{#if finding.fix}
									<button
										class="fix"
										aria-pressed={ui.fixing?.finding === finding.id && !ui.fixing.expect}
										onclick={() => reviewFix(finding.id, findingTarget(finding))}
										>Fix: {named(finding.fix.summary)}</button
									>
								{/if}
								{#if EXPECTABLE.has(finding.kind)}
									<button
										class="fix"
										aria-pressed={ui.fixing?.finding === finding.id && ui.fixing.expect}
										onclick={() => reviewFix(finding.id, findingTarget(finding), true)}
										>Mark expected…</button
									>
								{/if}
								{#each offers as o (o.kind)}
									<button
										class="fix"
										aria-pressed={o === making}
										onclick={() => {
											ruling = null;
											offering = { finding: finding.id, kind: o.kind };
										}}>{o.label}</button
									>
								{/each}
								{#each ruled as r (keyOf(r))}
									<button
										class="fix"
										aria-pressed={ruling?.offer === keyOf(r) && ruling.finding === finding.id}
										onclick={() => offerRule(r, finding.id)}>{r.label}</button
									>
								{/each}
							</p>
						{/if}
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
						{@render ruleForm(finding.id)}
					</li>
				{/each}
			</ul>
		{/each}
		{#if revertProblem}<p class="error" role="alert">{revertProblem}</p>{/if}
		{#if expectations.length}
			<h3>Expected ({expectations.length})</h3>
			<ul>
				{#each expectations as change (change.id)}
					{@const finding = comparison.expected.find((f) => f.id === change.finding)}
					{@const covered = comparison.expected.filter((f) => f.covered_by === change.finding)}
					{@const target = finding ? findingTarget(finding) : null}
					<li class="change">
						<button class="finding gone" onclick={() => target && select(target, true)}>
							<span class="title">{named(change.title)}</span>
							<span class="detail"
								>{finding
									? named(finding.detail)
									: covered.length
										? `Not answering; its ${covered.length} links not seen, as expected`
										: `Not in the ${ui.at ? 'run then' : 'latest run'}`}</span
							>
							{#if finding}{@render when(finding)}{/if}
							<span class="when">{change.by} · {clock(change.at)} · {change.note}</span>
						</button>
						<button class="link" onclick={() => revert(change)}>Withdraw</button>
					</li>
				{/each}
			</ul>
		{/if}
		{#if fixes.length}
			<h3>Fixed here ({fixes.length})</h3>
			<p class="muted">In the documentation Sunstone shows, not yet in the source of truth.</p>
			<ul>
				{#each fixes as change (change.id)}
					{@const target = changedTarget(change.fix.after, change.fix.before)}
					<li class="change">
						<button class="finding" onclick={() => target && select(target, true)}>
							<span class="title">{changeLine(change)}</span>
							<span class="detail">{named(change.title)}</span>
							<span class="when"
								>{change.by} · {clock(change.at)}{change.note ? ` · ${change.note}` : ''}</span
							>
						</button>
						<button class="link" onclick={() => revert(change)}>Revert</button>
					</li>
				{/each}
			</ul>
		{/if}
		{#if comparison.gone.length}
			<h3>Seen earlier, not {ui.at ? 'then' : 'now'} ({comparison.gone.length})</h3>
			<ul>
				{#each comparison.gone as finding (finding.id)}
					<li>
						<button class="finding gone" onclick={() => show(finding)}>
							<span class="title">{named(finding.title)}</span>
							<span class="detail">{named(finding.detail)}</span>
							{@render when(finding)}
						</button>
					</li>
				{/each}
			</ul>
		{/if}
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
	p {
		margin: 2px 4px 6px;
	}
	.muted {
		color: var(--muted);
		font-size: 12px;
	}
	.actions button {
		padding: 2px 8px;
		font-size: 12px;
	}
	.actions button[aria-pressed='true'] {
		border-color: var(--selected);
	}
	.finding {
		display: block;
		width: 100%;
		margin: 0 0 4px;
		padding: 5px 8px;
		text-align: left;
		border-radius: 4px;
	}
	.finding[aria-pressed='true'] {
		border-color: var(--selected);
	}
	.title {
		display: block;
	}
	.detail,
	.when {
		display: block;
		color: var(--muted);
		font-size: 12px;
	}
	.when {
		font-size: 11px;
	}
	.gone {
		opacity: 0.75;
	}
	.fix,
	.link {
		border: none;
		background: none;
		color: var(--accent);
		cursor: pointer;
		text-align: left;
	}
	.offers {
		display: flex;
		flex-wrap: wrap;
		gap: 0 12px;
		margin: -2px 0 6px;
		padding: 0 8px;
	}
	.rules {
		display: flex;
		flex-wrap: wrap;
		gap: 2px 12px;
	}
	.fix {
		padding: 0;
		font-size: 12px;
	}
	.fix:hover,
	.link:hover {
		text-decoration: underline;
	}
	.fix[aria-pressed='true'] {
		color: var(--selected);
	}
	.link {
		padding: 0;
		font-size: 12px;
	}
	.change {
		display: flex;
		align-items: flex-start;
		gap: 6px;
	}
	.change .finding {
		flex: 1;
		min-width: 0;
	}
	.change .link {
		margin-top: 6px;
	}
	.override {
		margin: 0 0 8px;
		padding: 4px 8px;
		border: 1px solid var(--drift);
		border-radius: 6px;
	}
	.error {
		color: var(--down);
		font-size: 12px;
	}
</style>
