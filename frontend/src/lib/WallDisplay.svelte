<!--
@component
The NOC wall display, for a screen no one sits at. A bar across the top
gives the time, how fresh live state is, and how many problems of each kind
no one is on yet; below it, the views show in turn an overview of the
network, with a small label, then each of those problems close up, with a
large caption saying where it is and a bar showing how long until the next. Moving the mouse shows controls;
Space pauses, the arrow keys step, and Escape leaves.
-->
<script lang="ts">
	import { onMount, untrack } from 'svelte';
	import type { Problem } from './api/analysis.ts';
	import type { LiveIndex } from './live.ts';
	import { MARK } from './problem-kinds.ts';
	import { select, ui, type Selection } from './state.svelte.ts';
	import { siteOf, type TopologyIndex } from './topology.ts';
	import { slidesFor, tally, type Slide } from './wall.ts';

	const {
		index,
		problems,
		live,
		liveProblem
	}: {
		index: TopologyIndex;
		problems: Problem[];
		live: LiveIndex | null;
		liveProblem: string | null;
	} = $props();

	const CONTROLS_MS = 3000;

	const slides = $derived(slidesFor(problems));
	const counts = $derived(tally(problems));
	let position = $state(0);
	let shownAt = $state(Date.now());
	let now = $state(Date.now());
	let controls = $state(false);
	let hideControls: ReturnType<typeof setTimeout> | undefined;
	const slide = $derived(slides[position % Math.max(1, slides.length)]);

	function key(s: Slide | undefined): string {
		return !s ? '' : s.kind === 'overview' ? s.view : s.problem.id;
	}

	function show(next: number): void {
		const count = slides.length;
		if (count === 0) return;
		position = ((next % count) + count) % count;
		shownAt = Date.now();
	}

	// Put the slide on screen whenever it changes, including when the list
	// shifts under it because a problem cleared.
	let applied = '';
	$effect(() => {
		const s = slide;
		if (key(s) === applied) return;
		applied = key(s);
		untrack(() => {
			if (!s) return;
			if (s.kind === 'overview') {
				ui.problem = null;
				select(null);
				ui.view = s.view;
				ui.fitRequest++;
			} else {
				ui.view = 'geo';
				ui.problem = s.problem.id;
				select(s.problem.target, true);
			}
		});
	});

	// Move on after the dwell time, unless paused.
	$effect(() => {
		if (ui.wall.paused) return;
		const p = position;
		// Stepping restarts the wait, even onto the same slide when there is only one.
		void shownAt;
		const timer = setTimeout(() => show(p + 1), ui.wall.dwell * 1000);
		return () => clearTimeout(timer);
	});

	onMount(() => {
		const clock = setInterval(() => (now = Date.now()), 1000);
		return () => {
			clearInterval(clock);
			clearTimeout(hideControls);
		};
	});

	function wake(): void {
		controls = true;
		clearTimeout(hideControls);
		hideControls = setTimeout(() => (controls = false), CONTROLS_MS);
	}

	function onkey(e: KeyboardEvent): void {
		if (e.key === ' ') ui.wall.paused = !ui.wall.paused;
		else if (e.key === 'ArrowRight') show(position + 1);
		else if (e.key === 'ArrowLeft') show(position - 1);
		else if (e.key === 'Escape') leave();
		else return;
		e.preventDefault();
		wake();
	}

	async function fullScreen(): Promise<void> {
		try {
			await document.documentElement.requestFullscreen();
		} catch (e) {
			// Some browsers and embedded screens refuse; the wall still fills the window.
			console.warn('Full screen refused', e);
		}
	}

	function leave(): void {
		ui.wall.on = false;
		ui.wall.paused = false;
		if (document.fullscreenElement) void document.exitFullscreen();
	}

	/** The sites a problem is at, named, for its caption. */
	function where(target: Selection): string {
		const codes =
			target.kind === 'device'
				? [siteOf(index, target.id)]
				: target.kind === 'site'
					? [target.id]
					: target.ids.flatMap((id) => {
							const link = index.links.get(id);
							return link ? [siteOf(index, link.a.device), siteOf(index, link.b.device)] : [];
						});
		return [...new Set(codes)]
			.map((code) => `${code} · ${index.sites.get(code)?.name ?? code}`)
			.join(' and ');
	}

	const time = (ms: number) =>
		new Date(ms).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
</script>

<svelte:window onkeydown={onkey} onmousemove={wake} />

