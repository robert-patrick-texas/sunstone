<!--
@component
Details of the current selection: a device and its neighbors, a site and
its WAN links, or a set of links. With live state, also health, round-trip
times from each monitoring position, and load on each link, and what
failing it would do. Above it, the shortest paths between two devices when
a path is shown, hop by hop with interfaces; or the impact being shown, of
a problem or of "what if" failures. With live state, charts of the last
day: round trip to a device, load on each of its links, and load on a
selected link; clicking a chart replays that moment. Names in the panel are
links that select and bring that item into view.
-->
<script lang="ts">
	import { fetchWhatIf, type Problem, type WhatIf } from './api/analysis.ts';
	import type { Comparison } from './api/discovery.ts';
	import type { OnCall, Ownership } from './api/oncall.ts';
	import { acknowledge, unacknowledge, type Window } from './api/operations.ts';
	import { fetchHistory, type DeviceHistory, type InterfaceHistory } from './api/state.ts';
	import type { Endpoint, Link } from './api/topology.ts';
	import { clock, linkHistory } from './history.ts';
	import { phaseOf, span, windowsFor } from './maintenance.ts';
	import type { Impact } from './impact.ts';
	import {
		deviceHealth,
		groupHealth,
		HEALTH_LABEL,
		linkLive,
		type DeviceHealth,
		type LiveIndex
	} from './live.ts';
	import { linksBetween, type PathResult } from './paths.ts';
	import {
		addFailure,
		planMaintenance,
		rememberName,
		clearPath,
		expandedSites,
		select,
		showNeighborhood,
		startPath,
		topo,
		ui,
		type Selection
	} from './state.svelte.ts';
	import DiscoveryFor from './DiscoveryFor.svelte';
	import OnCallFor from './OnCallFor.svelte';
	import Routing from './Routing.svelte';
	import Spark from './Spark.svelte';
	import { HEALTH_COLOR, HEALTH_GLYPH, ROLE_COLOR, SERIES_COLOR, utilColor } from './theme.ts';
	import TimeChart from './TimeChart.svelte';
	import {
		compareNatural,
		formatSpeed,
		linkName,
		neighborsOf,
		ROLE_LABEL,
		ROLES,
		shortInterface,
		siteOf,
		type TopologyIndex
	} from './topology.ts';

	const {
		index,
		path,
		impact,
		problem,
		whatIfProblem,
		windows,
		onchange,
		live,
		oncall,
		ownership,
		comparison
	}: {
		index: TopologyIndex;
		path: PathResult | null;
		impact: Impact | null;
		problem: Problem | null;
		/** Why the "what if" impact could not be worked out, if it could not. */
		whatIfProblem: string | null;
		windows: Window[];
		/** Called after a problem is acknowledged or paged, or that is withdrawn. */
		onchange: () => void;
		live: LiveIndex | null;
		/** Who is on call, or null without an on-call directory. */
		oncall: OnCall | null;
		ownership: Ownership | null;
		/** The latest discovery run, against the documentation. */
		comparison: Comparison | null;
	} = $props();

	const HEALTHS: DeviceHealth[] = ['down', 'degraded', 'nodata', 'up', 'unmonitored'];
	const LINK_STATE: Record<string, string> = {
		down: 'down',
		nodata: 'no data',
		unmonitored: 'not monitored'
	};
	/** Most groups of exposed devices, and failed devices, listed one by one. */
	const MAX_GROUPS = 8;
	const MAX_NAMED = 12;

	let ackNote = $state('');
	let ackProblem = $state<string | null>(null);
	const RECENT_MS = 24 * 60 * 60_000;

	async function ack(e: SubmitEvent, id: string): Promise<void> {
		e.preventDefault();
		rememberName(ui.person.trim());
		try {
			await acknowledge(id, ackNote, ui.person);
			ackNote = '';
			ackProblem = null;
			onchange();
		} catch (err) {
			ackProblem = err instanceof Error ? err.message : String(err);
		}
	}

	async function withdraw(id: string): Promise<void> {
		try {
			await unacknowledge(id);
			ackProblem = null;
			onchange();
		} catch (err) {
			ackProblem = err instanceof Error ? err.message : String(err);
		}
	}

	/** Load on a link as seen leaving and entering one of its ends. */
	function loadAt(l: LiveIndex, link: Link, end: Endpoint) {
		const state = linkLive(l, link);
		const fromA = link.a.device === end.device && link.a.interface === end.interface;
		return {
			health: state.health,
			out: fromA ? state.aToB : state.bToA,
			in: fromA ? state.bToA : state.aToB
		};
	}

	function minutesAgo(iso: string): string {
		return `${Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 60_000))} min ago`;
	}

	const selection = $derived(ui.selection);
	const replayed = $derived(ui.at ? Date.parse(ui.at) : null);

	/** History is fetched again this often while the same device stays selected. */
	const HISTORY_REFRESH_MS = 5 * 60_000;
	const DOWN = { label: 'Down', color: HEALTH_COLOR.down };
	const NODATA = { label: 'No data', color: HEALTH_COLOR.nodata };
	const LOSS = { label: 'Packet loss', color: HEALTH_COLOR.degraded };

	// The device whose last day to chart: the selected device, or the end of
	// the selected link that the source monitors.
	const historyDevice = $derived.by(() => {
		if (!live || !selection) return null;
		if (selection.kind === 'device') return live.devices.has(selection.id) ? selection.id : null;
		if (selection.kind !== 'links' || selection.ids.length !== 1) return null;
		const link = index.links.get(selection.ids[0] ?? '');
		return link ? ([link.a.device, link.b.device].find((d) => live.devices.has(d)) ?? null) : null;
	});
	let history = $state.raw<DeviceHistory | null>(null);
	let historyProblem = $state<string | null>(null);

	$effect(() => {
		const device = historyDevice;
		history = null;
		historyProblem = null;
		if (!device) return;
		let stopped = false;
		const load = async () => {
			try {
				const found = await fetchHistory(device);
				if (!stopped) history = found;
			} catch (e) {
				if (!stopped) historyProblem = e instanceof Error ? e.message : String(e);
			}
		};
		void load();
		const timer = setInterval(load, HISTORY_REFRESH_MS);
		return () => {
			stopped = true;
			clearInterval(timer);
		};
	});

	function replay(time: number): void {
		ui.at = new Date(time).toISOString();
	}

	/** Down, no data, or packet loss at each step of a device's history. */
	function deviceStrip(h: DeviceHistory) {
		return h.status.map((status, i) => {
			if (status === 'down') return DOWN;
			if (status === 'nodata') return NODATA;
			const lossy = Object.values(h.loss_pct).some((l) => (l[i] ?? 0) > 0);
			return lossy ? LOSS : null;
		});
	}

	/** Load in an interface's busier direction at each step. */
	function busier(h: InterfaceHistory): (number | null)[] {
		return h.in_pct.map((inbound, i) => {
			const outbound = h.out_pct[i] ?? null;
			return inbound === null && outbound === null ? null : Math.max(inbound ?? 0, outbound ?? 0);
		});
	}

	function positionLabel(name: string): string {
		const at = live?.state.positions.find((p) => p.name === name);
		return at ? `${name} (${at.site})` : name;
	}
	// What failing the selection alone would do, on top of what live state
	// shows down now, asked of the server. Each answer is kept with the
	// selection it is for, so an old one never shows beside a new selection.
	let answered = $state.raw<{ key: string; answer: WhatIf } | null>(null);
	const selectionKey = $derived(JSON.stringify(selection));
	const ifFails = $derived(answered?.key === selectionKey ? answered.answer : null);

	$effect(() => {
		const target = selection ? $state.snapshot(selection) : null;
		const key = JSON.stringify(target);
		const at = live?.state.generated_at ?? null;
		if (!target) return;
		let stopped = false;
		fetchWhatIf([target], at).then(
			(answer) => {
				if (!stopped) answered = { key, answer };
			},
			// Without an answer the line is left out; the details are still there.
			(e: unknown) => console.warn('Could not ask what failing the selection would do', e)
		);
		return () => {
			stopped = true;
		};
	});

	function plural(n: number, noun: string): string {
		return `${n} ${noun}${n === 1 ? '' : 's'}`;
	}

	function consequence({ impact: i, already }: WhatIf, subject: string): string {
		if (already) return `Live state already shows ${subject} down or cut off.`;
		const parts: string[] = [];
		if (i.cutOff.size) parts.push(`cut off ${plural(i.cutOff.size, 'device')}`);
		if (i.exposed.size) parts.push(`leave ${plural(i.exposed.size, 'device')} without redundancy`);
		return parts.length
			? `Failing ${subject} would ${parts.join(' and ')}.`
			: `Failing ${subject} would cut nothing else off, and every device would keep a second path.`;
	}

	function itemName(item: Selection): string {
		if (item.kind === 'device') return item.id;
		if (item.kind === 'site') return `${item.id} (whole site)`;
		const links = item.ids.flatMap((id) => index.links.get(id) ?? []);
		return links.length === 1 && links[0] ? linkName(links[0]) : `${links.length} links`;
	}

	function sitesOf(devices: Iterable<string>): string[] {
		return [...new Set([...devices].map((d) => siteOf(index, d)))].sort(compareNatural);
	}

	/** How many of some devices are at each site, most first. */
	function countBySite(devices: Set<string>): [string, number][] {
		const counts = new Map<string, number>();
		for (const d of devices) counts.set(siteOf(index, d), (counts.get(siteOf(index, d)) ?? 0) + 1);
		return [...counts].sort((x, y) => y[1] - x[1] || compareNatural(x[0], y[0]));
	}

	/** Exposed devices grouped by the devices they now depend on, biggest group first. */
	function dependents(exposed: Map<string, string[]>): { chain: string[]; devices: string[] }[] {
		const groups = new Map<string, { chain: string[]; devices: string[] }>();
		for (const [device, chain] of exposed) {
			const key = chain.join(' ');
			const group = groups.get(key) ?? { chain, devices: [] };
			group.devices.push(device);
			groups.set(key, group);
		}
		return [...groups.values()].sort((x, y) => y.devices.length - x.devices.length);
	}

	/** Select a name in the panel; the click must not also reach its row, which selects the link. */
	function follow(e: MouseEvent, target: Selection): void {
		e.stopPropagation();
		select(target, true);
	}

	/** Interfaces of `device` on the given links, with their LAG if bundled. */
	function interfacesOf(links: Link[], device: string): string {
		const ends = links.map((l) => (l.a.device === device ? l.a : l.b));
		const lag = ends[0]?.lag;
		const names = ends.map((e) => shortInterface(e.interface)).join(', ');
		return lag ? `${names} (${shortInterface(lag)})` : names;
	}

	function showPathInTopology(): void {
		topo.scope = 'path';
		ui.view = 'topology';
	}

	function siteWanLinks(code: string): { local: Endpoint; remote: Endpoint; link: Link }[] {
		return (index.devicesBySite.get(code) ?? []).flatMap((d) =>
			neighborsOf(index, d.name).filter((n) => siteOf(index, n.remote.device) !== code)
		);
	}
