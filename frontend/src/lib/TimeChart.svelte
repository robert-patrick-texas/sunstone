<!--
@component
Readings over the last day, for the details panel: one line per series,
broken where there was no reading, with a strip of states under it (down,
packet loss, no data) and dashed marks at given levels. The key under the
chart names each line with its latest value. Hovering, or moving with the
arrow keys once focused, reads out every series at that time on the line
above the chart; clicking, or Enter, replays that moment. The moment being
replayed is marked.
-->
<script lang="ts">
	import { clock } from './history.ts';

	interface Series {
		label: string;
		color: string;
		values: (number | null)[];
	}
	interface StripState {
		label: string;
		color: string;
	}

	const {
		label,
		start,
		step,
		series,
		unit,
		max = null,
		levels = [],
		strip = [],
		at = null,
		onpick
	}: {
		/** What the chart shows, for screen readers. */
		label: string;
		/** Time of the first reading, and between readings, in milliseconds. */
		start: number;
		step: number;
		series: Series[];
		unit: string;
		/** Top of the scale, or null to fit the data. */
		max?: number | null;
		/** Values marked with a dashed line. */
		levels?: number[];
		/** A state per reading, or null where there is nothing to mark. */
		strip?: (StripState | null)[];
		/** The moment being replayed, in milliseconds, or null. */
		at?: number | null;
		onpick: (time: number) => void;
	} = $props();

	const W = 1000;
	const H = 100;

	const count = $derived(Math.max(1, ...series.map((s) => s.values.length)));
	const top = $derived(max ?? niceTop(series.flatMap((s) => s.values)));
	const marked = $derived(at === null ? null : Math.round((at - start) / step));
	const states = $derived([
		...new Map(strip.flatMap((s) => (s ? [[s.label, s] as const] : []))).values()
	]);
	let hover = $state<number | null>(null);

	function x(i: number): number {
		return count > 1 ? (i / (count - 1)) * W : 0;
	}

	function y(v: number): number {
		return H - (Math.min(v, top) / top) * H;
	}

	function path(values: (number | null)[]): string {
		let d = '';
		let drawing = false;
		values.forEach((v, i) => {
			if (v === null) {
				drawing = false;
				return;
			}
			const point = `${x(i).toFixed(1)},${y(v).toFixed(1)}`;
			// A lone reading is a zero-length segment, drawn as a dot by its round caps.
			d += drawing ? `L${point}` : `M${point}L${point}`;
			drawing = true;
		});
		return d;
	}

	/** 1, 2, or 5 times a power of ten, with some room above the largest value. */
	function niceTop(values: (number | null)[]): number {
		const most = 1.15 * Math.max(1, ...values.filter((v): v is number => v !== null));
		const power = 10 ** Math.floor(Math.log10(most));
		return ([1, 2, 5, 10].find((m) => m * power >= most) ?? 10) * power;
	}

	function format(v: number | null | undefined): string {
		return v === null || v === undefined ? 'no reading' : `${+v.toFixed(1)}${unit}`;
	}

	function latest(values: (number | null)[]): number | null {
		for (let i = values.length - 1; i >= 0; i--) if (values[i] !== null) return values[i] ?? null;
		return null;
	}

	function readout(i: number): string {
		const parts = series.map((s) => `${s.label} ${format(s.values[i])}`);
		const state = strip[i];
		return [
			clock(new Date(start + i * step).toISOString()),
			...parts,
			...(state ? [state.label] : [])
		].join(' · ');
	}

	function left(i: number): string {
		return `${count > 1 ? (i / (count - 1)) * 100 : 0}%`;
	}

	function onmove(e: PointerEvent): void {
		const box = (e.currentTarget as HTMLElement).getBoundingClientRect();
		const i = Math.round(((e.clientX - box.left) / box.width) * (count - 1));
		hover = Math.max(0, Math.min(count - 1, i));
	}

	function onkey(e: KeyboardEvent): void {
		const now = hover ?? count - 1;
		if (e.key === 'ArrowLeft') hover = Math.max(0, now - 1);
		else if (e.key === 'ArrowRight') hover = Math.min(count - 1, now + 1);
		else if (e.key === 'Enter') onpick(start + now * step);
		else return;
		e.preventDefault();
	}