<div class="bar">
	<span class="brand"><img src="/favicon.svg" alt="" width="26" height="26" />Sunstone</span>
	<span class="counts" aria-live="polite">
		{#if counts.kinds.length === 0}<span class="clear">No open problems</span>{/if}
		{#each counts.kinds as k (k.kind)}
			<span class="count"
				><i style:--c={MARK[k.kind].color} aria-hidden="true">{MARK[k.kind].glyph}</i>{k.count}
				{k.short}</span
			>
		{/each}
		{#if counts.handled}<span class="handled">{counts.handled} being handled</span>{/if}
	</span>
	<span class="time">
		<b>{time(now)}</b>
		<small>
			{#if liveProblem}
				Live state unavailable: {liveProblem}
			{:else if live}
				{live.state.source} · as of {new Date(live.state.generated_at).toLocaleTimeString()}
			{:else}
				Loading live state…
			{/if}
		</small>
	</span>
</div>

{#if slide}
	<div class="caption" class:overview={slide.kind === 'overview'} aria-live="polite">
		{#if slide.kind === 'overview'}
			<p class="what">{slide.label}</p>
		{:else}
			<p class="which">Problem {slide.number} of {slide.of} · at {where(slide.problem.target)}</p>
			<p class="what">
				<i style:--c={MARK[slide.problem.kind].color} aria-hidden="true"
					>{MARK[slide.problem.kind].glyph}</i
				>{slide.problem.title}
			</p>
			{#if slide.problem.detail}<p class="detail">{slide.problem.detail}</p>{/if}
		{/if}
		{#key shownAt}
			<div
				class="progress"
				style:animation-duration="{ui.wall.dwell}s"
				style:animation-play-state={ui.wall.paused ? 'paused' : 'running'}
			></div>
		{/key}
	</div>
{/if}

<div
	class="controls"
	class:shown={controls || ui.wall.paused}
	role="toolbar"
	aria-label="Wall display"
>
	<button aria-label="Previous" onclick={() => show(position - 1)}>‹</button>
	<button onclick={() => (ui.wall.paused = !ui.wall.paused)}>
		{ui.wall.paused ? 'Resume' : 'Pause'}
	</button>
	<button aria-label="Next" onclick={() => show(position + 1)}>›</button>
	<button onclick={fullScreen}>Full screen</button>
	<button onclick={leave}>Leave wall</button>
</div>

<style>
	.bar {
		display: flex;
		align-items: center;
		gap: 28px;
		padding: 10px 20px;
		background: var(--panel);
		border-bottom: 1px solid var(--border);
		font-size: 20px;
	}
	.brand {
		display: flex;
		align-items: center;
		gap: 10px;
		font-weight: 600;
	}
	.counts {
		display: flex;
		flex-wrap: wrap;
		gap: 6px 22px;
		flex: 1;
	}
	.count {
		display: inline-flex;
		align-items: center;
		gap: 8px;
	}
	.clear,
	.handled {
		color: var(--muted);
	}
	i {
		display: inline-grid;
		place-items: center;
		width: 24px;
		height: 24px;
		border-radius: 50%;
		background: var(--c);
		color: var(--bg);
		font-style: normal;
		font-size: 16px;
		font-weight: 700;
	}
	.time {
		display: flex;
		flex-direction: column;
		align-items: flex-end;
	}
	.time b {
		font-size: 28px;
		font-variant-numeric: tabular-nums;
	}
	.time small {
		color: var(--muted);
		font-size: 14px;
	}
	.caption {
		position: fixed;
		left: 50%;
		bottom: 72px;
		transform: translateX(-50%);
		z-index: 20;
		min-width: 420px;
		max-width: min(900px, 90vw);
		padding: 14px 22px 0;
		background: rgb(15 20 25 / 0.92);
		border: 1px solid var(--border);
		border-radius: 8px;
		overflow: hidden;
	}
	.caption p {
		margin: 0 0 6px;
	}
	/* An overview needs the whole screen; its label sits small at the top. */
	.caption.overview {
		top: 86px;
		bottom: auto;
		min-width: 0;
		padding: 6px 16px 0;
	}
	.caption.overview .what {
		font-size: 18px;
		font-weight: normal;
	}
	.which {
		color: var(--muted);
		font-size: 15px;
	}
	.what {
		display: flex;
		align-items: center;
		gap: 12px;
		font-size: 30px;
		font-weight: 600;
	}
	.what i {
		width: 32px;
		height: 32px;
		font-size: 22px;
	}
	.detail {
		color: var(--muted);
		font-size: 18px;
	}
	.progress {
		height: 4px;
		margin: 10px -22px 0;
		background: var(--live);
		transform-origin: left;
		animation: fill linear forwards;
	}
	@keyframes fill {
		from {
			transform: scaleX(0);
		}
		to {
			transform: scaleX(1);
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.progress {
			animation: none;
		}
	}
	.controls {
		position: fixed;
		top: 86px;
		right: 64px;
		z-index: 21;
		display: flex;
		gap: 6px;
		opacity: 0;
		pointer-events: none;
		transition: opacity 0.2s;
	}
	.controls.shown {
		opacity: 1;
		pointer-events: auto;
	}
</style>
