<!--
@component
Problems in the live state shown (now, or a replayed moment), most urgent
first, grouped by kind. The server finds them, once per moment for every
viewer. Within each kind, problems someone has acknowledged, then ones that
planned maintenance accounts for, come after the rest, dimmed and marked.
Clicking one selects it, brings it into view, and shows its impact in every
view; clicking it again stops showing the impact.
-->
<script lang="ts">
	import type { Problem } from './api/analysis.ts';
	import type { OnCall } from './api/oncall.ts';
	import type { Window } from './api/operations.ts';
	import { personOf } from './oncall.ts';
	import { grouped, handling, MARK } from './problem-kinds.ts';
	import { showProblem, ui } from './state.svelte.ts';

	const {
		problems,
		windows,
		oncall
	}: { problems: Problem[]; windows: Window[]; oncall: OnCall | null } = $props();
	const name = (id: string) => (oncall ? personOf(oncall, id).name : id);

	const groups = $derived(grouped(problems));
	const titles = $derived(new Map(windows.map((w) => [w.id, w.title])));
	let list: HTMLElement;

	// Stepping through problems from the keyboard keeps the one shown in sight.
	$effect(() => {
		if (!ui.problem) return;
		list.querySelector('[aria-pressed="true"]')?.scrollIntoView({ block: 'nearest' });
	});
</script>

<section aria-label="Problems" bind:this={list}>
	{#if problems.length === 0}
		<p class="muted">Nothing wrong {ui.at ? 'at this moment' : 'in the latest snapshot'}.</p>
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
						class:handled={handling(problem) > 0}
						aria-pressed={ui.problem === problem.id}
						onclick={() => showProblem(problem)}
					>
						<i style:--c={MARK[problem.kind].color} aria-hidden="true">{MARK[problem.kind].glyph}</i
						>
						<span>
							<span class="title">{problem.title}</span>
							{#if problem.detail}<span class="detail">{problem.detail}</span>{/if}
							{#if problem.planned.length}
								<span class="tag planned"
									>Planned: {problem.planned
										.map((id) => titles.get(id) ?? 'maintenance')
										.join(', ')}</span
								>
							{/if}
							{#if problem.paging && !problem.paging.stopped}
								{@const last = problem.paging.notified.at(-1)}
								<span class="tag paged">Paged{last ? `: ${name(last.person)}` : ''}</span>
							{/if}
							{#if problem.ack}
								<span class="tag ack"
									>On it: {problem.ack.by}{problem.ack.note ? ` · ${problem.ack.note}` : ''}</span
								>
							{/if}
						</span>
					</button>
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
	.handled {
		opacity: 0.65;
	}
	.tag {
		display: block;
		margin-top: 2px;
		font-size: 11px;
		color: var(--text);
	}
	.tag::before {
		content: '';
		display: inline-block;
		width: 6px;
		height: 6px;
		margin-right: 5px;
		border-radius: 50%;
		background: var(--live);
	}
	.tag.ack::before {
		background: var(--selected);
	}
	.tag.paged::before {
		background: var(--path);
	}
	.detail {
		display: block;
		color: var(--muted);
		font-size: 12px;
	}
</style>
