<!--
@component
An incident: problems someone treats as one, with where it stands (when it
began, who opened it, how soon someone took it on and paged a team, when it
cleared), its problems, the notes people write, and its timeline, worked out
on the server from what Sunstone records about its devices and links. Once
its problems clear, whoever writes the postmortem closes it with a summary.
Like the shift handover it fills the window, prints, is written as a
message to post, and a link opens it again (`?incident=12`). Clicking a line
of the timeline leaves it and replays that moment.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import {
		closeIncident,
		fetchIncident,
		fetchIncidents,
		noteIncident,
		type Entry,
		type IncidentList,
		type IncidentReport,
		type Member
	} from './api/incidents.ts';
	import { clock } from './history.ts';
	import { first, incidentLabel, into, lasted, postmortemText, STATUS } from './incident.ts';
	import { rememberName, select, showProblem, ui, type Selection } from './state.svelte.ts';

	const {
		shown,
		copied,
		oncopy
	}: {
		/** The incident's number, or 0 for none chosen yet. */
		shown: number;
		/** What Copy link last said, if it said anything lately. */
		copied: string | null;
		oncopy: () => void;
	} = $props();

	// Timelines grow while an incident lasts, and people add notes; check now and then.
	const POLL_MS = 30_000;
	/** How far back history goes, so what can be replayed. */
	const HISTORY_MS = 24 * 3_600_000;

	let found = $state.raw<{ shown: number; report: IncidentReport } | null>(null);
	let list = $state.raw<IncidentList | null>(null);
	let problem = $state<string | null>(null);
	let note = $state('');
	let summary = $state('');
	let busy = $state(false);
	let actionProblem = $state<string | null>(null);
	let showMessage = $state(false);
	let messageCopied = $state<string | null>(null);
	/** Incremented to fetch the incident again, after a note or the postmortem. */
	let reload = $state(0);
	const incident = $derived(found?.shown === shown ? found.report : null);
	const link = $derived(`${location.origin}${location.pathname}?incident=${shown}`);
	const now = $derived(incident?.cleared_at ? Date.parse(incident.cleared_at) : Date.now());

	// Every incident, now and then and after a change, to choose from; with
	// none chosen, the first.
	$effect(() => {
		void reload;
		let stopped = false;
		const load = () =>
			fetchIncidents().then(
				(l) => {
					if (stopped) return;
					list = l;
					const start = first(l.incidents);
					if (ui.incident === 0 && start !== null) ui.incident = start;
				},
				(e: unknown) => console.warn('Incidents unavailable', e)
			);
		void load();
		const timer = setInterval(load, POLL_MS);
		return () => {
			stopped = true;
			clearInterval(timer);
		};
	});

	// The incident chosen, again now and then while open.
	$effect(() => {
		const view = shown;
		void reload;
		if (view === 0) return;
		let stopped = false;
		const load = async () => {
			try {
				const report = await fetchIncident(view);
				if (stopped) return;
				found = { shown: view, report };
				problem = null;
			} catch (e) {
				if (!stopped) problem = e instanceof Error ? e.message : String(e);
			}
		};
		void load();
		const timer = setInterval(load, POLL_MS);
		return () => {
			stopped = true;
			clearInterval(timer);
		};
	});

	onMount(() => document.querySelector<HTMLElement>('.incident h1')?.focus());

	function close(): void {
		ui.incident = null;
	}

	/** A moment to replay, if history still has it. */
	function replayable(at: string | null | undefined): string | null {
		return at && Date.parse(at) > Date.now() - HISTORY_MS ? at : null;
	}

	/** Leave the incident and show something, replaying a moment if there is one. */
	function go(target: Selection | null, at: string | null): void {
		close();
		ui.live = true;
		ui.at = at;
		if (target) select(target, true);
	}

	function goMember(m: Member): void {
		if (!m.cleared_at) {
			close();
			ui.live = true;
			ui.at = null;
			ui.sideTab = 'problems';
			ui.problemsOpen = true;
			showProblem({ id: m.problem, target: m.target });
			return;
		}
		go(m.target, replayable(m.began ?? m.joined_at));
	}

	function goEntry(e: Entry): void {
		if (e.target) go(e.target, replayable(e.at));
	}

	async function act(work: () => Promise<unknown>, done: () => void): Promise<void> {
		rememberName(ui.person.trim());
		busy = true;
		actionProblem = null;
		try {
			await work();
			done();
			reload++;
		} catch (err) {
			actionProblem = err instanceof Error ? err.message : String(err);
		} finally {
			busy = false;
		}
	}

	function addNote(e: SubmitEvent): void {
		e.preventDefault();
		void act(
			() => noteIncident(shown, note, ui.person),
			() => (note = '')
		);
	}

	function closeIt(e: SubmitEvent): void {
		e.preventDefault();
		void act(
			() => closeIncident(shown, summary, ui.person),
			() => (summary = '')
		);
	}

	async function copyMessage(): Promise<void> {
		if (!incident) return;
		try {
			await navigator.clipboard.writeText(postmortemText(incident, link));
			messageCopied = 'Postmortem copied';
		} catch {
			// Clipboards need a secure page and permission; the text can be selected.
			messageCopied = 'Select it below to copy it';
		}
		setTimeout(() => (messageCopied = null), 2500);
	}

	function onKeydown(e: KeyboardEvent): void {
		const target = e.target;
		const typing =
			target instanceof HTMLElement && ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName);
		if (typing || e.ctrlKey || e.metaKey || e.altKey) return;
		if (e.key === 'Escape' || e.key.toLowerCase() === 'i') {
			e.preventDefault();
			close();
		}
	}

	const at = (time: string) => {
		const after = incident ? into(incident, time) : null;
		return after ? `${clock(time)} · ${after}` : clock(time);
	};