</script>

<figure class="chart">
	<div class="readout" aria-hidden="true">{hover === null ? '' : readout(hover)}</div>
	<div
		class="plot"
		role="slider"
		tabindex="0"
		aria-label="{label}. Arrow keys read each time; Enter replays it."
		aria-valuemin={0}
		aria-valuemax={count - 1}
		aria-valuenow={hover ?? count - 1}
		aria-valuetext={readout(hover ?? count - 1)}
		onpointermove={onmove}
		onpointerleave={() => (hover = null)}
		onblur={() => (hover = null)}
		onclick={() => hover !== null && onpick(start + hover * step)}
		onkeydown={onkey}
	>
		<svg viewBox="0 0 {W} {H}" preserveAspectRatio="none" aria-hidden="true">
			{#each levels as level (level)}
				<line class="level" x1="0" x2={W} y1={y(level)} y2={y(level)} />
			{/each}
			{#each series as s (s.label)}
				<path d={path(s.values)} stroke={s.color} />
			{/each}
		</svg>
		<span class="top">{top}{unit}</span>
		{#if marked !== null && marked >= 0 && marked < count}
			<div class="marker" style:left={left(marked)}></div>
		{/if}
		{#if hover !== null}
			<div class="cross" style:left={left(hover)}></div>
		{/if}
	</div>
	{#if states.length}
		<svg class="strip" viewBox="-0.5 0 {count} 1" preserveAspectRatio="none" aria-hidden="true">
			{#each strip as s, i (i)}
				{#if s}<rect x={i - 0.5} y="0" width="1" height="1" fill={s.color} />{/if}
			{/each}
		</svg>
	{/if}
	<div class="axis"><span>{clock(new Date(start).toISOString())}</span><span>now</span></div>
	<figcaption>
		{#each series as s (s.label)}
			<span
				><i class="line" style:background={s.color}></i>{s.label} {format(latest(s.values))}</span
			>
		{/each}
		{#each states as s (s.label)}
			<span><i class="box" style:background={s.color}></i>{s.label}</span>
		{/each}
	</figcaption>
</figure>

<style>
	.chart {
		margin: 6px 0 12px;
	}
	.plot {
		position: relative;
		height: 64px;
		border-bottom: 1px solid var(--border);
		cursor: crosshair;
	}
	.plot:focus-visible {
		outline: 1px solid var(--live);
		outline-offset: 2px;
	}
	svg {
		display: block;
		width: 100%;
		height: 100%;
		overflow: visible;
	}
	path {
		fill: none;
		stroke-width: 2;
		vector-effect: non-scaling-stroke;
		stroke-linejoin: round;
		stroke-linecap: round;
	}
	.level {
		stroke: var(--border);
		stroke-dasharray: 4 3;
		vector-effect: non-scaling-stroke;
	}
	.top {
		position: absolute;
		top: -2px;
		left: 0;
		font-size: 10px;
		color: var(--muted);
		background: var(--panel);
		padding-right: 4px;
	}
	.marker,
	.cross {
		position: absolute;
		top: 0;
		bottom: 0;
		width: 1px;
		pointer-events: none;
	}
	.marker {
		background: var(--selected);
	}
	.cross {
		background: var(--text);
		opacity: 0.6;
	}
	/* Holds its height while empty, so the chart does not jump on hover. */
	.readout {
		min-height: 16px;
		font-size: 11px;
		color: var(--text);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.strip {
		height: 5px;
		margin-top: 2px;
	}
	.axis {
		display: flex;
		justify-content: space-between;
		font-size: 10px;
		color: var(--muted);
	}
	figcaption {
		display: flex;
		flex-wrap: wrap;
		gap: 2px 12px;
		margin-top: 4px;
		font-size: 12px;
		color: var(--muted);
	}
	figcaption span {
		display: inline-flex;
		align-items: center;
		gap: 5px;
	}
	.line {
		width: 12px;
		height: 2px;
	}
	.box {
		width: 8px;
		height: 8px;
		border-radius: 2px;
	}
</style>
