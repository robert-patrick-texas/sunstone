<!--
@component
Where the documentation and the network disagree, as of the latest
discovery run: how many documented links devices confirm, then each
finding, most misleading first. Clicking one selects the link it is about,
or the device, and brings it into view.
-->
<script lang="ts">
	import type { Comparison, Finding, LinkCheck } from './api/discovery.ts';
	import { CHECK_LABEL, findingTarget, groupFindings } from './discovery.ts';
	import { clock } from './history.ts';
	import { select, ui } from './state.svelte.ts';
	import type { TopologyIndex } from './topology.ts';

	const {
		index,
		comparison,
		problem
	}: {
		index: TopologyIndex;
		comparison: Comparison | null;
		/** Why discovery could not be loaded, if it could not. */
		problem: string | null;
	} = $props();

	const groups = $derived(comparison ? groupFindings(comparison.findings) : []);
	const counts = $derived.by(() => {
		const found = new Map<LinkCheck, number>();
		for (const check of Object.values(comparison?.links ?? {})) {
			if (check) found.set(check, (found.get(check) ?? 0) + 1);
		}
		return [...found].filter(([, n]) => n > 0);
	});

	function show(finding: Finding): void {
		const target = findingTarget(finding);
		if (target) select(target, true);
	}

	const shown = (finding: Finding) =>
		JSON.stringify(findingTarget(finding)) === JSON.stringify(ui.selection);
</script>

<section aria-label="Discovery">
	{#if problem}
		<p class="muted">Discovery unavailable: {problem}</p>
	{:else if !comparison}
		<p class="muted">Loading discovery…</p>
	{:else}
		<p class="muted">
			{comparison.source} LLDP and CDP at {clock(comparison.at)} · {comparison.polled.length} devices
			answered
		</p>
		<p class="summary">
			<b>{comparison.confirmed}</b> of {index.topology.links.length} documented links confirmed{#each counts as [check, n] (check)}<span
					class="muted">{` · ${n} ${CHECK_LABEL[check].toLowerCase()}`}</span
				>{/each}
		</p>
		{#if groups.length === 0}
			<p class="muted">Everything discovery can see matches the documentation.</p>
		{/if}
		{#each groups as group (group.kind)}
			<h3>{group.label} ({group.items.length})</h3>
			<ul>
				{#each group.items as finding (finding.id)}
					<li>
						<button class="finding" aria-pressed={shown(finding)} onclick={() => show(finding)}>
							<span class="title">{finding.title}</span>
							<span class="detail">{finding.detail}</span>
						</button>
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
	p {
		margin: 2px 4px 6px;
	}
	.muted {
		color: var(--muted);
		font-size: 12px;
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
	.detail {
		display: block;
		color: var(--muted);
		font-size: 12px;
	}
</style>