</script>

<svelte:window onkeydown={onKeydown} />

<div class="incident" aria-label="Incident">
	<header class="bar">
		<h1 tabindex="-1">{incident ? `Incident ${incident.number}` : 'Incidents'}</h1>
		{#if incident}
			<span class="title">{incident.title}</span>
			<span class="status {incident.status}">{STATUS[incident.status]}</span>
		{/if}
		<select
			class="controls"
			aria-label="Which incident"
			onchange={(e) => (ui.incident = Number(e.currentTarget.value))}
		>
			{#if shown === 0}<option value="0" selected>Choose one</option>{/if}
			{#each list?.incidents ?? [] as i (i.number)}
				<option value={i.number} selected={i.number === shown}>{incidentLabel(i)}</option>
			{/each}
		</select>
		<span class="grow"></span>
		{#if incident}
			<button
				class="controls"
				aria-pressed={showMessage}
				title="The incident written to post in chat or send by email"
				onclick={() => (showMessage = !showMessage)}>Postmortem</button
			>
			<button class="controls" onclick={() => window.print()}>Print</button>
			<button class="controls" onclick={oncopy}>{copied ?? 'Copy link'}</button>
		{/if}
		<button class="controls" title="Close (Esc)" onclick={close}>Close</button>
	</header>

	{#if problem}
		<p class="muted pad">Incident unavailable: {problem}</p>
	{:else if shown === 0}
		<p class="muted pad">
			{list && list.incidents.length === 0
				? 'No incidents yet. To open one, choose a problem in the problems list and use Open incident in its details.'
				: 'Finding the incidents…'}
		</p>
	{:else if !incident}
		<p class="muted pad">Working out the incident…</p>
	{:else}
		{@const long = lasted(incident, now)}
		<div class="sheet">
			{#if showMessage}
				<section class="message controls" aria-label="Postmortem text">
					<h2>
						Postmortem <small class="quiet">to post in chat or send by email; nothing is sent</small
						>
					</h2>
					<pre>{postmortemText(incident, link)}</pre>
					<p><button onclick={copyMessage}>{messageCopied ?? 'Copy postmortem'}</button></p>
				</section>
			{/if}
			<div class="column">
				<section aria-label="Where it stands">
					<h2>Where it stands</h2>
					<dl class="facts">
						<dt>Began</dt>
						<dd>{incident.began ? clock(incident.began) : 'Before history begins'}</dd>
						<dt>Opened</dt>
						<dd>{incident.opened_by} · {at(incident.opened_at)}</dd>
						<dt>Taken on</dt>
						<dd>
							{incident.acknowledged
								? `${incident.acknowledged.by} · ${at(incident.acknowledged.at)}`
								: 'No one has acknowledged it'}
						</dd>
						<dt>Paged</dt>
						<dd>
							{incident.paged
								? `${incident.paged.text} · ${at(incident.paged.at)}`
								: 'No team has been paged'}
						</dd>
						<dt>{incident.cleared_at ? 'Cleared' : incident.closed ? 'Not cleared' : 'Lasting'}</dt>
						<dd>
							{#if incident.cleared_at}
								{clock(incident.cleared_at)}{long ? ` · lasted ${long}` : ''}
							{:else if incident.closed}
								Closed while its problems were still there
							{:else}
								{long ?? 'since before history begins'}
							{/if}
						</dd>
					</dl>
				</section>

				<section aria-label="Problems">
					<h2>Problems ({incident.problems.length})</h2>
					<ul class="rows">
						{#each incident.problems as m (m.problem)}
							<li>
								<button class="row" class:open={!m.cleared_at} onclick={() => goMember(m)}>
									<span class="what">{m.title}</span>
									<span class="when"
										>{m.cleared_at ? `cleared ${clock(m.cleared_at)}` : 'still there'}</span
									>
									<span class="long">
										{[
											m.lost ? `${m.lost} unreachable` : '',
											m.exposed ? `${m.exposed} without redundancy` : '',
											`added by ${m.joined_by}`
										]
											.filter(Boolean)
											.join(' · ')}
									</span>
								</button>
							</li>
						{/each}
					</ul>
				</section>

				<section aria-label="Notes">
					<h2>Notes ({incident.notes.length})</h2>
					{#if incident.notes.length === 0}<p class="muted">None yet.</p>{/if}
					<ul class="rows">
						{#each incident.notes as n (n.id)}
							<li class="note">
								<span class="what">{n.text}</span>
								<span class="when">{n.by} · {clock(n.at)}</span>
							</li>
						{/each}
					</ul>
					{#if !incident.closed}
						<form class="write controls" onsubmit={addNote}>
							<input
								bind:value={note}
								required
								maxlength="1000"
								placeholder="What is known, or being done"
								aria-label="Note on the incident"
							/>
							<input
								class="name"
								bind:value={ui.person}
								required
								maxlength="64"
								placeholder="Your name"
								aria-label="Your name"
								autocomplete="name"
							/>
							<button type="submit" disabled={busy}>Add note</button>
						</form>
					{/if}
				</section>

				<section aria-label="Postmortem" class:due={incident.status === 'cleared'}>
					<h2>Postmortem</h2>
					{#if incident.closed}
						<p class="summary">{incident.closed.summary}</p>
						<p class="muted">Closed by {incident.closed.by} · {clock(incident.closed.at)}</p>
					{:else}
						<p class="muted">
							{incident.status === 'cleared'
								? 'Its problems have cleared. Say what happened, and what is to be done about it, to close it.'
								: 'Once its problems clear, say what happened, and what is to be done about it, to close it.'}
						</p>
						<form class="write controls" onsubmit={closeIt}>
							<textarea
								bind:value={summary}
								required
								maxlength="4000"
								rows="4"
								placeholder="What happened, and what is to be done about it"
								aria-label="Postmortem summary"></textarea>
							<button type="submit" disabled={busy}>Close incident</button>
						</form>
					{/if}
					{#if actionProblem}<p class="error" role="alert">{actionProblem}</p>{/if}
				</section>
			</div>
			<div class="column">
				<section aria-label="Timeline">
					<h2>Timeline ({incident.timeline.length})</h2>
					<ul class="rows">
						{#each incident.timeline as e (e.at + e.kind + e.text)}
							<li>
								<button class="row entry {e.kind}" disabled={!e.target} onclick={() => goEntry(e)}>
									<span class="clock">{clock(e.at)}</span>
									<span class="what"
										>{e.text}{e.kind === 'note' && e.by ? ` (${e.by})` : ''}{e.planned
											? ' · planned'
											: ''}</span
									>
								</button>
							</li>
						{/each}
					</ul>
				</section>
			</div>
		</div>
	{/if}
</div>

<style>
	/* Over everything else, which stays as it is underneath. */
	.incident {
		position: fixed;
		inset: 0;
		z-index: 50;
		display: flex;
		flex-direction: column;
		background: var(--bg);
	}
	.bar {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 8px 12px;
		padding: 8px 14px;
		background: var(--panel);
		border-bottom: 1px solid var(--border);
	}
	h1 {
		margin: 0;
		font-size: 17px;
		font-weight: 600;
		outline: none;
	}
	.title {
		font-weight: 600;
	}
	.status {
		padding: 1px 8px;
		border-radius: 10px;
		font-size: 12px;
		border: 1px solid var(--border);
	}
	.status.open {
		color: var(--down);
		border-color: var(--down);
	}
	.status.cleared {
		color: var(--accent);
		border-color: var(--accent);
	}
	.grow {
		flex: 1;
	}
	.pad {
		padding: 8px 24px;
	}
	.sheet {
		flex: 1;
		overflow-y: auto;
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(min(100%, 480px), 1fr));
		align-items: start;
		gap: 0 32px;
		padding: 8px 24px 40px;
	}
	.column {
		min-width: 0;
	}
	section {
		margin-bottom: 18px;
	}
	section.due {
		padding: 2px 12px 8px;
		border-left: 3px solid var(--accent);
		background: var(--panel);
		border-radius: 4px;
	}
	h2 {
		margin: 12px 0 6px;
		font-size: 15px;
		font-weight: 600;
	}
	h2 small {
		margin-left: 8px;
		font-size: 12px;
		font-weight: normal;
		color: var(--muted);
	}
	.message {
		grid-column: 1 / -1;
	}
	pre {
		margin: 0 0 6px;
		padding: 8px 10px;
		max-height: 40vh;
		overflow: auto;
		white-space: pre-wrap;
		font-size: 12px;
		background: var(--panel);
		border: 1px solid var(--border);
		border-radius: 4px;
	}
	.facts {
		display: grid;
		grid-template-columns: max-content 1fr;
		gap: 3px 16px;
		margin: 0;
		font-size: 13px;
	}
	.facts dt {
		color: var(--muted);
	}
	.facts dd {
		margin: 0;
	}
	.summary {
		white-space: pre-wrap;
		font-size: 13px;
	}
	.note {
		display: grid;
		grid-template-columns: 1fr auto;
		gap: 0 12px;
		align-items: baseline;
		padding: 4px 8px;
		font-size: 13px;
		border-left: 3px solid var(--accent);
		margin-bottom: 3px;
	}
	.write {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		margin-top: 6px;
	}
	.write input,
	.write textarea {
		flex: 1 1 260px;
		font: inherit;
		font-size: 13px;
		color: var(--text);
		background: var(--bg);
		border: 1px solid var(--border);
		border-radius: 4px;
		padding: 4px 6px;
	}
	.write textarea {
		flex-basis: 100%;
	}
	.write input.name {
		flex: 0 1 140px;
	}
	.error {
		color: var(--down);
		font-size: 12px;
	}
	p {
		margin: 4px 0;
	}
	.muted {
		color: var(--muted);
		font-size: 12px;
	}
	.rows {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	.row {
		display: grid;
		grid-template-columns: 1fr auto;
		gap: 0 12px;
		width: 100%;
		margin: 0 0 3px;
		padding: 4px 8px;
		text-align: left;
		border-radius: 4px;
		font-size: 13px;
	}
	.row:disabled {
		cursor: default;
		color: var(--text);
	}
	.row.open {
		border-left: 3px solid var(--down);
	}
	.what {
		grid-column: 1;
	}
	.when {
		grid-column: 2;
		color: var(--muted);
		font-size: 12px;
		white-space: nowrap;
	}
	.long {
		grid-column: 1 / -1;
		color: var(--muted);
		font-size: 12px;
	}
	/* The timeline: the time, then what happened; people's steps marked. */
	.entry {
		grid-template-columns: 4.5em 1fr;
		border-left: 3px solid transparent;
	}
	.entry .what {
		grid-column: 2;
	}
	.clock {
		color: var(--muted);
		font-size: 12px;
		font-variant-numeric: tabular-nums;
	}
	.entry.opened,
	.entry.joined,
	.entry.ack,
	.entry.page,
	.entry.notice,
	.entry.note,
	.entry.closed {
		border-left-color: var(--accent);
	}
	.entry.cleared {
		border-left-color: var(--live);
	}

	/* On paper: black on white, without the controls, one column. */
	@media print {
		:global(html),
		:global(body) {
			height: auto;
			background: #fff;
		}
		:global(.app > :not(.incident)) {
			display: none !important;
		}
		.incident {
			position: static;
		}
		.incident,
		.bar {
			height: auto;
			color: #000;
			background: #fff;
			border: none;
		}
		.controls {
			display: none;
		}
		.sheet {
			display: block;
			overflow: visible;
			padding: 0 14px;
		}
		section {
			break-inside: avoid;
		}
		section.due {
			background: none;
			border-left: 3px solid #000;
		}
		.row {
			color: #000;
			background: none;
			border: none;
			border-bottom: 1px solid #ccc;
			border-radius: 0;
		}
		.row:disabled {
			color: #000;
			opacity: 1;
		}
		.muted,
		.when,
		.long,
		.clock,
		.facts dt {
			color: #444;
		}
	}
</style>
