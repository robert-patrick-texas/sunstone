<!--
@component
The app: header with view switch and search, the current view, the legend,
the details panel for whatever is selected, a side panel of maintenance
windows, and with live state, a time slider over the last day and problems
and events in the side panel too. The address bar always holds a link to
what is on screen, and opening such a link shows it again. In wall display
mode, the wall's bar and captions take the place of the controls.
-->
<script lang="ts">
	import '../app.css';
	import { onMount } from 'svelte';
	import { replaceState } from '$app/navigation';
	import { fetchProblems, fetchWhatIf, type Problem } from '#lib/api/analysis.ts';
	import { fetchWindows, type Window } from '#lib/api/operations.ts';
	import { fetchEvents, fetchState, type EventLog } from '#lib/api/state.ts';
	import { fetchTopology } from '#lib/api/topology.ts';
	import DetailsPanel from '#lib/DetailsPanel.svelte';
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
	import { indexState, type LiveIndex } from '#lib/live.ts';
	import { shortestPaths } from '#lib/paths.ts';
	import ProblemsPanel from '#lib/ProblemsPanel.svelte';
	import SearchBox from '#lib/SearchBox.svelte';
	import {
		clearPath,
		expandedSites,
		fromLink,
		select,
		topo,
		ui,
		type View
	} from '#lib/state.svelte.ts';
	import Timeline from '#lib/Timeline.svelte';
	import { compareNatural, indexTopology, type TopologyIndex } from '#lib/topology.ts';
	import { fromQuery, readable, toQuery, type Shared } from '#lib/url.ts';
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
	// While the time slider is dragged, wait for it to settle before fetching.
	const REPLAY_WAIT_MS = 200;

	let index = $state.raw<TopologyIndex | null>(null);
	let live = $state.raw<LiveIndex | null>(null);
	let liveProblem = $state<string | null>(null);
	let events = $state.raw<EventLog | null>(null);
	let eventsProblem = $state<string | null>(null);
	let windows = $state.raw<Window[]>([]);
	let windowsProblem = $state<string | null>(null);
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
	// A path, when shown, takes the place of an impact.
	const impact = $derived.by(() => {
		if (!index || path || ui.pathFrom) return null;
		return ui.whatIf.length === 0 ? (focused?.impact ?? null) : whatIf;
	});
	let problem = $state<string | null>(null);
	let showPerf = $state(false);
	let copied = $state<string | null>(null);

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

	/** Show what a link asks for. */
	function openLink(found: Partial<Shared>): void {
		if (found.topo) Object.assign(topo, found.topo);
		if (found.expanded) {
			expandedSites.clear();
			for (const code of found.expanded) expandedSites.add(code);
		}
		if (found.view) ui.view = found.view;
		if (found.selection) ui.selection = found.selection;
		if (found.path) ui.path = found.path;
		if (found.whatIf) ui.whatIf = found.whatIf;
		if (found.live) {
			ui.live = true;
			ui.at = found.at ?? null;
			ui.problem = found.problem ?? null;
		}
		if (found.camera) fromLink.camera = found.camera;
		if (found.wall) {
			ui.wall.on = true;
			ui.wall.dwell = found.wall.dwell;
		}
	}

	// Keep the address bar a link to what is on screen.
	$effect(() => {
		if (!index) return;
		const shared: Shared = {
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
			wall: ui.wall.on ? { dwell: ui.wall.dwell } : null
		};
		// ?perf is for measuring, not for sharing, but keep it while measuring.
		const parts = [readable(toQuery(shared, index)), showPerf ? 'perf' : ''].filter(Boolean);
		const search = parts.length ? `?${parts.join('&')}` : '';
		if (search !== location.search) replaceState(`${location.pathname}${search}`, {});
	});

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

	/**
	 * After a window is saved or deleted, or a problem acknowledged: fetch
	 * what changed, and live state too, since the simulator acts out planned work.
	 */
	function refetch(): void {
		void loadWindows();
		refresh++;
	}

	function toggleMaintenance(): void {
		const showing = ui.problemsOpen && ui.sideTab === 'maintenance';
		ui.sideTab = 'maintenance';
		ui.problemsOpen = !showing;
	}

	function onKeydown(e: KeyboardEvent): void {
		// The wall display has keys of its own.
		if (ui.wall.on || e.key !== 'Escape' || e.target instanceof HTMLInputElement) return;
		// Escape first cancels choosing a path's destination, then clears the selection.
		if (ui.pathFrom) ui.pathFrom = null;
		else select(null);
	}
</script>

<svelte:window onkeydown={onKeydown} />
{#if showPerf}<PerfPanel />{/if}

<div class="app" class:wall={ui.wall.on}>
	{#if ui.wall.on}
		{#if index}<WallDisplay {index} {problems} {live} {liveProblem} />{/if}
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
				onclick={toggleMaintenance}
			>
				Maintenance{coming ? ` ${coming}` : ''}
			</button>
			{#if index}
				<SearchBox {index} />
				<span class="stats">
					{index.topology.sites.length} sites · {index.topology.devices.length} devices ·
					{index.topology.links.length} links
				</span>
			{/if}
			<button title="Copy a link that shows someone else exactly this" onclick={copyLink}>
				{copied ?? 'Copy link'}
			</button>
			<button title="Full-screen display for a NOC wall" onclick={enterWall}>Wall display</button>
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
			{#if !ui.wall.on && ui.problemsOpen && (live || ui.sideTab === 'maintenance')}
				<aside class="side" aria-label="Problems, events, and maintenance">
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
					</div>
					{#if ui.sideTab === 'maintenance'}
						<MaintenancePanel {index} {windows} problem={windowsProblem} onchange={refetch} />
					{:else if ui.sideTab === 'problems'}
						<ProblemsPanel {problems} {windows} />
					{:else}
						<EventsPanel {index} log={events} problem={eventsProblem} />
					{/if}
				</aside>
			{/if}
			<section class="view">
				{#key ui.view}
					{#if ui.view === 'geo'}
						<GeoView {index} {path} {impact} {live} />
					{:else if ui.view === 'hierarchy'}
						<HierarchyView {index} {path} {impact} {live} />
					{:else}
						<TopologyView {index} {path} {impact} {live} />
					{/if}
				{/key}
				<Legend live={live !== null} impact={impact !== null} />
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
		align-items: center;
		gap: 16px;
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
		width: min(300px, 30vw);
		overflow-y: auto;
		background: var(--panel);
		border-right: 1px solid var(--border);
		padding: 10px;
		font-size: 13px;
	}
	.tabs {
		margin-bottom: 10px;
	}
	.tabs button {
		flex: 1;
		padding: 4px 6px;
		white-space: nowrap;
	}
	.tabs button[aria-selected='true'] {
		background: var(--panel-2);
		border-color: var(--live);
	}
	.stats {
		margin-left: auto;
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