</script>

{#snippet healthBadge(health: DeviceHealth, text: string)}
	<span class="health" class:hollow={health === 'unmonitored'} style:--c={HEALTH_COLOR[health]}
		><i>{HEALTH_GLYPH[health]}</i>{text}</span
	>
{/snippet}

{#snippet load(health: string, out: number | null, inbound: number | null)}
	{#if health === 'ok' && out !== null && inbound !== null}
		<i class="bar" style:background={utilColor(Math.max(out, inbound))}></i>{Math.round(out)}% / {Math.round(
			inbound
		)}%
	{:else}
		<span class="muted">{LINK_STATE[health] ?? '—'}</span>
	{/if}
{/snippet}

{#snippet deviceLink(name: string)}
	<button class="link" onclick={(e) => follow(e, { kind: 'device', id: name })}>{name}</button>
{/snippet}

{#snippet siteLink(code: string)}
	<button class="link" onclick={(e) => follow(e, { kind: 'site', id: code })}>{code}</button>
{/snippet}

{#snippet whatIf(item: Selection, label: string)}
	{@const added = ui.whatIf.some((f) => JSON.stringify(f) === JSON.stringify(item))}
	<button disabled={added} onclick={() => addFailure($state.snapshot(item))}>
		{added ? 'In what if' : ui.whatIf.length ? 'Add to what if' : label}
	</button>
{/snippet}

{#snippet planButton(item: Selection)}
	<button onclick={() => planMaintenance([$state.snapshot(item)])}>Plan maintenance…</button>
{/snippet}

{#snippet maintenanceOf(item: Selection)}
	{@const now = Date.now()}
	{@const found = windowsFor(index, windows, item).filter(
		(w) => phaseOf(w, now) !== 'ended' || now - Date.parse(w.end) < RECENT_MS
	)}
	{#if found.length}
		<h3>Maintenance ({found.length})</h3>
		<ul class="windows">
			{#each found as w (w.id)}
				{@const phase = phaseOf(w, now)}
				<li>
					<span class="phase {phase}"
						>{phase === 'open' ? 'Open now' : phase === 'upcoming' ? 'Coming up' : 'Ended'}</span
					>
					{w.title} <span class="muted">· {span(w)} · {w.by}</span>
				</li>
			{/each}
		</ul>
	{/if}
{/snippet}

{#snippet consequences(i: Impact)}
	{#if ui.whatIf.length === 0 && i.failed.devices.size}
		{@const down = [...i.failed.devices].sort(compareNatural)}
		<h3>Down ({down.length})</h3>
		<p class="names">
			{#each down.slice(0, MAX_NAMED) as d (d)}{@render deviceLink(d)}{/each}
			{#if down.length > MAX_NAMED}<span class="muted">and {down.length - MAX_NAMED} more</span
				>{/if}
		</p>
	{/if}
	{#if i.cutOff.size}
		<h3>Cut off ({i.cutOff.size})</h3>
		<p class="names">
			{#each countBySite(i.cutOff) as [site, n] (site)}
				<span>{@render siteLink(site)} {n}</span>
			{/each}
		</p>
	{/if}
	{#if i.exposed.size}
		{@const groups = dependents(i.exposed)}
		<h3>No redundancy left ({i.exposed.size})</h3>
		<ul class="groups">
			{#each groups.slice(0, MAX_GROUPS) as g (g.chain.join(' '))}
				<li>
					{plural(g.devices.length, 'device')} at {sitesOf(g.devices).join(', ')}
					{g.devices.length === 1 ? 'depends' : 'depend'} on
					{#each g.chain as d, j (d)}{j > 0 ? ' and ' : ''}{@render deviceLink(d)}{/each}
				</li>
			{/each}
		</ul>
		{#if groups.length > MAX_GROUPS}
			<p class="muted">and {groups.length - MAX_GROUPS} more groups</p>
		{/if}
	{/if}
	{#if i.cutOff.size === 0 && i.exposed.size === 0}
		<p>Nothing else is cut off, and every device keeps a second path to the core.</p>
	{/if}
{/snippet}

{#snippet endpoint(end: Endpoint)}
	{@render deviceLink(end.device)}
	<span class="mono">{shortInterface(end.interface)}</span>
	{#if end.lag}<span class="tag">{shortInterface(end.lag)}</span>{/if}
{/snippet}

{#if selection || path || ui.pathFrom || impact || problem || (ui.whatIf.length && whatIfProblem)}
	<aside class="details" aria-label="Details">
		{#if ui.pathFrom}
			<section class="path" aria-label="Path">
				<h2>Path from {ui.pathFrom}</h2>
				<p class="muted">Click a device or search for the destination.</p>
				<p class="actions"><button onclick={clearPath}>Cancel</button></p>
			</section>
		{:else if path}
			<section class="path" aria-label="Path">
				<button class="close" onclick={clearPath} aria-label="Clear path">×</button>
				<h2>Path</h2>
				<p>{@render deviceLink(path.from)} → {@render deviceLink(path.to)}</p>
				{#if path.hops === null}
					<p class="muted">No links join these devices, so there is no path.</p>
				{:else}
					<p class="muted">
						{path.hops} hops by link count ·
						{path.count === 1 ? 'one path' : `${path.count} equal-length paths`}
					</p>
					<p class="actions"><button onclick={showPathInTopology}>Show in topology</button></p>
					{#each path.listed as devices, i (devices.join(' '))}
						<details open={i === 0}>
							<summary>
								Path {i + 1}{devices.length > 2 ? ` via ${devices.slice(1, -1).join(' › ')}` : ''}
							</summary>
							<ol class="hops">
								{#each devices as device, j (device)}
									{@const next = devices[j + 1]}
									<li>
										{@render deviceLink(device)}
										{#if next}
											{@const links = linksBetween(index, path, device, next)}
											<span class="mono">
												{interfacesOf(links, device)} → {interfacesOf(links, next)}
											</span>
										{/if}
									</li>
								{/each}
							</ol>
						</details>
					{/each}
					{#if path.count > path.listed.length}
						<p class="muted">and {path.count - path.listed.length} more</p>
					{/if}
				{/if}
			</section>
		{:else if ui.whatIf.length && whatIfProblem}
			<section class="impact" aria-label="Impact">
				<button class="close" onclick={() => (ui.whatIf = [])} aria-label="Clear what if">×</button>
				<h2>What if</h2>
				<p class="muted">Could not work out what these failures would do: {whatIfProblem}</p>
			</section>
		{:else if impact || problem}
			<section class="impact" aria-label="Impact">
				{#if ui.whatIf.length}
					<button class="close" onclick={() => (ui.whatIf = [])} aria-label="Clear what if"
						>×</button
					>
					<h2>What if {ui.whatIf.length === 1 ? 'this fails' : 'these fail'}</h2>
					<ul class="failures">
						{#each ui.whatIf as item, i (JSON.stringify(item))}
							<li>
								<button class="link" onclick={(e) => follow(e, $state.snapshot(item))}
									>{itemName(item)}</button
								>
								<button
									class="remove"
									aria-label="Remove {itemName(item)}"
									onclick={() => ui.whatIf.splice(i, 1)}>×</button
								>
							</li>
						{/each}
					</ul>
					{#if live}<p class="muted">On top of what live state shows down now.</p>{/if}
				{:else if problem}
					<button class="close" onclick={() => (ui.problem = null)} aria-label="Stop showing impact"
						>×</button
					>
					<h2>{problem.title}</h2>
					{#if problem.detail}<p class="muted">{problem.detail}</p>{/if}
					{#each problem.planned as id (id)}
						{@const w = windows.find((x) => x.id === id)}
						<p class="handled">
							<span class="phase open">Planned</span>
							{w ? `${w.title} · ${span(w)} · ${w.by}` : 'Maintenance accounts for it'}
						</p>
					{/each}
					{#if ui.at === null}
						{#if problem.ack}
							<p class="handled">
								<span class="phase ack">On it</span>
								{problem.ack.by} since {clock(problem.ack.at)}{problem.ack.note
									? `: ${problem.ack.note}`
									: ''}
								<button class="link" onclick={() => withdraw(problem.id)}>Withdraw</button>
							</p>
						{:else}
							<form class="ack-form" onsubmit={(e) => ack(e, problem.id)}>
								<input
									bind:value={ackNote}
									maxlength="1000"
									placeholder="What is being done"
									aria-label="Note"
								/>
								<input
									bind:value={ui.person}
									required
									maxlength="64"
									placeholder="Your name"
									aria-label="Your name"
									autocomplete="name"
								/>
								<button type="submit">Acknowledge</button>
							</form>
						{/if}
						{#if ackProblem}<p class="muted" role="alert">{ackProblem}</p>{/if}
					{:else if problem.ack}
						<p class="handled">
							<span class="phase ack">On it</span>
							{problem.ack.by} since {clock(problem.ack.at)}
						</p>
					{/if}
					<Routing {index} {problem} {oncall} {onchange} />
				{/if}
				{#if impact}{@render consequences(impact)}{/if}
			</section>
		{/if}

		{#if selection}
			<section aria-label="Selection">
				<button class="close" onclick={() => select(null)} aria-label="Close details">×</button>

				{#if selection.kind === 'device'}
					{@const device = index.devices.get(selection.id)}
					{#if device}
						{@const neighbors = neighborsOf(index, device.name)}
						<h2>{device.name}</h2>
						<p>
							<span class="role" style:--role={ROLE_COLOR[device.role]}
								>{ROLE_LABEL[device.role]}</span
							>
							at {@render siteLink(device.site)}
							{index.sites.get(device.site)?.name}
						</p>
						{#if live}
							{@const record = live.devices.get(device.name)}
							{@const health = deviceHealth(live, device.name)}
							<p>
								{@render healthBadge(health, HEALTH_LABEL[health])}
								{#if record?.stale}<span class="muted">
										· last reading {minutesAgo(record.observed_at)}</span
									>{/if}
							</p>
							{#if record}
								<table class="reach">
									<thead><tr><th>From</th><th>Round trip</th><th>Loss</th></tr></thead>
									<tbody>
										{#each record.reachability as r (r.position)}
											{@const at = live.state.positions.find((p) => p.name === r.position)}
											<tr>
												<td>{r.position}{at ? ` (${at.site})` : ''}</td>
												<td>{r.rtt_ms === null ? '—' : `${r.rtt_ms.toFixed(1)} ms`}</td>
												<td>{r.loss_pct === null ? '—' : `${r.loss_pct}%`}</td>
											</tr>
										{/each}
									</tbody>
								</table>
							{:else}
								<p class="muted">The {live.state.source} source does not watch this device.</p>
							{/if}
							{#if history?.device === device.name}
								<h3>Last 24 hours</h3>
								<TimeChart
									label="Round trip to {device.name} over the last 24 hours"
									start={Date.parse(history.start)}
									step={history.step_s * 1000}
									series={Object.entries(history.rtt_ms).map(([position, values], i) => ({
										label: positionLabel(position),
										color: SERIES_COLOR[i % SERIES_COLOR.length] ?? '',
										values
									}))}
									unit=" ms"
									strip={deviceStrip(history)}
									at={replayed}
									onpick={replay}
								/>
							{:else if historyProblem}
								<p class="muted">History unavailable: {historyProblem}</p>
							{/if}
						{/if}
						<dl>
							{#if device.platform}<dt>Platform</dt>
								<dd>{device.platform}</dd>{/if}
							{#if device.mgmt_ip}<dt>Management</dt>
								<dd class="mono">{device.mgmt_ip}</dd>{/if}
						</dl>
						<p class="actions">
							<button onclick={() => showNeighborhood({ kind: 'device', id: device.name })}>
								Show neighborhood
							</button>
							<button onclick={() => startPath(device.name)}>Path from here</button>
							{@render whatIf(selection, 'What if it fails?')}
							{@render planButton(selection)}
						</p>
						{#if ifFails}<p class="muted">{consequence(ifFails, 'it')}</p>{/if}
						<OnCallFor {index} {oncall} {ownership} item={selection} />
						{@render maintenanceOf(selection)}
						<DiscoveryFor {index} {comparison} item={selection} />
						<h3>Neighbors ({neighbors.length})</h3>
						<table>
							<thead>
								<tr>
									<th>Local</th><th>Neighbor</th><th>Remote</th><th>Speed</th>
									{#if live}<th title="Percent of capacity, out of and into this device"
											>Out / in</th
										>{/if}
									{#if history?.device === device.name}<th
											title="Load in the busier direction over the last 24 hours: amber from 80%, red from 95%; red ticks where the link was down"
											>24 h</th
										>{/if}
								</tr>
							</thead>
							<tbody>
								{#each neighbors as n (n.link.id)}
									<tr onclick={() => select({ kind: 'links', ids: [n.link.id] }, true)}>
										<td class="mono">
											{shortInterface(n.local.interface)}
											{#if n.local.lag}<span class="tag">{shortInterface(n.local.lag)}</span>{/if}
										</td>
										<td>{@render deviceLink(n.remote.device)}</td>
										<td class="mono">{shortInterface(n.remote.interface)}</td>
										<td>
											{formatSpeed(n.link.speed_mbps)}
											{#if n.link.kind === 'wan'}<span class="tag wan">WAN</span>{/if}
										</td>
										{#if live}
											{@const at = loadAt(live, n.link, n.local)}
											<td class="nowrap">{@render load(at.health, at.out, at.in)}</td>
										{/if}
										{#if history?.device === device.name}
											{@const h = history.interfaces.find((i) => i.interface === n.local.interface)}
											<td>
												{#if h}<Spark
														values={busier(h)}
														down={h.oper.map((o) => o === 'down')}
														start={Date.parse(history.start)}
														step={history.step_s * 1000}
														at={replayed}
													/>{/if}
											</td>
										{/if}
									</tr>
								{/each}
							</tbody>
						</table>
					{/if}
				{:else if selection.kind === 'site'}
					{@const site = index.sites.get(selection.id)}
					{#if site}
						{@const devices = index.devicesBySite.get(site.code) ?? []}
						{@const wan = siteWanLinks(site.code)}
						<h2>{site.code} · {site.name}</h2>
						<p class="muted">
							{site.region ?? 'No region'} · {site.lat.toFixed(4)}, {site.lon.toFixed(4)}
						</p>
						<p class="roles">
							{#each ROLES as role (role)}
								{@const count = devices.filter((d) => d.role === role).length}
								{#if count}
									<span class="role" style:--role={ROLE_COLOR[role]}
										>{count} {ROLE_LABEL[role]}</span
									>
								{/if}
							{/each}
						</p>
						{#if live}
							{@const { counts } = groupHealth(
								live,
								devices.map((d) => d.name)
							)}
							<p class="roles">
								{#each HEALTHS as health (health)}
									{#if counts[health]}
										{@render healthBadge(health, `${counts[health]} ${HEALTH_LABEL[health]}`)}
									{/if}
								{/each}
							</p>
						{/if}
						<p class="actions">
							<button
								title="Show the site's devices in the hierarchy and topology views"
								onclick={() =>
									expandedSites.has(site.code)
										? expandedSites.delete(site.code)
										: expandedSites.add(site.code)}
							>
								{expandedSites.has(site.code) ? 'Collapse site' : 'Expand site'}
							</button>
							<button onclick={() => showNeighborhood({ kind: 'site', id: site.code })}>
								Show neighborhood
							</button>
							{@render whatIf(selection, 'What if it fails?')}
							{@render planButton(selection)}
						</p>
						{#if ifFails}<p class="muted">{consequence(ifFails, 'the whole site')}</p>{/if}
						<OnCallFor {index} {oncall} {ownership} item={selection} />
						{@render maintenanceOf(selection)}
						<DiscoveryFor {index} {comparison} item={selection} />
						<h3>Links to other sites ({wan.length})</h3>
						<table>
							<thead><tr><th>Local</th><th>Remote</th><th>Speed</th><th>Circuit</th></tr></thead>
							<tbody>
								{#each wan as n (n.link.id)}
									<tr onclick={() => select({ kind: 'links', ids: [n.link.id] }, true)}>
										<td>{@render endpoint(n.local)}</td>
										<td
											>{@render siteLink(siteOf(index, n.remote.device))}
											{@render endpoint(n.remote)}</td
										>
										<td>{formatSpeed(n.link.speed_mbps)}</td>
										<td class="muted">
											{n.link.circuit
												? `${n.link.circuit.provider} ${n.link.circuit.circuit_id}`
												: ''}
										</td>
									</tr>
								{/each}
							</tbody>
						</table>
						<details>
							<summary>Devices ({devices.length})</summary>
							<ul class="devices">
								{#each devices as d (d.name)}
									<li>
										<span class="dot" style:--role={ROLE_COLOR[d.role]}></span>{@render deviceLink(
											d.name
										)}
									</li>
								{/each}
							</ul>
						</details>
					{/if}
				{:else}
					{@const links = selection.ids.flatMap((id) => index.links.get(id) ?? [])}
					{@const total = links.reduce((s, l) => s + l.speed_mbps, 0)}
					<h2>{links.length === 1 ? 'Link' : `${links.length} links`}</h2>
					<p class="muted">{formatSpeed(total)} total capacity</p>
					<p class="actions">
						{@render whatIf(
							selection,
							links.length === 1 ? 'What if it fails?' : 'What if they fail?'
						)}
						{@render planButton(selection)}
					</p>
					{#if ifFails}
						<p class="muted">{consequence(ifFails, links.length === 1 ? 'it' : 'them')}</p>
					{/if}
					<OnCallFor {index} {oncall} {ownership} item={selection} />
					{@render maintenanceOf(selection)}
					<DiscoveryFor {index} {comparison} item={selection} />
					<table>
						<thead>
							<tr>
								<th>A end</th><th>B end</th><th>Speed</th>
								{#if live}<th title="Percent of capacity, A to B and B to A">A→B / B→A</th>{/if}
							</tr>
						</thead>
						<tbody>
							{#each links as link (link.id)}
								<tr>
									<td>{@render endpoint(link.a)}</td>
									<td>{@render endpoint(link.b)}</td>
									<td>
										{formatSpeed(link.speed_mbps)}
										{#if link.kind === 'wan'}<span class="tag wan">WAN</span>{/if}
									</td>
									{#if live}
										{@const at = loadAt(live, link, link.a)}
										<td class="nowrap">{@render load(at.health, at.out, at.in)}</td>
									{/if}
								</tr>
								{#if link.circuit}
									<tr class="sub">
										<td colspan={live ? 4 : 3}>
											Circuit {link.circuit.circuit_id} · {link.circuit.provider}
										</td>
									</tr>
								{/if}
							{/each}
						</tbody>
					</table>
					{#if links.length === 1 && links[0] && history}
						{@const series = linkHistory(history, links[0])}
						{#if series}
							<h3>Last 24 hours</h3>
							<TimeChart
								label="Load on the link over the last 24 hours, as seen from {history.device}"
								start={Date.parse(history.start)}
								step={history.step_s * 1000}
								series={[
									{ label: 'A→B', color: SERIES_COLOR[0], values: series.aToB },
									{ label: 'B→A', color: SERIES_COLOR[1], values: series.bToA }
								]}
								unit="%"
								max={100}
								levels={[80, 95]}
								strip={series.down.map((d) => (d ? DOWN : null))}
								at={replayed}
								onpick={replay}
							/>
						{/if}
					{:else if historyProblem}
						<p class="muted">History unavailable: {historyProblem}</p>
					{/if}
				{/if}
			</section>
		{/if}
	</aside>
{/if}

<style>
	.details {
		position: relative;
		flex: none;
		width: min(420px, 45vw);
		overflow-y: auto;
		background: var(--panel);
		border-left: 1px solid var(--border);
		padding: 14px 16px;
		font-size: 13px;
	}
	section {
		position: relative;
	}
	.path {
		margin: -14px -16px 14px;
		padding: 14px 16px;
		border-bottom: 1px solid var(--border);
		background: color-mix(in srgb, var(--path) 8%, var(--panel));
	}
	.impact {
		margin: -14px -16px 14px;
		padding: 14px 16px;
		border-bottom: 1px solid var(--border);
		background: color-mix(in srgb, var(--down) 8%, var(--panel));
	}
	.windows {
		margin: 4px 0;
		padding: 0;
		list-style: none;
	}
	.windows li {
		margin: 3px 0;
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
	.phase.open {
		border-color: var(--live);
		color: var(--text);
	}
	.phase.ack {
		border-color: var(--selected);
		color: var(--text);
	}
	.handled {
		margin: 6px 0;
	}
	.ack-form {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		margin: 8px 0 4px;
	}
	.ack-form input {
		flex: 1 1 120px;
		font: inherit;
		color: var(--text);
		background: var(--bg);
		border: 1px solid var(--border);
		border-radius: 4px;
		padding: 3px 6px;
	}
	.failures,
	.groups {
		margin: 6px 0;
		padding-left: 18px;
	}
	.failures li,
	.groups li {
		margin: 3px 0;
	}
	.remove {
		border: none;
		background: none;
		padding: 0 4px;
		color: var(--muted);
	}
	.names {
		display: flex;
		flex-wrap: wrap;
		gap: 2px 12px;
	}
	.hops {
		margin: 6px 0;
		padding-left: 22px;
	}
	.hops li {
		margin: 3px 0;
	}
	.hops .mono {
		color: var(--muted);
		margin-left: 6px;
	}
	.close {
		position: absolute;
		top: 8px;
		right: 8px;
		border: none;
		background: none;
		font-size: 20px;
		color: var(--muted);
		cursor: pointer;
	}
	h2 {
		margin: 0 24px 6px 0;
		font-size: 17px;
		word-break: break-all;
	}
	h3 {
		margin: 16px 0 6px;
		font-size: 13px;
		color: var(--muted);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}
	p {
		margin: 4px 0;
	}
	dl {
		display: grid;
		grid-template-columns: max-content 1fr;
		gap: 2px 12px;
		margin: 8px 0;
	}
	dt {
		color: var(--muted);
	}
	dd {
		margin: 0;
	}
	table {
		width: 100%;
		border-collapse: collapse;
	}
	th {
		text-align: left;
		color: var(--muted);
		font-weight: normal;
		border-bottom: 1px solid var(--border);
		padding: 3px 4px;
	}
	td {
		padding: 3px 4px;
		border-bottom: 1px solid var(--panel-2);
		vertical-align: top;
	}
	tbody tr:hover {
		background: var(--panel-2);
		cursor: pointer;
	}
	tr.sub td {
		color: var(--muted);
		font-size: 12px;
		padding-top: 0;
	}
	.link {
		border: none;
		background: none;
		padding: 0;
		color: var(--accent);
		cursor: pointer;
		text-align: left;
	}
	.link:hover {
		text-decoration: underline;
	}
	.mono {
		font-family: ui-monospace, 'Cascadia Mono', Menlo, monospace;
		font-size: 12px;
	}
	.muted {
		color: var(--muted);
	}
	.tag {
		font-size: 10px;
		padding: 0 4px;
		border-radius: 3px;
		background: var(--panel-2);
		border: 1px solid var(--border);
		color: var(--muted);
		margin-left: 4px;
	}
	.tag.wan {
		color: var(--accent);
		border-color: var(--accent);
	}
	.role {
		display: inline-block;
		padding: 1px 6px;
		border-radius: 10px;
		border: 1px solid var(--role);
		color: var(--role);
		font-size: 12px;
		margin-right: 4px;
	}
	.roles {
		margin: 8px 0;
	}
	.health {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		margin-right: 10px;
	}
	.health i {
		display: inline-grid;
		place-items: center;
		width: 14px;
		height: 14px;
		border-radius: 50%;
		background: var(--c);
		color: var(--bg);
		font-style: normal;
		font-size: 11px;
		font-weight: 700;
	}
	.health.hollow i {
		box-sizing: border-box;
		background: none;
		border: 1px solid var(--c);
	}
	.bar {
		display: inline-block;
		width: 8px;
		height: 8px;
		border-radius: 2px;
		margin-right: 5px;
	}
	.nowrap {
		white-space: nowrap;
	}
	.reach {
		margin: 6px 0 10px;
	}
	.actions {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		margin: 10px 0;
	}
	.actions button {
		white-space: nowrap;
	}
	.devices {
		columns: 2;
		list-style: none;
		padding: 0;
		margin: 6px 0;
	}
	.dot {
		display: inline-block;
		width: 8px;
		height: 8px;
		border-radius: 2px;
		background: var(--role);
		margin-right: 6px;
	}
	details {
		margin-top: 14px;
	}
	summary {
		cursor: pointer;
		color: var(--muted);
	}
</style>
