<!--
@component
The time slider for live state: the last day in 5-minute steps, with a bar
at each step as tall as how much went down then, so a branch outage stands
out from a single switch. Moving it back replays that moment in every view;
its right end, or Back to now, follows the present again. Play steps
forward a step a second until it catches up.
-->
<script lang="ts">
	import type { EventLog } from './api/state.ts';
	import { clock, downsBySteps, STEP_MS } from './history.ts';
	import { ui } from './state.svelte.ts';
	import { HEALTH_COLOR } from './theme.ts';

	const { log }: { log: EventLog } = $props();

	const PLAY_MS = 1000;

	// Position i is the i-th step boundary in the log; the last position is now.
	const start = $derived(Math.ceil(Date.parse(log.since) / STEP_MS) * STEP_MS);
	const last = $derived(Math.floor((Date.parse(log.until) - start) / STEP_MS) + 1);
	const position = $derived(
		ui.at ? Math.min(last, Math.round((Date.parse(ui.at) - start) / STEP_MS)) : last
	);
	// Square-root heights keep one device visible beside a whole branch.
	const bars = $derived.by(() => {
		const downs = [...downsBySteps(log.events, start)].filter(([i]) => i >= 0);
		const most = Math.sqrt(Math.max(1, ...downs.map(([, n]) => n)));
		return downs.map(([i, n]) => ({ i, n, h: Math.max(0.15, Math.sqrt(n) / most) }));
	});
	const when = $derived(ui.at ? `${clock(ui.at)} · ${ago(Date.parse(ui.at))}` : 'Now');

	let playing = $state(false);

	function moveTo(i: number): void {
		if (i >= last) {
			ui.at = null;
			return;
		}
		ui.at = new Date(start + Math.max(0, i) * STEP_MS).toISOString();
	}

	function ago(at: number): string {
		const minutes = Math.round((Date.parse(log.until) - at) / 60_000);
		const hours = Math.floor(minutes / 60);
		return hours ? `${hours} h ${minutes % 60} min ago` : `${minutes} min ago`;
	}

	// Back at the present, there is nothing more to play.
	$effect(() => {
		if (!ui.at) playing = false;
	});

	$effect(() => {
		if (!playing) return;
		const timer = setInterval(() => moveTo(position + 1), PLAY_MS);
		return () => clearInterval(timer);
	});
</script>

<div class="timeline" role="group" aria-label="Time">
	<button
		aria-label="5 minutes earlier"
		disabled={position <= 0}
		onclick={() => moveTo(position - 1)}>‹</button
	>
	<button
		class="play"
		aria-pressed={playing}
		disabled={!ui.at}
		title={ui.at ? 'Step forward a step a second' : 'Move back in time first'}
		onclick={() => (playing = !playing)}>{playing ? 'Pause' : 'Play'}</button
	>
	<button aria-label="5 minutes later" disabled={!ui.at} onclick={() => moveTo(position + 1)}
		>›</button
	>
	<div class="track">
		<svg viewBox="-0.5 0 {last + 1} 1" preserveAspectRatio="none" aria-hidden="true">
			{#each bars as b (b.i)}
				<rect x={b.i - 0.5} y={1 - b.h} width="1" height={b.h} fill={HEALTH_COLOR.down} />
			{/each}
		</svg>
		<input
			type="range"
			min="0"
			max={last}
			step="1"
			value={position}
			aria-label="Moment to show"
			aria-valuetext={when}
			oninput={(e) => moveTo(Number(e.currentTarget.value))}
		/>
	</div>
	<span class="when" class:past={ui.at !== null}>{when}</span>
	{#if ui.at}<button onclick={() => moveTo(last)}>Back to now</button>{/if}
</div>

<style>
	.timeline {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 4px 14px;
		background: var(--panel);
		border-bottom: 1px solid var(--border);
		font-size: 12px;
	}
	.timeline button {
		padding: 2px 8px;
	}
	.play {
		min-width: 52px;
	}
	.track {
		position: relative;
		flex: 1;
		min-width: 120px;
		display: flex;
		flex-direction: column;
	}
	/* Marks line up with the slider's thumb, which stops half its width from each end. */
	svg {
		height: 12px;
		margin: 0 8px;
		width: calc(100% - 16px);
	}
	input {
		width: 100%;
		margin: 0;
		accent-color: var(--live);
	}
	.when {
		min-width: 150px;
		color: var(--muted);
		white-space: nowrap;
	}
	.when.past {
		color: var(--selected);
	}
</style>
