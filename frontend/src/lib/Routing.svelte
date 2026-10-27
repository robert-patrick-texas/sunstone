<!--
@component
Where a problem goes: the team that owns it, whether it is urgent, and its
page. Before a page, it says whom the page would go to and lets someone
send it; after, who has been told, who is next and when, or why escalation
stopped. Sunstone only records the page and escalates it on paper: nothing
is sent. For circuits, it gives the carrier's NOC. When replaying, it shows
the page as it stood then, without the buttons.
-->
<script lang="ts">
	import { untrack } from 'svelte';
	import type { Problem } from './api/analysis.ts';
	import { sendPage, withdrawPage, type OnCall } from './api/oncall.ts';
	import { clock } from './history.ts';
	import { carriersFor, linksOf, personOf, wouldPage } from './oncall.ts';
	import { rememberName, showTeam, ui } from './state.svelte.ts';
	import type { TopologyIndex } from './topology.ts';

	const {
		index,
		problem,
		oncall,
		onchange
	}: {
		index: TopologyIndex;
		problem: Problem;
		oncall: OnCall | null;
		/** Called after a page is sent or withdrawn. */
		onchange: () => void;
	} = $props();

	let failure = $state<string | null>(null);
	let busy = $state(false);
	// Asked for once, if the browser does not know it yet, and kept while it
	// is typed; but not while the acknowledgement form above asks for it.
	const unnamed = !untrack(() => ui.person.trim());
	const askName = $derived(unnamed && problem.ack !== null && problem.ack !== undefined);

	const team = $derived(oncall?.teams.find((t) => t.id === problem.team));
	const steps = $derived(oncall && team ? wouldPage(oncall, team) : []);
	// An outage's circuits are where reach stops; a link problem's are its own.
	const carriers = $derived(
		oncall
			? carriersFor(
					oncall,
					index,
					problem.impact ? [...problem.impact.failed.links] : linksOf(problem.target)
				)
			: []
	);
	const name = (id: string) => (oncall ? personOf(oncall, id).name : id);
	const after = (minutes: number) => (minutes ? `after ${minutes} min` : 'at once');

	async function page(e: SubmitEvent): Promise<void> {
		e.preventDefault();
		if (!ui.person.trim()) {
			failure = 'Give your name in the box above first.';
			return;
		}
		rememberName(ui.person.trim());
		busy = true;
		try {
			await sendPage(problem.id, ui.person, location.href);
			failure = null;
			onchange();
		} catch (err) {
			failure = err instanceof Error ? err.message : String(err);
		} finally {
			busy = false;
		}
	}

	async function withdraw(): Promise<void> {
		try {
			await withdrawPage(problem.id);
			failure = null;
			onchange();
		} catch (err) {
			failure = err instanceof Error ? err.message : String(err);
		}
	}
</script>

{#if oncall && team}
	<div class="routing" role="group" aria-label="Paging">
		<p>
			<span class="phase" class:urgent={problem.urgency === 'high'}
				>{problem.urgency === 'high' ? 'Urgent' : 'Not urgent'}</span
			>
			<button class="link" onclick={() => showTeam(team.id)}>{team.name}</button>
		</p>
		{#if problem.paging}
			{@const paging = problem.paging}
			<ol class="notices">
				{#each paging.notified as n (n.to + n.at)}
					<li>
						Paged <b>{name(n.person)}</b> <span class="muted">({n.to}) at {clock(n.at)}</span>
					</li>
				{/each}
			</ol>
			<p class="muted">
				{#if paging.stopped === 'acknowledged'}
					Escalation stopped: someone acknowledged it.
				{:else if paging.stopped === 'cleared'}
					Escalation stopped: the problem cleared.
				{:else if paging.next}
					Pages {name(paging.next.person)} ({paging.next.to}) at {clock(paging.next.at)} unless someone
					acknowledges it first.
				{:else}
					Everyone in the escalation policy has been paged.
				{/if}
				Sent by {paging.page.by} at {clock(paging.page.at)}.
			</p>
			{#if ui.at === null && !paging.stopped}
				<p><button class="link" onclick={withdraw}>Withdraw page</button></p>
			{/if}
		{:else if ui.at === null}
			<p class="muted">
				A page would go to {steps
					.map((s) => `${s.person.name} (${s.to}) ${after(s.afterMin)}`)
					.join(', then ')}, unless someone acknowledges it.
			</p>
			<form class="page-form" onsubmit={page}>
				{#if askName}
					<input
						bind:value={ui.person}
						required
						maxlength="64"
						placeholder="Your name"
						aria-label="Your name"
						autocomplete="name"
					/>
				{/if}
				<button type="submit" disabled={busy}>Page {steps[0]?.person.name ?? team.name}</button>
			</form>
			<p class="note">Simulated: Sunstone records the page and escalates it; nothing is sent.</p>
		{/if}
		{#each carriers.slice(0, 3) as c (c.circuit)}
			<p>
				{c.provider} <span class="muted">· circuit {c.circuit}</span>
				{#if c.carrier}
					· NOC <a class="mono" href="tel:{c.carrier.phone.replaceAll(' ', '')}"
						>{c.carrier.phone}</a
					>
				{/if}
			</p>
		{/each}
		{#if failure}<p class="muted" role="alert">{failure}</p>{/if}
	</div>
{/if}

<style>
	.routing {
		margin: 8px 0;
		padding: 6px 8px;
		border: 1px solid var(--border);
		border-radius: 4px;
	}
	p {
		margin: 4px 0;
	}
	.phase {
		display: inline-block;
		margin-right: 6px;
		padding: 0 6px;
		border-radius: 8px;
		border: 1px solid var(--border);
		font-size: 11px;
		color: var(--muted);
	}
	.phase.urgent {
		border-color: var(--down);
		color: var(--text);
	}
	.notices {
		margin: 4px 0;
		padding-left: 18px;
	}
	.muted {
		color: var(--muted);
	}
	.note {
		color: var(--muted);
		font-size: 11px;
	}
	.page-form {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		margin: 6px 0 2px;
	}
	.page-form input {
		flex: 1 1 120px;
		font: inherit;
		color: var(--text);
		background: var(--bg);
		border: 1px solid var(--border);
		border-radius: 4px;
		padding: 3px 6px;
	}
	.link {
		border: none;
		background: none;
		padding: 0;
		color: var(--accent);
		cursor: pointer;
	}
	a {
		color: var(--accent);
	}
	.mono {
		font-family: ui-monospace, monospace;
		font-size: 12px;
	}
</style>
