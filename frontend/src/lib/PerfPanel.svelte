<!--
@component
Frame rate, the longest the page was blocked, and timings of the heavy
work, in a corner of the page. Shown only when the page is opened with
`?perf`. It reads the numbers twice a second.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import { perf, resetPerf } from './perf.ts';

	const REFRESH_MS = 500;

	let shown = $state.raw({ ...perf, timings: { ...perf.timings } });
	const rows = $derived(Object.entries(shown.timings).sort(([a], [b]) => a.localeCompare(b)));

	onMount(() => {
		const timer = setInterval(
			() => (shown = { ...perf, timings: { ...perf.timings } }),
			REFRESH_MS
		);
		return () => clearInterval(timer);
	});
</script>

<aside class="perf" aria-label="Performance">
	<p>
		<b>{shown.fps}</b> fps · worst frame <b>{shown.worstFrameMs}</b> ms · longest block
		<b>{shown.longestTaskMs}</b> ms
		<button onclick={resetPerf}>Reset</button>
	</p>
	<table>
		<thead><tr><th>Work</th><th>Last</th><th>Max</th><th>Mean</th><th>Runs</th></tr></thead>
		<tbody>
			{#each rows as [name, t] (name)}
				<tr>
					<td>{name}</td>
					<td>{t.last.toFixed(0)}</td>
					<td>{t.max.toFixed(0)}</td>
					<td>{(t.total / t.count).toFixed(0)}</td>
					<td>{t.count}</td>
				</tr>
			{/each}
		</tbody>
	</table>
</aside>

<style>
	.perf {
		position: fixed;
		right: 8px;
		bottom: 8px;
		z-index: 50;
		padding: 6px 8px;
		background: rgb(15 20 25 / 0.92);
		border: 1px solid var(--border);
		border-radius: 6px;
		font-size: 11px;
		font-variant-numeric: tabular-nums;
	}
	p {
		margin: 0 0 4px;
	}
	button {
		margin-left: 6px;
		padding: 0 6px;
		font-size: 11px;
	}
	th,
	td {
		padding: 0 6px 0 0;
		text-align: right;
	}
	th:first-child,
	td:first-child {
		text-align: left;
	}
	th {
		color: var(--muted);
		font-weight: normal;
	}
</style>
