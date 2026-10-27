<!--
@component
Who is on call, team by team, at the moment shown: what each team owns,
its primary and secondary with their phone numbers, until when, and who is
on next. Someone can cover a team's primary turn for a while, and covers
can be removed. Pages still escalating are listed first, and the carriers'
NOCs last. The team asked for (from the details panel or search) is
highlighted and brought into view.
-->
<script lang="ts">
	import type { Problem } from './api/analysis.ts';
	import { deleteCover, saveCover, type OnCall, type Person, type TeamNow } from './api/oncall.ts';
	import { clock } from './history.ts';
	import { personOf } from './oncall.ts';
	import { localTime, rememberName, showProblem, ui } from './state.svelte.ts';

	const {
		oncall,
		problem,
		problems,
		onchange
	}: {
		oncall: OnCall | null;
		/** Why on-call data could not be loaded, if it could not. */
		problem: string | null;
		problems: Problem[];
		/** Called after a cover is saved or removed. */
		onchange: () => void;
	} = $props();

	interface Draft {
		team: string;
		person: string;
		start: string;
		end: string;
		note: string;
	}

	const HOUR_MS = 60 * 60_000;

	let draft = $state<Draft | null>(null);
	let failure = $state<string | null>(null);
	let list: HTMLElement;
	const escalating = $derived(problems.filter((p) => p.paging && !p.paging.stopped));

	// Bring the team asked for into view.
	$effect(() => {
		if (!ui.team || !oncall) return;
		list
			.querySelector(`[data-team="${CSS.escape(ui.team)}"]`)
			?.scrollIntoView({ block: 'nearest' });
	});

	function startCover(team: TeamNow): void {
		const now = Date.now();
		draft = {
			team: team.id,
			person: '',
			start: localTime(new Date(now)),
			end: localTime(new Date(Math.min(Date.parse(team.now.until), now + 4 * HOUR_MS))),
			note: ''
		};
		failure = null;
	}

	async function save(e: SubmitEvent): Promise<void> {
		e.preventDefault();
		if (!draft) return;
		rememberName(ui.person.trim());
		try {
			await saveCover({
				team: draft.team,
				person: draft.person,
				start: new Date(draft.start).toISOString(),
				end: new Date(draft.end).toISOString(),
				note: draft.note,
				by: ui.person
			});
			draft = null;
			failure = null;
			onchange();
		} catch (err) {
			failure = err instanceof Error ? err.message : String(err);
		}
	}

	async function remove(id: string): Promise<void> {
		try {
			await deleteCover(id);
			failure = null;
			onchange();
		} catch (err) {
			failure = err instanceof Error ? err.message : String(err);
		}
	}
</script>

