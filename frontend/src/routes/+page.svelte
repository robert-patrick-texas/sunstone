<!--
@component
The app: header with view switch and search, the current view, the legend,
the details panel for whatever is selected, a side panel of maintenance
windows and who is on call, and with live state, a time slider over the
last day and problems and events in the side panel too. The address bar always holds a link to
what is on screen, and opening such a link shows it again; going somewhere
new (another view, selection, path, or problem) adds a step that Back
returns from. Every command has a place in search and most have a key;
`?` lists them. In wall display mode, the wall's bar and captions take the
place of the controls.
-->
<script lang="ts">
	import '../app.css';
	import { onMount, untrack } from 'svelte';
	import { pushState, replaceState } from '$app/navigation';
	import { fetchProblems, fetchWhatIf, type Problem } from '#lib/api/analysis.ts';
	import { fetchDiscovery, type Comparison } from '#lib/api/discovery.ts';
	import { fetchOnCall, fetchOwnership, type OnCall, type Ownership } from '#lib/api/oncall.ts';
	import { fetchWindows, type Window } from '#lib/api/operations.ts';
	import { fetchEvents, fetchState, type EventLog } from '#lib/api/state.ts';
	import { fetchTopology } from '#lib/api/topology.ts';
	import { available, COMMANDS, commandFor, type CommandId } from '#lib/commands.ts';
	import DetailsPanel from '#lib/DetailsPanel.svelte';
	import DiscoveryPanel from '#lib/DiscoveryPanel.svelte';
	import { startPerf, timed, timedAsync } from '#lib/perf.ts';
	import PerfPanel from '#lib/PerfPanel.svelte';
	import EventsPanel from '#lib/EventsPanel.svelte';
	import GeoView from '#lib/geo/GeoView.svelte';
	import HierarchyView from '#lib/hierarchy/HierarchyView.svelte';
	import type { Impact } from '#lib/impact.ts';
	import TopologyView from '#lib/topo/TopologyView.svelte';
	import Legend from '#lib/Legend.svelte';
	import { phaseOf } from '#lib/maintenance.ts';
	import MaintenancePanel from '#lib/MaintenancePanel.svelte';
	import OnCallPanel from '#lib/OnCallPanel.svelte';
	import { indexState, type LiveIndex } from '#lib/live.ts';
	import { shortestPaths } from '#lib/paths.ts';
	import { stepEarlier, stepLater, type Span } from '#lib/history.ts';
	import { stepProblem } from '#lib/problem-kinds.ts';
	import ProblemsPanel from '#lib/ProblemsPanel.svelte';
	import { loadRecent, saveRecent, withRecent } from '#lib/recent.ts';
	import SearchBox from '#lib/SearchBox.svelte';
	import ShortcutsHelp from '#lib/ShortcutsHelp.svelte';
	import {
		addFailure,
		clearPath,
		expandedSites,
		fromLink,
		select,
		showNeighborhood,
		showProblem,
		startPath,
		topo,
		ui,
		type Selection,
		type View
	} from '#lib/state.svelte.ts';
	import Timeline from '#lib/Timeline.svelte';
	import { compareNatural, indexTopology, type TopologyIndex } from '#lib/topology.ts';
	import { fromQuery, movesOn, OPENING, readable, toQuery, type Shared } from '#lib/url.ts';
	import WallDisplay from '#lib/WallDisplay.svelte';

	// Small networks open fully expanded in the hierarchy; larger ones start as one box per site.
	const EXPAND_ALL_UP_TO = 400;
	const VIEWS: { id: View; label: string }[] = [
		{ id: 'geo', label: 'Geographic' },
		{ id: 'hierarchy', label: 'Hierarchy' },
		{ id: 'topology', label: 'Topology' }
	];

	const POLL_MS = 10_000;
	// Sources report history in 5-minute steps, so the event log changes no faster.
	const EVENTS_POLL_MS = 60_000;
	// Maintenance windows change when someone plans one, so check now and then.
	const WINDOWS_POLL_MS = 60_000;
	// Shifts change hands on the hour at most; covers when someone adds one.
	const ONCALL_POLL_MS = 60_000;
	// Discovery runs every 15 minutes.
	const DISCOVERY_POLL_MS = 5 * 60_000;
	// While the time slider is dragged, wait for it to settle before fetching.
	const REPLAY_WAIT_MS = 200;
	// How far back sources keep history, for stepping back before the events arrive.
	const DAY_MS = 24 * 60 * 60_000;

	let index = $state.raw<TopologyIndex | null>(null);
	let live = $state.raw<LiveIndex | null>(null);
	let liveProblem = $state<string | null>(null);
	let events = $state.raw<EventLog | null>(null);
	let eventsProblem = $state<string | null>(null);
	let windows = $state.raw<Window[]>([]);
	let windowsProblem = $state<string | null>(null);
	let oncall = $state.raw<OnCall | null>(null);
	let oncallProblem = $state<string | null>(null);
	let ownership = $state.raw<Ownership | null>(null);
	let comparison = $state.raw<Comparison | null>(null);
	let discoveryProblem = $state<string | null>(null);
	/** Bumped to fetch live state and events again at once, after planned work changes. */
	let refresh = $state(0);
	const coming = $derived(windows.filter((w) => phaseOf(w, Date.now()) !== 'ended').length);
	const path = $derived(index && ui.path ? shortestPaths(index, ui.path.from, ui.path.to) : null);
	// Problems come with each snapshot, found once on the server for every viewer.
	let problems = $state.raw<Problem[]>([]);
	let whatIf = $state.raw<Impact | null>(null);
	let whatIfProblem = $state<string | null>(null);
	const focused = $derived(problems.find((p) => p.id === ui.problem) ?? null);
	// Problems someone is on, or that planned work accounts for, are handled.
	const unhandled = $derived(problems.filter((p) => !p.ack && p.planned.length === 0).length);
	// A path, when shown, takes the place of an impact, and either of discovery.
	const impact = $derived.by(() => {
		if (!index || path || ui.pathFrom) return null;
		return ui.whatIf.length === 0 ? (focused?.impact ?? null) : whatIf;
	});
	const drift = $derived(ui.discovery && !path && !ui.pathFrom && !impact ? comparison : null);
	let problem = $state<string | null>(null);
	let showPerf = $state(false);
	let copied = $state<string | null>(null);
	let helpOpen = $state(false);
	let searchBox = $state<ReturnType<typeof SearchBox>>();
	/** What this browser looked at recently, newest first. */
	let recent = $state(loadRecent());
	const context = $derived({
		selection: ui.selection,
		live: ui.live,
		replaying: ui.at !== null,
		problems: problems.length
	});
	// Search offers every command that can run now, except going to search itself.
	const ready = $derived(COMMANDS.filter((c) => c.id !== 'search' && available(c, context)));

	onMount(async () => {
		if (new URLSearchParams(location.search).has('perf')) {
			startPerf();
			showPerf = true;
		}
		try {
			const topology = await fetchTopology();
			if (topology.devices.length <= EXPAND_ALL_UP_TO) {
				for (const site of topology.sites) expandedSites.add(site.code);
			}
			const built = indexTopology(topology);
			// Before the views open, so they open on what the link shows.
			openLink(fromQuery(new URLSearchParams(location.search), built));
			index = built;
		} catch (e) {
			problem = e instanceof Error ? e.message : String(e);
		}
	});

	/** Show what a link asks for; anything it leaves out stays as it is. */
	function openLink(found: Partial<Shared>): void {
		if (found.topo) Object.assign(topo, found.topo);
		if (found.expanded) {
			expandedSites.clear();
			for (const code of found.expanded) expandedSites.add(code);
		}
		if (found.view) ui.view = found.view;
		if (found.selection !== undefined) ui.selection = found.selection;
		if (found.path !== undefined) ui.path = found.path;
		if (found.whatIf) ui.whatIf = found.whatIf;
		if (found.live !== undefined) {
			ui.live = found.live;
			ui.at = found.at ?? null;
			ui.problem = found.problem ?? null;
		}
		if (found.camera) fromLink.camera = found.camera;
		if (found.discovery !== undefined) ui.discovery = found.discovery;
		if (found.wall !== undefined) {
			ui.wall.on = found.wall !== null;
			if (found.wall) ui.wall.dwell = found.wall.dwell;
		}
	}

	/** What is on screen, as a link carries it. */
	function onScreen(): Shared {
		return {
			view: ui.view,
			selection: ui.selection ? $state.snapshot(ui.selection) : null,
			live: ui.live,
			at: ui.at,
			path: ui.path ? { ...ui.path } : null,
			whatIf: $state.snapshot(ui.whatIf),
			problem: ui.problem,
			topo: { ...$state.snapshot(topo) },
			expanded: [...expandedSites].sort(compareNatural),
			camera: ui.camera,
			wall: ui.wall.on ? { dwell: ui.wall.dwell } : null,
			discovery: ui.discovery
		};
	}

	// What the address bar last showed; not reactive.
	let shown: Shared | null = null;

	// Keep the address bar a link to what is on screen. Going somewhere new
	// adds a step to the browser's history, so Back returns from it; anything
	// else updates the current step. The wall moves on by itself, so it never adds steps.
	$effect(() => {
		if (!index) return;
		const shared = onScreen();
		const step = shown !== null && !ui.wall.on && movesOn(shown, shared);
		shown = shared;
		// ?perf is for measuring, not for sharing, but keep it while measuring.
		const parts = [readable(toQuery(shared, index)), showPerf ? 'perf' : ''].filter(Boolean);
		const search = parts.length ? `?${parts.join('&')}` : '';
		if (search === location.search) return;
		if (step) pushState(`${location.pathname}${search}`, {});
		else replaceState(`${location.pathname}${search}`, {});
	});

	/** Back or Forward: show the step gone to, as a link would. */
	function onPopState(): void {
		if (!index) return;
		const found = fromQuery(new URLSearchParams(location.search), index);
		ui.pathFrom = null;
		openLink({ ...OPENING, ...found });
		// Go back to where the map was, or else to what was selected.
		if (found.camera) {
			fromLink.camera = found.camera;
			ui.cameraRequest++;
		} else if (found.selection) ui.focusRequest++;
		shown = onScreen();
	}

	// Remember what was looked at, for search to offer again.
	$effect(() => {
		const selection = ui.selection;
		if (!selection || ui.wall.on) return;
		untrack(() => {
			recent = withRecent(recent, $state.snapshot(selection));
			saveRecent(recent);
		});
	});

	function forgetRecent(): void {
		recent = [];
		saveRecent(recent);
	}

	// The wall shows live state as it is now, and nothing else.
	$effect(() => {
		if (!ui.wall.on) return;
		ui.live = true;
		ui.at = null;
		ui.whatIf = [];
		clearPath();
	});

	async function copyLink(): Promise<void> {
		try {
			await navigator.clipboard.writeText(location.href);
			copied = 'Link copied';
		} catch {
			// Clipboards need a secure page and permission; the address bar always works.
			copied = 'Copy it from the address bar';
		}
		setTimeout(() => (copied = null), 2500);
	}

	function enterWall(): void {
		ui.wall.on = true;
		document.documentElement.requestFullscreen().catch((e: unknown) => {
			// Refused (some browsers, kiosks); the wall still fills the window.
			console.warn('Full screen refused', e);
		});
	}

	// While live state is on, fetch it now and every POLL_MS; or, while
	// replaying an earlier moment, fetch that moment once.
	$effect(() => {
		if (!ui.live) {
			live = null;
			problems = [];
			liveProblem = null;
			ui.problem = null;
			ui.at = null;
			return;
		}
		const at = ui.at;
		void refresh;
		let stopped = false;
		const load = async () => {
			try {
				const state = await timedAsync('live fetch', () => fetchState(at ?? undefined));
				const found = await timedAsync('problems fetch', () => fetchProblems(state.generated_at));
				if (stopped) return;
				live = timed('live index', () => indexState(state));
				problems = found;
				liveProblem = null;
			} catch (e) {
				if (!stopped) liveProblem = e instanceof Error ? e.message : String(e);
			}
		};
		if (at) {
			const wait = setTimeout(load, REPLAY_WAIT_MS);
			return () => {
				stopped = true;
				clearTimeout(wait);
			};
		}
		void load();
		const timer = setInterval(load, POLL_MS);
		return () => {
			stopped = true;
			clearInterval(timer);
		};
	});

	// What the "what if" failures would do, asked again when they or the live state change.
	$effect(() => {
		const failures = $state.snapshot(ui.whatIf);
		const at = live?.state.generated_at ?? null;
		if (failures.length === 0) {
			whatIf = null;
			whatIfProblem = null;
			return;
		}
		let stopped = false;
		timedAsync('what if', () => fetchWhatIf(failures, at)).then(
			(answer) => {
				if (stopped) return;
				whatIf = answer.impact;
				whatIfProblem = null;
			},
			(e: unknown) => {
				if (!stopped) whatIfProblem = e instanceof Error ? e.message : String(e);
			}
		);
		return () => {
			stopped = true;
		};
	});

	// The last day's events, for the time slider and the events list.
	$effect(() => {
		if (!ui.live) {
			events = null;
			eventsProblem = null;
			return;
		}
		void refresh;
		let stopped = false;
		const load = async () => {
			try {
				const log = await timedAsync('events fetch', fetchEvents);
				if (stopped) return;
				events = log;
				eventsProblem = null;
			} catch (e) {
				if (!stopped) eventsProblem = e instanceof Error ? e.message : String(e);
			}
		};
		void load();
		const timer = setInterval(load, EVENTS_POLL_MS);
		return () => {
			stopped = true;
			clearInterval(timer);
		};
	});

	async function loadWindows(): Promise<void> {
		try {
			windows = await fetchWindows();
			windowsProblem = null;
		} catch (e) {
			windowsProblem = e instanceof Error ? e.message : String(e);
		}
	}

	onMount(() => {
		void loadWindows();
		const timer = setInterval(loadWindows, WINDOWS_POLL_MS);
		return () => clearInterval(timer);
	});

	// Who owns what never changes while the server runs.
	onMount(async () => {
		try {
			ownership = await fetchOwnership();
		} catch (e) {
			// Without a directory there is no one to route to; the on-call list says why.
			console.warn('No ownership', e);
		}
	});

	// The latest discovery run; also after planned work changes what is down.
	$effect(() => {
		void refresh;
		let stopped = false;
		const load = async () => {
			try {
				const found = await fetchDiscovery();
				if (stopped) return;
				comparison = found;
				discoveryProblem = null;
			} catch (e) {
				if (!stopped) discoveryProblem = e instanceof Error ? e.message : String(e);
			}
		};
		void load();
		const timer = setInterval(load, DISCOVERY_POLL_MS);
		return () => {
			stopped = true;
			clearInterval(timer);
		};
	});

	// Who is on call: now, checked now and then, or at the moment replayed.
	$effect(() => {
		const at = ui.at;
		void refresh;
		let stopped = false;
		const load = async () => {
			try {
				const found = await fetchOnCall(at ?? undefined);
				if (stopped) return;
				oncall = found;
				oncallProblem = null;
			} catch (e) {
				if (stopped) return;
				oncall = null;
				oncallProblem = e instanceof Error ? e.message : String(e);
			}
		};
		void load();
		const timer = setInterval(load, ONCALL_POLL_MS);
		return () => {
			stopped = true;
			clearInterval(timer);
		};
	});

	/**
	 * After a window is saved or deleted, a problem acknowledged or paged, or
	 * a shift covered: fetch what changed, and live state too, since the
	 * simulator acts out planned work.
	 */
	function refetch(): void {
		void loadWindows();
		refresh++;
	}

	/** Show a list in the side panel, or hide it if it is showing. */
	function toggleTab(tab: typeof ui.sideTab): void {
		const showing = ui.problemsOpen && ui.sideTab === tab;
		ui.sideTab = tab;
		ui.problemsOpen = !showing;
	}

	/** Show the next or previous problem, in the order the list has them. */
	function stepThrough(step: 1 | -1): void {
		const next = stepProblem(problems, ui.problem, step);
		if (!next) return;
		ui.sideTab = 'problems';
		ui.problemsOpen = true;
		if (ui.problem !== next.id) showProblem(next);
	}

	/** The stretch of time history covers, from the events once they are in. */
	function historySpan(): Span {
		const now = Date.now();
		return (
			events ?? {
				since: new Date(now - DAY_MS).toISOString(),
				until: new Date(now).toISOString()
			}
		);
	}

	/** What each command does. */
	const ACTIONS: Record<CommandId, (selection: Selection | null) => void> = {
		search: () => searchBox?.focus(),
		help: () => (helpOpen = true),
		focus: () => ui.focusRequest++,
		fit: () => ui.fitRequest++,
		back: () => window.history.back(),
		forward: () => window.history.forward(),
		// Escape first cancels choosing a path's destination, then clears the selection.
		clear: () => (ui.pathFrom ? (ui.pathFrom = null) : select(null)),
		'view-geo': () => (ui.view = 'geo'),
		'view-hierarchy': () => (ui.view = 'hierarchy'),
		'view-topology': () => (ui.view = 'topology'),
		neighborhood: (s) => s && showNeighborhood(s),
		'path-from': (s) => s?.kind === 'device' && startPath(s.id),
		'what-if': (s) => s && addFailure(s),
		live: () => (ui.live = !ui.live),
		problems: () => toggleTab('problems'),
		events: () => toggleTab('events'),
		maintenance: () => toggleTab('maintenance'),
		oncall: () => toggleTab('oncall'),
		discovery: () => toggleTab('discovery'),
		'discovery-map': () => (ui.discovery = !ui.discovery),
		'next-problem': () => stepThrough(1),
		'previous-problem': () => stepThrough(-1),
		earlier: () => (ui.at = stepEarlier(ui.at, historySpan())),
		later: () => ui.at && (ui.at = stepLater(ui.at, historySpan())),
		now: () => (ui.at = null),
		'copy-link': () => void copyLink(),
		wall: enterWall
	};

	function run(id: CommandId): void {
		ACTIONS[id](ui.selection ? $state.snapshot(ui.selection) : null);
	}

	function onKeydown(e: KeyboardEvent): void {
		// The wall display has keys of its own, and the help is modal.
		if (ui.wall.on || helpOpen || e.defaultPrevented) return;
		// Keys are for typing while in a box, except Ctrl+K and the like.
		const target = e.target;
		const typing =
			target instanceof HTMLElement &&
			(target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName));
		if (typing && !e.ctrlKey && !e.metaKey) return;
		const command = COMMANDS.find((c) => c.id === commandFor(e));
		if (!command || !available(command, context)) return;
		e.preventDefault();
		run(command.id);
	}
