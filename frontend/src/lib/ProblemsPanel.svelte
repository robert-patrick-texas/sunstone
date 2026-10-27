<!--
@component
Current problems in live state, most urgent first, grouped by kind. Clicking
one selects it, brings it into view, and shows its impact in every view;
clicking it again stops showing the impact.
-->
<script lang="ts">
	import { PROBLEM_KINDS, type Problem, type ProblemKind } from './problems.ts';
	import { showProblem, ui } from './state.svelte.ts';
	import { HEALTH_COLOR } from './theme.ts';

	const { problems }: { problems: Problem[] } = $props();

	// Status colors, each with its own mark, so color is never the only cue.
	const MARK: Record<ProblemKind, { color: string; glyph: string }> = {
		outage: { color: HEALTH_COLOR.down, glyph: '×' },
		'link-down': { color: HEALTH_COLOR.down, glyph: '×' },
		congested: { color: HEALTH_COLOR.down, glyph: '%' },
		loss: { color: HEALTH_COLOR.degraded, glyph: '!' },
		busy: { color: HEALTH_COLOR.degraded, glyph: '%' },
		nodata: { color: HEALTH_COLOR.nodata, glyph: '?' }
	};

	const groups = $derived(
		PROBLEM_KINDS.map((k) => ({ ...k, items: problems.filter((p) => p.kind === k.kind) })).filter(
			(g) => g.items.length > 0
		)
	);
</script>

<aside class="problems" aria-label="Problems">
	<h2>Problems <span class="count">{problems.length}</span></h2>
	{#if problems.length === 0}
		<p class="muted">Nothing wrong in the latest snapshot.</p>
	{:else}
		<p class="muted">Click one to see it and what it affects.</p>
	{/if}
	{#each groups as group (group.kind)}
		<h3>{group.label} ({group.items.length})</h3>
		<ul>
			{#each group.items as problem (problem.id)}
				<li>
					<button
						class="problem"
						aria-pressed={ui.problem === problem.id}
						onclick={() => showProblem(problem)}
					>
						<i style:--c={MARK[problem.kind].color} aria-hidden="true">{MARK[problem.kind].glyph}</i
						>
						<span>
							<span class="title">{problem.title}</span>
							{#if problem.detail}<span class="detail">{problem.detail}</span>{/if}
						</span>
					</button>
				</li>
			{/each}
		</ul>
	{/each}
</aside>

<style>
	.problems {
		flex: none;
		width: min(300px, 30vw);
		overflow-y: auto;
		background: var(--panel);
		border-right: 1px solid var(--border);
		padding: 12px 10px;
		font-size: 13px;
	}
	h2 {
		margin: 0 4px 4px;
		font-size: 15px;
	}
	.count {
		color: var(--muted);
		font-weight: normal;
	}
	h3 {
		margin: 14px 4px 4px;
		font-size: 12px;
		font-weight: normal;
		color: var(--muted);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}
	.muted {
		margin: 0 4px;
		color: var(--muted);
		font-size: 12px;
	}
	ul {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	.problem {
		display: flex;
		gap: 8px;
		width: 100%;
		padding: 5px 6px;
		border: 1px solid transparent;
		background: none;
		text-align: left;
	}
	.problem:hover {
		background: var(--panel-2);
	}
	.problem[aria-pressed='true'] {
		background: var(--panel-2);
		border-color: var(--selected);
	}
	i {
		flex: none;
		display: inline-grid;
		place-items: center;
		width: 16px;
		height: 16px;
		margin-top: 1px;
		border-radius: 50%;
		background: var(--c);
		color: var(--bg);
		font-style: normal;
		font-size: 11px;
		font-weight: 700;
	}
	.title {
		display: block;
		word-break: break-word;
	}
	.detail {
		display: block;
		color: var(--muted);
		font-size: 12px;
	}
</style>