{#snippet phone(person: Person)}
	{#if person.phone}<a class="mono" href="tel:{person.phone.replaceAll(' ', '')}">{person.phone}</a
		>{/if}
{/snippet}

<section class="oncall" aria-label="On call" bind:this={list}>
	{#if problem}
		<p class="muted">On call unavailable: {problem}</p>
	{:else if !oncall}
		<p class="muted">Loading who is on call…</p>
	{:else}
		{#if ui.at}<p class="muted">As it was at {clock(ui.at)}.</p>{/if}
		{#if failure}<p class="muted" role="alert">{failure}</p>{/if}
		{#if escalating.length}
			<h3>Paging now ({escalating.length})</h3>
			<ul>
				{#each escalating as p (p.id)}
					{@const last = p.paging?.notified.at(-1)}
					<li class="paged">
						<button class="link" onclick={() => showProblem(p)}>{p.title}</button>
						<span class="muted">
							{#if last}· paged {personOf(oncall, last.person).name}{/if}
							{#if p.paging?.next}
								· {personOf(oncall, p.paging.next.person).name} at {clock(p.paging.next.at)}
							{/if}
						</span>
					</li>
				{/each}
			</ul>
		{/if}
		<h3>Teams ({oncall.teams.length})</h3>
		<ul>
			{#each oncall.teams as team (team.id)}
				{@const primary = personOf(oncall, team.now.primary)}
				{@const covers = oncall.covers.filter((c) => c.team === team.id)}
				<li class="team" class:shown={ui.team === team.id} data-team={team.id}>
					<p><b>{team.name}</b></p>
					<p class="muted">{team.owns.join('; ')}</p>
					<dl>
						<dt>Primary</dt>
						<dd>
							{primary.name}{#if team.now.cover}<span class="muted">{' (covering)'}</span>{/if}
							{@render phone(primary)}
						</dd>
						{#if team.now.secondary}
							{@const secondary = personOf(oncall, team.now.secondary)}
							<dt>Secondary</dt>
							<dd>{secondary.name} {@render phone(secondary)}</dd>
						{/if}
						{#if team.manager}
							{@const manager = personOf(oncall, team.manager)}
							<dt>Manager</dt>
							<dd>{manager.name} {@render phone(manager)}</dd>
						{/if}
						<dt>Until</dt>
						<dd>{clock(team.now.until)}, then {personOf(oncall, team.next.primary).name}</dd>
					</dl>
					{#each covers as c (c.id)}
						<p class="cover">
							{personOf(oncall, c.person).name} covers {clock(c.start)} – {clock(c.end)}
							<span class="muted">· {c.by}{c.note ? `: ${c.note}` : ''}</span>
							{#if ui.at === null}
								<button class="link" onclick={() => remove(c.id)}>Remove</button>
							{/if}
						</p>
					{/each}
					{#if draft?.team === team.id}
						<form class="cover-form" onsubmit={save} aria-label="Cover {team.name}">
							<label>
								Who
								<select bind:value={draft.person} required>
									<option value="" disabled>Choose someone</option>
									{#each oncall.people as person (person.id)}
										<option value={person.id}>{person.name}</option>
									{/each}
								</select>
							</label>
							<label>From <input type="datetime-local" bind:value={draft.start} required /></label>
							<label>Until <input type="datetime-local" bind:value={draft.end} required /></label>
							<label>Note <input bind:value={draft.note} maxlength="1000" /></label>
							<label>
								Your name
								<input bind:value={ui.person} required maxlength="64" autocomplete="name" />
							</label>
							<p class="actions">
								<button type="submit">Save</button>
								<button type="button" onclick={() => (draft = null)}>Cancel</button>
							</p>
						</form>
					{:else if ui.at === null}
						<p class="actions"><button onclick={() => startCover(team)}>Cover…</button></p>
					{/if}
				</li>
			{/each}
		</ul>
		{#if oncall.carriers.length}
			<h3>Carriers ({oncall.carriers.length})</h3>
			<ul>
				{#each oncall.carriers as c (c.provider)}
					<li class="carrier">
						{c.provider}
						<a class="mono" href="tel:{c.phone.replaceAll(' ', '')}">{c.phone}</a>
						{#if c.portal}· <a href={c.portal} target="_blank" rel="noreferrer">portal</a>{/if}
					</li>
				{/each}
			</ul>
		{/if}
	{/if}
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
	ul {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	p {
		margin: 2px 0;
	}
	.team {
		margin: 0 0 8px;
		padding: 6px 8px;
		border: 1px solid var(--border);
		border-left: 3px solid var(--border);
		border-radius: 4px;
	}
	.team.shown {
		border-left-color: var(--selected);
	}
	.paged,
	.carrier {
		margin: 4px;
	}
	dl {
		display: grid;
		grid-template-columns: max-content 1fr;
		gap: 2px 8px;
		margin: 4px 0;
	}
	dt {
		color: var(--muted);
	}
	dd {
		margin: 0;
	}
	.muted {
		color: var(--muted);
		font-size: 12px;
	}
	section > .muted {
		margin: 2px 4px;
	}
	a {
		color: var(--accent);
	}
	.mono {
		margin-left: 4px;
		font-family: ui-monospace, monospace;
		font-size: 11px;
	}
	.link {
		border: none;
		background: none;
		padding: 0;
		color: var(--accent);
		cursor: pointer;
		text-align: left;
	}
	.cover {
		font-size: 12px;
	}
	.cover-form {
		display: grid;
		gap: 4px;
		margin: 6px 0 2px;
	}
	.cover-form label {
		display: grid;
		grid-template-columns: 70px 1fr;
		align-items: center;
		gap: 6px;
		font-size: 12px;
		color: var(--muted);
	}
	.cover-form input,
	.cover-form select {
		min-width: 0;
		font: inherit;
		color: var(--text);
		background: var(--bg);
		border: 1px solid var(--border);
		border-radius: 4px;
		padding: 2px 4px;
	}
	.actions {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		margin: 6px 0 0;
	}
	.actions button {
		padding: 2px 8px;
		font-size: 12px;
	}
</style>