</script>

<svelte:window onkeydown={onKeydown} onpopstate={onPopState} />
{#if showPerf}<PerfPanel />{/if}
<ShortcutsHelp bind:open={helpOpen} />

<div class="app" class:wall={ui.wall.on}>
	{#if ui.wall.on}
		{#if index}<WallDisplay {index} {problems} {live} {liveProblem} {oncall} />{/if}
	{:else}
		<header>
			<h1><img src="/favicon.svg" alt="" width="22" height="22" />Sunstone</h1>
			<div class="segmented" role="group" aria-label="View">
				{#each VIEWS as view (view.id)}
					<button aria-pressed={ui.view === view.id} onclick={() => (ui.view = view.id)}>
						{view.label}
					</button>
				{/each}
			</div>
			<button
				class="live"
				aria-pressed={ui.live}
				title="Show device status and link load"
				onclick={() => (ui.live = !ui.live)}
			>
				<span class="pulse" aria-hidden="true"></span>Live
			</button>
			{#if ui.live}
				<button
					aria-pressed={ui.problemsOpen && ui.sideTab !== 'maintenance'}
					title="Show or hide the problems no one is on yet, and events"
					onclick={() => {
						if (ui.sideTab === 'maintenance') {
							ui.sideTab = 'problems';
							ui.problemsOpen = true;
						} else ui.problemsOpen = !ui.problemsOpen;
					}}
				>
					Problems{live ? ` ${unhandled}` : ''}
				</button>
				<span class="live-status" class:past={ui.at !== null} aria-live="polite">
					{#if liveProblem}
						Live state unavailable: {liveProblem}
					{:else if live}
						{live.state.source} · {ui.at ? 'replaying' : 'as of'}
						{new Date(live.state.generated_at).toLocaleTimeString()}
					{:else}
						Loading live state…
					{/if}
				</span>
			{/if}
			<button
				aria-pressed={ui.problemsOpen && ui.sideTab === 'maintenance'}
				title="Show or hide maintenance windows"
				onclick={() => toggleTab('maintenance')}
			>
				Maintenance{coming ? ` ${coming}` : ''}
			</button>
			<button
				aria-pressed={ui.problemsOpen && ui.sideTab === 'oncall'}
				title="Show or hide who is on call"
				onclick={() => toggleTab('oncall')}
			>
				On call
			</button>
			{#if index}
				<SearchBox
					bind:this={searchBox}
					{index}
					{live}
					{problems}
					{windows}
					{oncall}
					{recent}
					commands={ready}
					oncommand={run}
					onforget={forgetRecent}
				/>
				<span class="stats">
					{index.topology.sites.length} sites · {index.topology.devices.length} devices ·
					{index.topology.links.length} links
				</span>
			{/if}
			<button title="Copy a link that shows someone else exactly this" onclick={copyLink}>
				{copied ?? 'Copy link'}
			</button>
			<button title="Full-screen display for a NOC wall" onclick={enterWall}>Wall display</button>
			<button
				class="help"
				aria-label="Keyboard shortcuts"
				title="Keyboard shortcuts (?)"
				onclick={() => (helpOpen = true)}>?</button
			>
		</header>
	{/if}
	{#if ui.live && events && !ui.wall.on}
		<Timeline log={events} />
	{/if}
	<main>
		{#if problem}
			<p class="message">Could not load the topology: {problem}</p>
		{:else if !index}
			<p class="message">Loading topology…</p>
		{:else}
			{#if !ui.wall.on && ui.problemsOpen && (live || (ui.sideTab !== 'problems' && ui.sideTab !== 'events'))}
				<aside class="side" aria-label="Lists">
					<div class="segmented tabs" role="tablist" aria-label="List">
						{#if live}
							<button
								role="tab"
								aria-selected={ui.sideTab === 'problems'}
								title="{unhandled} no one is on yet, of {problems.length}"
								onclick={() => (ui.sideTab = 'problems')}>Problems {unhandled}</button
							>
							<button
								role="tab"
								aria-selected={ui.sideTab === 'events'}
								onclick={() => (ui.sideTab = 'events')}
								>Events{events ? ` ${events.events.length}` : ''}</button
							>
						{/if}
						<button
							role="tab"
							aria-selected={ui.sideTab === 'maintenance'}
							onclick={() => (ui.sideTab = 'maintenance')}
							>Maintenance{coming ? ` ${coming}` : ''}</button
						>
						<button
							role="tab"
							aria-selected={ui.sideTab === 'oncall'}
							onclick={() => (ui.sideTab = 'oncall')}>On call</button
						>
						<button
							role="tab"
							aria-selected={ui.sideTab === 'discovery'}
							title="Where discovery and the documentation disagree"
							onclick={() => (ui.sideTab = 'discovery')}
							>Discovery{comparison ? ` ${comparison.findings.length}` : ''}</button
						>
					</div>
					{#if ui.sideTab === 'discovery'}
						<DiscoveryPanel {index} {comparison} problem={discoveryProblem} />
					{:else if ui.sideTab === 'oncall'}
						<OnCallPanel {oncall} problem={oncallProblem} {problems} onchange={refetch} />
					{:else if ui.sideTab === 'maintenance'}
						<MaintenancePanel {index} {windows} problem={windowsProblem} onchange={refetch} />
					{:else if ui.sideTab === 'problems'}
						<ProblemsPanel {problems} {windows} {oncall} />
					{:else}
						<EventsPanel {index} log={events} problem={eventsProblem} />
					{/if}
				</aside>
			{/if}
			<section class="view">
				{#key ui.view}
					{#if ui.view === 'geo'}
						<GeoView {index} {path} {impact} {live} discovery={drift} />
					{:else if ui.view === 'hierarchy'}
						<HierarchyView {index} {path} {impact} {live} discovery={drift} />
					{:else}
						<TopologyView {index} {path} {impact} {live} discovery={drift} />
					{/if}
				{/key}
				<Legend live={live !== null} impact={impact !== null} discovery={drift !== null} />
				{#if ui.pathFrom}
					<p class="picking" aria-live="polite">
						Choose the destination for a path from <strong>{ui.pathFrom}</strong>: click a device or
						search. Esc cancels.
					</p>
				{/if}
			</section>
			{#if !ui.wall.on}
				<DetailsPanel
					{index}
					{path}
					{impact}
					problem={focused}
					{whatIfProblem}
					{windows}
					onchange={refetch}
					{live}
					{oncall}
					{ownership}
					{comparison}
				/>
			{/if}
		{/if}
	</main>
</div>

<style>
	.app {
		display: flex;
		flex-direction: column;
		height: 100%;
	}
	header {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 8px 12px;
		padding: 8px 14px;
		background: var(--panel);
		border-bottom: 1px solid var(--border);
	}
	h1 {
		display: flex;
		align-items: center;
		gap: 8px;
		margin: 0;
		font-size: 17px;
		font-weight: 600;
		letter-spacing: 0.02em;
	}
	.live {
		display: inline-flex;
		align-items: center;
		gap: 6px;
	}
	.pulse {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		background: var(--muted);
	}
	.live[aria-pressed='true'] {
		border-color: var(--live);
	}
	.live[aria-pressed='true'] .pulse {
		background: var(--live);
		animation: pulse 2s ease-in-out infinite;
	}
	@keyframes pulse {
		50% {
			opacity: 0.3;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.live[aria-pressed='true'] .pulse {
			animation: none;
		}
	}
	.live-status {
		color: var(--muted);
		font-size: 12px;
		white-space: nowrap;
	}
	.live-status.past {
		color: var(--selected);
	}
	.side {
		flex: none;
		width: min(330px, 30vw);
		overflow-y: auto;
		background: var(--panel);
		border-right: 1px solid var(--border);
		padding: 10px;
		font-size: 13px;
	}
	.tabs {
		margin-bottom: 10px;
	}
	.tabs {
		flex-wrap: wrap;
	}
	.tabs button {
		flex: 1 1 auto;
		padding: 4px 6px;
		white-space: nowrap;
	}
	.tabs button[aria-selected='true'] {
		background: var(--panel-2);
		border-color: var(--live);
	}
	.help {
		width: 28px;
		padding: 4px 0;
		border-radius: 50%;
	}
	header button {
		white-space: nowrap;
	}
	/* Takes the room left over, and gives it up first. */
	.stats {
		flex: 1 1 0;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		text-align: right;
		color: var(--muted);
		font-size: 12px;
		white-space: nowrap;
	}
	main {
		display: flex;
		flex: 1;
		min-height: 0;
	}
	.view {
		position: relative;
		flex: 1;
		min-width: 0;
		/* clip, not hidden: a hidden overflow can still be scrolled, for example
		   by focusing a field in a popover that pokes past the edge. */
		overflow: clip;
	}
	.picking {
		position: absolute;
		bottom: 56px;
		left: 50%;
		transform: translateX(-50%);
		margin: 0;
		padding: 8px 14px;
		background: var(--panel);
		border: 1px solid var(--path);
		border-radius: 6px;
		box-shadow: 0 8px 24px rgb(0 0 0 / 0.4);
	}
	.message {
		padding: 24px;
		color: var(--muted);
	}
</style>
