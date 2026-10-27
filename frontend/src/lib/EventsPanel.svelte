<!--
@component
What changed over the last day, newest first, with devices at one site that
changed together as one row. Clicking a row replays that moment and selects
what changed. Categories can be turned off.
-->
<script lang="ts">
	import { SvelteSet } from 'svelte/reactivity';
	import type { EventLog } from './api/state.ts';
	import {
		clock,
		EVENT_CATEGORIES,
		eventRows,
		type EventCategory,
		type EventKind,
		type EventRow
	} from './history.ts';
	import { select, ui } from './state.svelte.ts';
	import { HEALTH_COLOR } from './theme.ts';
	import type { TopologyIndex } from './topology.ts';

	const {
		index,
		log,
		problem
	}: { index: TopologyIndex; log: EventLog | null; problem: string | null } = $props();

	const PAGE = 200;
	const RESOLVED = { color: HEALTH_COLOR.up, glyph: '✓' };
	// Status colors, each with its own mark, so color is never the only cue.
	const MARK: Record<EventKind, { color: string; glyph: string }> = {
		down: { color: HEALTH_COLOR.down, glyph: '×' },
		'link-down': { color: HEALTH_COLOR.down, glyph: '×' },
		congested: { color: HEALTH_COLOR.down, glyph: '%' },
		busy: { color: HEALTH_COLOR.degraded, glyph: '%' },
		loss: { color: HEALTH_COLOR.degraded, glyph: '!' },
		nodata: { color: HEALTH_COLOR.nodata, glyph: '?' },
		up: RESOLVED,
		'link-up': RESOLVED,
		'load-normal': RESOLVED,
		'loss-cleared': RESOLVED,
		reporting: RESOLVED
	};

	const shown = new SvelteSet<EventCategory>(EVENT_CATEGORIES.map((c) => c.category));
	let limit = $state(PAGE);
	const rows = $derived(log ? eventRows(index, log.events, shown) : []);
	const replayed = $derived(ui.at ? Date.parse(ui.at) : null);

	function toggle(category: EventCategory): void {
		if (!shown.delete(category)) shown.add(category);
	}

	function replay(row: EventRow): void {
		ui.at = row.at;
		select(row.target, true);
	}
</script>

<section class="events" aria-label="Events">
	<div class="filters" role="group" aria-label="Show">
		{#each EVENT_CATEGORIES as c (c.category)}
			<button aria-pressed={shown.has(c.category)} onclick={() => toggle(c.category)}
				>{c.label}</button
			>
		{/each}
	</div>
	{#if problem}
		<p class="muted">Events unavailable: {problem}</p>
	{:else if !log}
		<p class="muted">Loading events…</p>
	{:else if rows.length === 0}
		<p class="muted">Nothing changed in the last day.</p>
	{:else}
		<p class="muted">Click one to replay that moment.</p>
	{/if}
	<ol>
		{#each rows.slice(0, limit) as row (`${row.at} ${row.kind} ${row.title}`)}
			<li>
				<button
					class="event"
					aria-pressed={replayed === Date.parse(row.at)}
					onclick={() => replay(row)}
				>
					<time datetime={row.at}>{clock(row.at)}</time>
					<i style:--c={MARK[row.kind].color} aria-hidden="true">{MARK[row.kind].glyph}</i>
					<span>{row.title}</span>
				</button>
			</li>
		{/each}
	</ol>
	{#if rows.length > limit}
		<button class="more" onclick={() => (limit += PAGE)}>
			Show {Math.min(PAGE, rows.length - limit)} older
		</button>
	{/if}
</section>

<style>
	.filters {
		display: flex;
		flex-wrap: wrap;
		gap: 4px;
		margin: 0 4px 8px;
	}
	.filters button {
		padding: 1px 8px;
		border-radius: 10px;
		font-size: 12px;
		color: var(--muted);
	}
	.filters button[aria-pressed='true'] {
		color: var(--text);
		border-color: var(--live);
	}
	.muted {
		margin: 0 4px 6px;
		color: var(--muted);
		font-size: 12px;
	}
	ol {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	.event {
		display: flex;
		align-items: flex-start;
		gap: 8px;
		width: 100%;
		padding: 4px 6px;
		border: none;
		border-left: 2px solid transparent;
		border-radius: 0;
		background: none;
		text-align: left;
	}
	.event:hover {
		background: var(--panel-2);
	}
	/* Every row at the moment being replayed. */
	.event[aria-pressed='true'] {
		border-left-color: var(--selected);
	}
	time {
		flex: none;
		width: 64px;
		color: var(--muted);
		font-variant-numeric: tabular-nums;
	}
	i {
		flex: none;
		display: inline-grid;
		place-items: center;
		width: 16px;
		height: 16px;
		border-radius: 50%;
		background: var(--c);
		color: var(--bg);
		font-style: normal;
		font-size: 11px;
		font-weight: 700;
	}
	span {
		word-break: break-word;
	}
	.more {
		margin: 8px 4px;
	}
</style>
