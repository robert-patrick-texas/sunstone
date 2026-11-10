<!--
@component
Every rule and override not withdrawn: rules applying, not applied and
why, and expired, each with what it applies on; then overrides flagged
(locks the topology now says otherwise of), applying, not applied, and
expired, each with what it is on; all to renew or withdraw, and making a
rule. Clicking what one is on selects it and brings it into view: a port as
its device, a port channel as its members.
-->
<script lang="ts">
	import type { OverrideNow, Target } from './api/overrides.ts';
	import { lagMembers } from './connections.ts';
	import OverrideItem from './OverrideItem.svelte';
	import RuleForm from './RuleForm.svelte';
	import RuleItem from './RuleItem.svelte';
	import { lagId, objectOf, overrides } from './overrides.svelte.ts';
	import { select } from './state.svelte.ts';
	import type { TopologyIndex } from './topology.ts';

	const { index }: { index: TopologyIndex } = $props();

	let making = $state(false);

	/** A lock applying whose field the topology now gives another value. */
	function flagged(o: OverrideNow): boolean {
		return (
			o.state === 'active' &&
			o.kind === 'lock' &&
			o.topology_value !== null &&
			o.topology_value !== undefined
		);
	}

	const groups = $derived(
		[
			{ label: 'Flagged', items: overrides.list.filter(flagged) },
			{
				label: 'Applying',
				items: overrides.list.filter((o) => o.state === 'active' && !flagged(o))
			},
			{ label: 'Not applied', items: overrides.list.filter((o) => o.state === 'not-applied') },
			{ label: 'Expired', items: overrides.list.filter((o) => o.state === 'expired') }
		].filter((g) => g.items.length > 0)
	);

	const ruleGroups = $derived(
		[
			{ label: 'Rules applying', items: overrides.rules.filter((r) => r.state === 'active') },
			{
				label: 'Rules not applied',
				items: overrides.rules.filter((r) => r.state === 'not-applied')
			},
			{ label: 'Rules expired', items: overrides.rules.filter((r) => r.state === 'expired') }
		].filter((g) => g.items.length > 0)
	);

	function show(of: Target): void {
		switch (of.kind) {
			case 'link':
				select({ kind: 'links', ids: [of.id] }, true);
				break;
			case 'port':
				select({ kind: 'device', id: of.id }, true);
				break;
			case 'lag': {
				const t = index.topology;
				const lag = t.lags.find((g) => lagId(g) === of.id);
				if (lag) select({ kind: 'links', ids: lagMembers(t, lag).map((l) => l.id) }, true);
				break;
			}
			default:
				select({ kind: of.kind, id: of.id }, true);
		}
	}
</script>

<section aria-label="Overrides">
	{#if making}
		<div class="making">
			<RuleForm {index} onmade={() => (making = false)} oncancel={() => (making = false)} />
		</div>
	{:else}
		<p class="actions"><button type="button" onclick={() => (making = true)}>New rule…</button></p>
	{/if}
	{#if groups.length === 0 && ruleGroups.length === 0}
		<p class="muted">
			No overrides or rules. Make one from an object's details: rename it, give it an alias, tag or
			label it, hide it, or lock a field; or make a rule for everything that matches.
		</p>
	{/if}
	{#each ruleGroups as group (group.label)}
		<h3>{group.label} ({group.items.length})</h3>
		<ul>
			{#each group.items as r (r.id)}
				<li><RuleItem {r} {index} onselect={show} /></li>
			{/each}
		</ul>
	{/each}
	{#each groups as group (group.label)}
		<h3>{group.label} ({group.items.length})</h3>
		<ul>
			{#each group.items as o (o.id)}
				<li>
					<!-- What is no longer in the topology has nothing to show. -->
					<OverrideItem
						{o}
						{index}
						withTarget
						onselect={objectOf(index, o.target) ? () => show(o.target) : undefined}
					/>
				</li>
			{/each}
		</ul>
	{/each}
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
	li {
		padding: 2px 4px;
	}
	li + li {
		border-top: 1px solid var(--border);
	}
	.muted {
		margin: 2px 4px 6px;
		color: var(--muted);
		font-size: 12px;
	}
	.making {
		margin: 0 4px 6px;
	}
	.actions {
		margin: 0 4px 6px;
	}
	.actions button {
		padding: 2px 8px;
		font-size: 12px;
	}
</style>
