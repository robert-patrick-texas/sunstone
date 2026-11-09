<!--
@component
Every override not withdrawn: flagged (locks the topology now says
otherwise of), applying, not applied and why, and expired, each with what
it is on, to renew or withdraw. Clicking what one is on selects it and
brings it into view: a port as its device, a port channel as its members.
-->
<script lang="ts">
	import type { OverrideNow } from './api/overrides.ts';
	import { lagMembers } from './connections.ts';
	import OverrideItem from './OverrideItem.svelte';
	import { lagId, objectOf, overrides } from './overrides.svelte.ts';
	import { select } from './state.svelte.ts';
	import type { TopologyIndex } from './topology.ts';

	const { index }: { index: TopologyIndex } = $props();

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

	function show({ target: of }: OverrideNow): void {
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
	{#if groups.length === 0}
		<p class="muted">
			No overrides. Make one from an object's details: rename it, give it an alias, tag or label it,
			hide it, or lock a field.
		</p>
	{/if}
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
						onselect={objectOf(index, o.target) ? show : undefined}
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
</style>
