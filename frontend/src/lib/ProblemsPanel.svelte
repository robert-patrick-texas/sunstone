<!--
@component
Problems in the live state shown (now, or a replayed moment), most urgent
first, grouped by kind or by region, after the networks that are not
working as they should: the whole network and named networks degraded or
offline, or working over something degraded, and the resources degraded
or offline. The server finds them, once per moment for every viewer. With
networks chosen in the header, only their problems are listed, and only
they and the networks beneath them; every resource stays listed, since
none belongs to a network. High-priority problems come first, on their
own, marked High. Within each kind, problems someone has acknowledged,
then ones that planned maintenance accounts for, come after the rest,
dimmed and marked. An outage or link down names the networks it takes
something from, and what: what fixing it would bring back; a link someone
downstream answers for first says who. Clicking one selects it, brings it
into view, and shows its impact in every view; clicking it again stops
showing the impact.
-->
<script lang="ts">
	import { problemNetworks } from './across.ts';
	import type { Problem } from './api/analysis.ts';
	import type { OnCall } from './api/oncall.ts';
	import type { Window } from './api/operations.ts';
	import { personOf } from './oncall.ts';
	import { grouped, handling, MARK } from './problem-kinds.ts';
	import { resourcesNeeding } from './resources.ts';
	import { scopeOf } from './scope.ts';
	import type { StatusReport } from './api/status.ts';
	import { select, showNetwork, showProblem, ui } from './state.svelte.ts';
	import { needing, STATUS_COLOR, STATUS_GLYPH, STATUS_LABEL, statusWord } from './status.ts';
	import type { TopologyIndex } from './topology.ts';

	const {
		index,
		problems,
		windows,
		oncall,
		status = null
	}: {
		index: TopologyIndex;
		problems: Problem[];
		windows: Window[];
		oncall: OnCall | null;
		/** Every network's status, if known. */
		status?: StatusReport | null;
	} = $props();
	const scope = $derived(scopeOf(index, ui.networks));
	const networks = $derived(
		(status ? needing(status) : []).filter(
			(n) =>
				scope.networks.length === 0 ||
				(n.network !== null && (scope.networks.includes(n.network) || scope.under.has(n.network)))
		)
	);
	const resources = $derived(status ? resourcesNeeding(status) : []);
	const name = (id: string) => (oncall ? personOf(oncall, id).name : id);

	const groups = $derived(grouped(problems, { index, scope, by: ui.problemsBy }));
	const elsewhere = $derived(problems.length - groups.reduce((n, g) => n + g.items.length, 0));
	const titles = $derived(new Map(windows.map((w) => [w.id, w.title])));
	let list: HTMLElement;

	// Stepping through problems from the keyboard keeps the one shown in sight.
	$effect(() => {
		if (!ui.problem) return;
		list
			.querySelector(`[data-problem="${CSS.escape(ui.problem)}"]`)
			?.scrollIntoView({ block: 'nearest' });
	});
</script>

<section aria-label="Problems" bind:this={list}>
	{#if problems.length > 0}
		<div class="by" role="group" aria-label="Group problems">
			<button aria-pressed={ui.problemsBy === 'kind'} onclick={() => (ui.problemsBy = 'kind')}
				>By kind</button
			>
			<button aria-pressed={ui.problemsBy === 'region'} onclick={() => (ui.problemsBy = 'region')}
				>By region</button
			>
		</div>
	{/if}
	{#if problems.length === elsewhere}
		<p class="muted">
			{scope.networks.length ? `No problems in ${scope.networks.join(' or ')}` : 'Nothing wrong'}
			{ui.at ? 'at this moment' : 'in the latest snapshot'}.
		</p>
	{:else}
		<p class="muted">Click one to see it and what it affects.</p>
	{/if}
	{#if elsewhere > 0}
		<p class="muted">{elsewhere} not in {scope.networks.join(' or ')}.</p>
	{/if}
	{#if networks.length}
		<h3>Networks ({networks.length})</h3>
		<ul>
			{#each networks as n (n.network ?? '')}
				<li>
					<button
						class="problem"
						aria-pressed={n.network !== null &&
							ui.networks.length === 1 &&
							ui.networks[0] === n.network}
						onclick={() => (n.network ? showNetwork(n.network) : (ui.networks = []))}
					>
						<i style:--c={STATUS_COLOR[n.status]} aria-hidden="true"
							>{STATUS_GLYPH[n.status] || '*'}</i
						>
						<span>
							<span class="title">{n.name} {statusWord(n).toLowerCase()}</span>
							<span class="detail">{[...n.reasons, ...n.caveats].slice(0, 2).join(' · ')}</span>
						</span>
					</button>
				</li>
			{/each}
		</ul>
	{/if}
	{#if resources.length}
		<h3>Resources ({resources.length})</h3>
		<ul>
			{#each resources as r (r.name)}
				<li>
					<button
						class="problem"
						aria-pressed={ui.selection?.kind === 'resource' && ui.selection.id === r.name}
						onclick={() => select({ kind: 'resource', id: r.name }, true)}
					>
						<i style:--c={STATUS_COLOR[r.status]} aria-hidden="true">{STATUS_GLYPH[r.status]}</i>
						<span>
							<span class="title">{r.name} {STATUS_LABEL[r.status].toLowerCase()}</span>
							{#if r.reasons.length}<span class="detail">{r.reasons[0]}</span>{/if}
						</span>
					</button>
				</li>
			{/each}
		</ul>
	{/if}
	{#each groups as group (group.key)}
		<h3>{group.label} ({group.items.length})</h3>
		<ul>
			{#each group.items as problem (problem.id)}
				{@const across = problemNetworks(index, problem.networks)}
				<li>
					<button
						class="problem"
						class:handled={handling(problem) > 0}
						class:high={problem.priority === 'high'}
						data-problem={problem.id}
						aria-pressed={ui.problem === problem.id}
						onclick={() => showProblem(problem)}
					>
						<i style:--c={MARK[problem.kind].color} aria-hidden="true">{MARK[problem.kind].glyph}</i
						>
						<span>
							<span class="title"
								>{#if problem.priority === 'high'}<b class="high-mark">High</b>
								{/if}{problem.title}</span
							>
							{#if problem.detail}<span class="detail">{problem.detail}</span>{/if}
							{#if across}<span class="detail">{across}</span>{/if}
							{#if problem.responsible}
								<span class="detail">{problem.responsible} answers first</span>
							{/if}
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
							{#if problem.incident}
								<span class="tag incident">Incident {problem.incident}</span>
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
	.by {
		display: flex;
		gap: 4px;
		margin: 0 4px 8px;
	}
	.by button {
		padding: 1px 8px;
		border-radius: 10px;
		font-size: 12px;
		color: var(--muted);
	}
	.by button[aria-pressed='true'] {
		color: var(--text);
		border-color: var(--live);
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
	/* High priority: a stripe in the accent, besides the mark in words. */
	.problem.high {
		box-shadow: inset 3px 0 0 var(--accent);
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
	.tag.incident::before {
		background: var(--down);
	}
	.detail {
		display: block;
		color: var(--muted);
		font-size: 12px;
	}
</style>
