<!--
@component
A tiny chart of one link's load over the last day, for a table row: the
busier direction as a muted line, with the stretches at 80% or more drawn
amber and at 95% or more red, red ticks along the bottom where the link was
down, and the moment being replayed marked. Its title gives the peak.
-->
<script lang="ts">
	import { clock } from './history.ts';
	import { COLOR, HEALTH_COLOR } from './theme.ts';

	const {
		values,
		down,
		start,
		step,
		at = null
	}: {
		values: (number | null)[];
		down: boolean[];
		/** Time of the first reading, and between readings, in milliseconds. */
		start: number;
		step: number;
		/** The moment being replayed, in milliseconds, or null. */
		at?: number | null;
	} = $props();

	const HIGH = 80;
	const CRITICAL = 95;

	const n = $derived(Math.max(1, values.length - 1));
	const line = $derived(segments(() => true));
	const high = $derived(segments((v) => v >= HIGH && v < CRITICAL));
	const critical = $derived(segments((v) => v >= CRITICAL));
	const marked = $derived(at === null ? null : Math.round((at - start) / step));
	const title = $derived.by(() => {
		let peak = -1;
		values.forEach((v, i) => {
			if (v !== null && (peak < 0 || v > (values[peak] ?? 0))) peak = i;
		});
		const busiest =
			peak < 0
				? 'No readings'
				: `Peak ${Math.round(values[peak] ?? 0)}% at ${clock(new Date(start + peak * step).toISOString())}`;
		const outages = down.filter((d, i) => d && !down[i - 1]).length;
		return outages ? `${busiest} · down ${outages} time${outages === 1 ? '' : 's'}` : busiest;
	});

	/** Path through the readings that pass a test, broken everywhere else. */
	function segments(keep: (v: number) => boolean): string {
		let d = '';
		let drawing = false;
		values.forEach((v, i) => {
			if (v === null || !keep(v)) {
				drawing = false;
				return;
			}
			const point = `${i},${100 - Math.min(v, 100)}`;
			// A lone reading is a zero-length segment, drawn as a dot by its round caps.
			d += drawing ? `L${point}` : `M${point}L${point}`;
			drawing = true;
		});
		return d;
	}
</script>

<svg viewBox="0 -4 {n} 108" preserveAspectRatio="none" role="img" aria-label={title}>
	<title>{title}</title>
	<path d={line} stroke={COLOR.muted} />
	<path d={high} stroke={HEALTH_COLOR.degraded} />
	<path d={critical} stroke={HEALTH_COLOR.down} />
	{#each down as d, i (i)}
		{#if d}<rect x={i - 0.5} y="80" width="1" height="24" fill={HEALTH_COLOR.down} />{/if}
	{/each}
	{#if marked !== null && marked >= 0 && marked <= n}
		<line x1={marked} x2={marked} y1="-4" y2="104" stroke={COLOR.selected} />
	{/if}
</svg>

<style>
	svg {
		display: inline-block;
		width: 64px;
		height: 16px;
		vertical-align: middle;
	}
	path,
	line {
		fill: none;
		stroke-width: 1.25;
		vector-effect: non-scaling-stroke;
		stroke-linecap: round;
	}
</style>
