<!--
@component
The shift handover: what the incoming shift needs to know about the last
hours, worked out on the server for every viewer. What is wrong now and who
is on it, who is on call, the outages that began or ended and how long they
lasted, pages and acknowledgements, maintenance done, open, and coming,
and fixes and new discovery findings. It fills the window, prints on paper,
and a link opens it again (`?handover=12`). Clicking something leaves the
report and shows it: a problem with its impact, an outage at the moment it
began.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import { fetchHandover, type Handover, type Outage } from './api/handover.ts';
	import type { Change } from './api/changes.ts';
	import type { Finding } from './api/discovery.ts';
	import type { Window } from './api/operations.ts';
	import { changedTarget, changeLine, findingTarget, seenWhen } from './discovery.ts';
	import { duration, lasted, outageSections, SPANS, standing } from './handover.ts';
	import { clock } from './history.ts';
	import { phaseOf, span } from './maintenance.ts';
	import { personOf } from './oncall.ts';
	import { MARK } from './problem-kinds.ts';
	import {
		select,
		showDiscovery,
		showProblem,
		showTeam,
		ui,
		type Selection
	} from './state.svelte.ts';

	const {
		hours,
		copied,
		oncopy
	}: {
		hours: number;
		/** What Copy link last said, if it said anything lately. */
		copied: string | null;
		oncopy: () => void;
	} = $props();

	// Pages, acknowledgements, and maintenance change when someone acts; check now and then.
	const POLL_MS = 60_000;
	/** Single devices listed before Show all. */
	const FIRST_DEVICES = 10;

	let handover = $state.raw<Handover | null>(null);
	let problem = $state<string | null>(null);
	let allDevices = $state(false);
	const now = $derived(handover ? Date.parse(handover.until) : Date.now());
	const sections = $derived(outageSections(handover?.outages ?? []));
	const stillDown = $derived(handover?.outages.filter((o) => !o.end).length ?? 0);
	const unhandled = $derived(
		handover?.problems.filter((p) => !p.ack && p.planned.length === 0).length ?? 0
	);
	const teams = $derived(new Map(handover?.oncall?.teams.map((t) => [t.id, t.name]) ?? []));
	const person = (id: string) => (handover?.oncall ? personOf(handover.oncall, id).name : id);
	const phases = $derived.by(() => {
		const windows = handover?.windows ?? [];
		return [
			{ label: 'Open now', items: windows.filter((w) => phaseOf(w, now) === 'open') },
			{ label: 'Coming', items: windows.filter((w) => phaseOf(w, now) === 'upcoming') },
			{ label: 'Done', items: windows.filter((w) => phaseOf(w, now) === 'ended') }
		].filter((p) => p.items.length);
	});

	// Again for each span chosen, and now and then while open.
	$effect(() => {
		const span = hours;
		let stopped = false;
		const load = async () => {
			try {
				const found = await fetchHandover(span);
				if (stopped) return;
				handover = found;
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

	onMount(() => document.querySelector<HTMLElement>('.handover h1')?.focus());

	function close(): void {
		ui.handover = null;
	}

	/** Leave the report and show something: live, now or at a moment. */
	function go(target: Selection | null, at: string | null = null): void {
		close();
		if (at) {
			ui.live = true;
			ui.at = at;
		}
		if (target) select(target, true);
	}

	function goProblem(p: { id: string; target: Selection }): void {
		close();
		ui.live = true;
		ui.at = null;
		ui.sideTab = 'problems';
		ui.problemsOpen = true;
		if (ui.problem !== p.id) showProblem(p);
	}

	function goOutage(o: Outage): void {
		// Only moments history still has can be replayed.
		const back = handover ? Date.parse(handover.until) - 24 * 3_600_000 : 0;
		go(o.target, o.start && Date.parse(o.start) > back ? o.start : null);
	}

	function goWindow(w: Window): void {
		go(w.targets[0] ?? null);
		ui.sideTab = 'maintenance';
		ui.problemsOpen = true;
	}

	function goChange(c: Change): void {
		go(changedTarget(c.fix.after, c.fix.before));
	}

	function goFinding(f: Finding): void {
		close();
		ui.sideTab = 'discovery';
		ui.problemsOpen = true;
		showDiscovery(findingTarget(f));
	}

	function goTeam(team: string): void {
		close();
		showTeam(team);
	}

	function onKeydown(e: KeyboardEvent): void {
		const target = e.target;
		const typing =
			target instanceof HTMLElement && ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName);
		if (typing || e.ctrlKey || e.metaKey || e.altKey) return;
		if (e.key === 'Escape' || e.key.toLowerCase() === 'h') {
			e.preventDefault();
			close();
		}
	}

	const when = (o: Outage) =>
		`${o.start ? clock(o.start) : 'before history'} – ${o.end ? clock(o.end) : 'still down'}`;
</script>

<svelte:window onkeydown={onKeydown} />

{#snippet outages(list: Outage[])}
	<ul class="rows">
		{#each list as o (o.title + (o.start ?? ''))}
			<li>
				<button class="row" class:open={!o.end} onclick={() => goOutage(o)}>
					<span class="what">{o.title}</span>
					<span class="when">{when(o)}</span>
					<span class="long">{lasted(o, now)}{o.planned ? ' · planned' : ''}</span>
				</button>
			</li>
		{/each}
	</ul>
{/snippet}

<div class="handover" aria-label="Shift handover">
	<header class="bar">
		<h1 tabindex="-1">Shift handover</h1>
		{#if handover}
			<span class="span">
				{clock(handover.since)} – {clock(handover.until)} · the last {duration(
					Date.parse(handover.until) - Date.parse(handover.since)
				)}
			</span>
		{/if}
		<div class="segmented controls" role="group" aria-label="Covering">
			{#each SPANS as h (h)}
				<button aria-pressed={hours === h} onclick={() => (ui.handover = h)}>{h} h</button>
			{/each}
		</div>
		<span class="grow"></span>
		<button class="controls" onclick={() => window.print()}>Print</button>
		<button class="controls" onclick={oncopy}>{copied ?? 'Copy link'}</button>
		<button class="controls" title="Close (Esc)" onclick={close}>Close</button>
	</header>

	{#if problem}
		<p class="muted">Handover unavailable: {problem}</p>
	{:else if !handover}
		<p class="muted">Working out the handover…</p>
	{:else}
		<div class="sheet">
			<div class="column">
				<section aria-label="Open now">
					<h2>
						Open now ({handover.problems.length})
						{#if handover.problems.length}<small>{unhandled} no one is on</small>{/if}
					</h2>
					{#if handover.problems.length === 0}
						<p class="muted">Nothing is wrong in the latest snapshot.</p>
					{/if}
					<ul class="rows">
						{#each handover.problems as p (p.id)}
							{@const handled = p.ack !== null || p.planned.length > 0}
							<li>
								<button class="row" class:open={!handled} onclick={() => goProblem(p)}>
									<span class="what">
										<i style:--c={MARK[p.kind].color} aria-hidden="true">{MARK[p.kind].glyph}</i>
										{p.title}
										{#if p.detail}<span class="muted"> · {p.detail}</span>{/if}
									</span>
									<span class="when">{p.team ? (teams.get(p.team) ?? p.team) : ''}</span>
									<span class="long">{standing(p)}</span>
								</button>
							</li>
						{/each}
					</ul>
				</section>

				{#if handover.oncall}
					<section aria-label="On call now">
						<h2>On call now</h2>
						<table>
							<thead><tr><th>Team</th><th>Primary</th><th>Secondary</th><th>Until</th></tr></thead>
							<tbody>
								{#each handover.oncall.teams as t (t.id)}
									{@const primary = personOf(handover.oncall, t.now.primary)}
									<tr>
										<td><button class="link" onclick={() => goTeam(t.id)}>{t.name}</button></td>
										<td>{primary.name} <span class="muted">{primary.phone}</span></td>
										<td>{t.now.secondary ? person(t.now.secondary) : '—'}</td>
										<td>{clock(t.now.until)}</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</section>
				{/if}

				<section aria-label="Pages and acknowledgements">
					<h2>Pages and acknowledgements ({handover.pages.length + handover.acks.length})</h2>
					{#if handover.pages.length + handover.acks.length === 0}
						<p class="muted">No one was paged, and nothing was acknowledged.</p>
					{/if}
					<ul class="rows">
						{#each handover.pages as pg (pg.id)}
							{@const open = handover.problems.find((p) => p.id === pg.problem)}
							<li>
								<button class="row" disabled={!open} onclick={() => open && goProblem(open)}>
									<span class="what"
										>{pg.by} paged {teams.get(pg.team) ?? pg.team}: {pg.title ?? pg.problem}{pg.note
											? ` · ${pg.note}`
											: ''}</span
									>
									<span class="when">{clock(pg.at)}</span>
									<span class="long"
										>{pg.cleared_at ? `cleared ${clock(pg.cleared_at)}` : 'open'}</span
									>
								</button>
							</li>
						{/each}
						{#each handover.acks as a (a.problem + a.at)}
							{@const open = handover.problems.find((p) => p.id === a.problem)}
							<li>
								<button class="row" disabled={!open} onclick={() => open && goProblem(open)}>
									<span class="what"
										>{a.by} on {a.title ?? a.problem}{a.note ? ` · ${a.note}` : ''}</span
									>
									<span class="when">{clock(a.at)}</span>
									<span class="long"
										>{a.cleared_at ? `cleared ${clock(a.cleared_at)}` : 'open'}</span
									>
								</button>
							</li>
						{/each}
					</ul>
				</section>

				<section aria-label="Maintenance">
					<h2>Maintenance ({handover.windows.length})</h2>
					{#if phases.length === 0}
						<p class="muted">None done, open, or coming in as long again.</p>
					{/if}
					{#each phases as phase (phase.label)}
						<h3>{phase.label} ({phase.items.length})</h3>
						<ul class="rows">
							{#each phase.items as w (w.id)}
								<li>
									<button class="row" onclick={() => goWindow(w)}>
										<span class="what">{w.title}{w.note ? ` · ${w.note}` : ''}</span>
										<span class="when">{span(w)}</span>
										<span class="long">{w.by}</span>
									</button>
								</li>
							{/each}
						</ul>
					{/each}
				</section>

				<section aria-label="Documentation">
					<h2>Documentation ({handover.changes.length + handover.findings.length})</h2>
					{#if handover.changes.length + handover.findings.length === 0}
						<p class="muted">No fixes recorded, and nothing new seen by discovery.</p>
					{/if}
					{#if handover.changes.length}
						<h3>Fixed or marked expected ({handover.changes.length})</h3>
						<ul class="rows">
							{#each handover.changes as c (c.id)}
								<li>
									<button class="row" onclick={() => goChange(c)}>
										<span class="what">{changeLine(c)}{c.note ? ` · ${c.note}` : ''}</span>
										<span class="when">{clock(c.at)}</span>
										<span class="long">{c.by}</span>
									</button>
								</li>
							{/each}
						</ul>
					{/if}
					{#if handover.findings.length}
						<h3>First seen by discovery ({handover.findings.length})</h3>
						<ul class="rows">
							{#each handover.findings as f (f.id)}
								<li>
									<button class="row" onclick={() => goFinding(f)}>
										<span class="what">{f.title} <span class="muted">· {f.detail}</span></span>
										<span class="when">{seenWhen(f, null)}</span>
										<span class="long"></span>
									</button>
								</li>
							{/each}
						</ul>
					{/if}
				</section>
			</div>
			<div class="column">
				<section aria-label="Outages">
					<h2>Outages ({handover.outages.length})</h2>
					{#if handover.outages.length === 0}
						<p class="muted">Nothing went down or came back.</p>
					{:else}
						<p class="muted">
							Began or ended in these hours: {sections.sites.length} at whole sites, {sections.links
								.length} links on their own, and {sections.devices.length} single devices; {stillDown}
							still down.
						</p>
					{/if}
					{#if sections.sites.length}
						<h3>Sites ({sections.sites.length})</h3>
						{@render outages(sections.sites)}
					{/if}
					{#if sections.links.length}
						<h3>Links ({sections.links.length})</h3>
						{@render outages(sections.links)}
					{/if}
					{#if sections.devices.length}
						<h3>Single devices ({sections.devices.length})</h3>
						{@render outages(
							allDevices ? sections.devices : sections.devices.slice(0, FIRST_DEVICES)
						)}
						{#if !allDevices && sections.devices.length > FIRST_DEVICES}
							<p class="muted">
								and {sections.devices.length - FIRST_DEVICES} more
								<button class="link controls" onclick={() => (allDevices = true)}>Show all</button>
							</p>
						{/if}
					{/if}
				</section>
			</div>
		</div>
	{/if}
</div>

<style>
	/* Over everything else, which stays as it is underneath. */
	.handover {
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
	.span {
		color: var(--muted);
	}
	.segmented button[aria-pressed='true'] {
		border-color: var(--live);
	}
	.grow {
		flex: 1;
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
	h2 {
		margin: 12px 0 6px;
		font-size: 15px;
		font-weight: 600;
	}
	h2 small {
		margin-left: 8px;
		font-size: 12px;
		font-weight: normal;
		color: var(--accent);
	}
	h3 {
		margin: 10px 0 4px;
		font-size: 12px;
		font-weight: normal;
		color: var(--muted);
		text-transform: uppercase;
		letter-spacing: 0.04em;
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
		border-left: 3px solid var(--accent);
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
	.long:empty {
		display: none;
	}
	i {
		display: inline-block;
		width: 1.2em;
		color: var(--c);
		font-style: normal;
		font-weight: 700;
		text-align: center;
	}
	table {
		width: 100%;
		border-collapse: collapse;
		font-size: 13px;
	}
	th {
		text-align: left;
		font-weight: normal;
		color: var(--muted);
		font-size: 12px;
	}
	td,
	th {
		padding: 3px 8px 3px 0;
		border-bottom: 1px solid var(--border);
	}
	.link {
		border: none;
		background: none;
		padding: 0;
		color: var(--accent);
		cursor: pointer;
		font: inherit;
	}

	/* On paper: black on white, without the controls, one column. */
	@media print {
		:global(html),
		:global(body) {
			height: auto;
			background: #fff;
		}
		:global(.app > :not(.handover)) {
			display: none !important;
		}
		.handover {
			position: static;
		}
		.handover,
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
		.row {
			color: #000;
			background: none;
			border: none;
			border-bottom: 1px solid #ccc;
			border-radius: 0;
		}
		.row.open {
			border-left: 3px solid #000;
		}
		.row:disabled {
			color: #000;
			opacity: 1;
		}
		.muted,
		.when,
		.long,
		h3,
		th,
		.span {
			color: #444;
		}
		.link {
			color: #000;
		}
	}
</style>
