<!--
@component
One search for everything: devices, sites, and links (by circuit, carrier,
or interface), management addresses and address ranges, problems,
maintenance windows, and commands. Before anything is typed it offers what
was looked at recently. Choosing a result selects it and brings it into
view in whichever view is open; a problem shows its impact, a window opens
the maintenance list on what it works on, and a command runs. The arrow keys
move through the results, Enter chooses, Escape closes. Press `/` or Ctrl+K
to get here.
-->
<script lang="ts">
	import { onMount } from 'svelte';
	import type { Problem } from './api/analysis.ts';
	import type { Window } from './api/operations.ts';
	import type { Command, CommandId } from './commands.ts';
	import { deviceHealth, type LiveIndex } from './live.ts';
	import { timed } from './perf.ts';
	import { MARK } from './problem-kinds.ts';
	import {
		commandEntries,
		problemEntries,
		recentEntries,
		search,
		topologyEntries,
		windowEntries,
		type Entry
	} from './search.ts';
	import { select, showProblem, ui, type Selection } from './state.svelte.ts';
	import { HEALTH_COLOR, HEALTH_GLYPH } from './theme.ts';
	import type { TopologyIndex } from './topology.ts';

	const {
		index,
		live,
		problems,
		windows,
		recent,
		commands,
		oncommand,
		onforget
	}: {
		index: TopologyIndex;
		live: LiveIndex | null;
		problems: Problem[];
		windows: Window[];
		/** What was looked at recently, newest first, as links write it. */
		recent: string[];
		/** The commands that can run now. */
		commands: Command[];
		oncommand: (id: CommandId) => void;
		/** Forget what was looked at recently. */
		onforget: () => void;
	} = $props();

	interface Shown {
		label: string;
		entries: Entry[];
		more: number;
		recent?: boolean;
	}

	let input: HTMLInputElement;
	let query = $state('');
	let open = $state(false);
	let active = $state(0);

	// The topology never changes while the page is open, so its entries are
	// built once: when the browser is next idle, or at the first search if sooner.
	let built: Entry[] | null = null;
	function items(): Entry[] {
		built ??= timed('search index', () => topologyEntries(index));
		return built;
	}

	onMount(() => {
		if ('requestIdleCallback' in window) {
			const id = requestIdleCallback(() => void items(), { timeout: 5000 });
			return () => cancelIdleCallback(id);
		}
		const timer = setTimeout(() => void items(), 2000);
		return () => clearTimeout(timer);
	});
	const problemList = $derived(problemEntries(index, problems));
	const windowList = $derived(windowEntries(index, windows));
	const commandList = $derived(commandEntries(commands));
	const groups: Shown[] = $derived.by(() => {
		if (!query.trim()) {
			const entries = recentEntries(index, recent);
			return entries.length ? [{ label: 'Recent', entries, more: 0, recent: true }] : [];
		}
		const lists = [problemList, items(), windowList, commandList];
		return timed('search', () => search(query, lists));
	});
	const flat = $derived(groups.flatMap((g) => g.entries));
	const expanded = $derived(open && flat.length > 0);

	/** Put the cursor in the search box. */
	export function focus(): void {
		input.focus();
		input.select();
	}

	function close(): void {
		query = '';
		input.blur();
	}

	/** One selection for all a window works on when it is all links, else the first thing. */
	function windowTarget(targets: Selection[]): Selection | null {
		const ids = targets.flatMap((t) => (t.kind === 'links' ? t.ids : []));
		return targets.every((t) => t.kind === 'links') && ids.length
			? { kind: 'links', ids }
			: (targets[0] ?? null);
	}

	function choose(entry: Entry | undefined): void {
		if (!entry) return;
		close();
		const target = entry.target;
		if (target.kind === 'command') {
			oncommand(target.command);
		} else if (target.kind === 'item') {
			select(target.item, true);
		} else if (target.kind === 'problem') {
			ui.sideTab = 'problems';
			ui.problemsOpen = true;
			if (ui.problem === target.problem.id) select(target.problem.target, true);
			else showProblem(target.problem);
		} else {
			ui.sideTab = 'maintenance';
			ui.problemsOpen = true;
			select(windowTarget(target.window.targets), true);
		}
	}

	function onKeydown(e: KeyboardEvent): void {
		const count = flat.length;
		if (e.key === 'ArrowDown' && count) active = (active + 1) % count;
		else if (e.key === 'ArrowUp' && count) active = (active - 1 + count) % count;
		else if (e.key === 'Enter') choose(flat[active]);
		else if (e.key === 'Escape') close();
		else return;
		e.preventDefault();
	}

	/** A device's health, as a mark, when live state is on. */
	function mark(entry: Entry): { color: string; glyph: string; hollow: boolean } | null {
		const target = entry.target;
		if (target.kind === 'problem') return { ...MARK[target.problem.kind], hollow: false };
		if (!live || target.kind !== 'item' || target.item.kind !== 'device') return null;
		const health = deviceHealth(live, target.item.id);
		return {
			color: HEALTH_COLOR[health],
			glyph: HEALTH_GLYPH[health],
			hollow: health === 'unmonitored'
		};
	}

	function keysOf(entry: Entry): string[] {
		const target = entry.target;
		if (target.kind !== 'command') return [];
		return commands.find((c) => c.id === target.command)?.keys ?? [];
	}
</script>

<div class="search">
	<input
		bind:this={input}
		bind:value={query}
		oninput={() => (active = 0)}
		onkeydown={onKeydown}
		onfocus={() => {
			open = true;
			active = 0;
		}}
		onblur={() => (open = false)}
		type="text"
		role="combobox"
		autocomplete="off"
		spellcheck="false"
		aria-label="Search"
		aria-autocomplete="list"
		aria-expanded={expanded}
		aria-controls="search-results"
		aria-activedescendant={expanded ? `search-${active}` : undefined}
		placeholder="Search everything  ( / )"
	/>
	{#if open}
		<div class="results">
			{#if expanded}
				<ul id="search-results" role="listbox" aria-label="Search results">
					{#each groups as group, g (group.label)}
						{@const offset = groups.slice(0, g).reduce((n, x) => n + x.entries.length, 0)}
						<li class="heading" role="presentation">
							<span>{group.label}</span>
							{#if group.recent}
								<button
									class="forget"
									tabindex="-1"
									onmousedown={(e) => e.preventDefault()}
									onclick={onforget}>Clear</button
								>
							{/if}
						</li>
						{#each group.entries as entry, i (entry.kind + entry.key)}
							{@const n = offset + i}
							{@const m = mark(entry)}
							<li id="search-{n}" role="option" aria-selected={n === active}>
								<button
									tabindex="-1"
									onmousedown={(e) => e.preventDefault()}
									onmousemove={() => (active = n)}
									onclick={() => choose(entry)}
								>
									<span class="mark">
										{#if m}<i class:hollow={m.hollow} style:--c={m.color} aria-hidden="true"
												>{m.glyph}</i
											>{/if}
									</span>
									<span class="text">
										<span class="label">{entry.label}</span>
										{#if entry.detail && entry.kind !== 'command'}
											<span class="detail">{entry.detail}</span>
										{/if}
									</span>
									{#each keysOf(entry) as k (k)}<kbd>{k}</kbd>{/each}
								</button>
							</li>
						{/each}
						{#if group.more}
							<li class="more" role="presentation">
								{group.more} more {group.label.toLowerCase()}: add words to narrow
							</li>
						{/if}
					{/each}
				</ul>
			{:else if query.trim()}
				<p class="hint">
					Nothing matches “{query.trim()}”. Search by name, management address or range
					(10.1.0.0/16), circuit, interface, problem, or command.
				</p>
			{:else}
				<p class="hint">Type a device, site, address, circuit, interface, problem, or command.</p>
			{/if}
			<p class="keys">
				<kbd>↑</kbd><kbd>↓</kbd> move · <kbd>Enter</kbd> open · <kbd>Esc</kbd> close ·
				<kbd>?</kbd> all shortcuts
			</p>
		</div>
	{/if}
</div>

<style>
	/* In the header, it narrows before anything wraps, and takes spare room first. */
	.search {
		position: relative;
		flex: 100 1 200px;
		min-width: 170px;
		max-width: 340px;
	}
	input {
		width: 100%;
		box-sizing: border-box;
		padding: 6px 10px;
		border-radius: 6px;
		border: 1px solid var(--border);
		background: var(--bg);
		color: var(--text);
		font: inherit;
	}
	.results {
		position: absolute;
		top: calc(100% + 4px);
		left: 0;
		z-index: 30;
		width: max(100%, min(460px, 90vw));
		max-height: 70vh;
		overflow-y: auto;
		background: var(--panel);
		border: 1px solid var(--border);
		border-radius: 6px;
		box-shadow: 0 8px 24px rgb(0 0 0 / 0.4);
	}
	ul {
		margin: 0;
		padding: 4px 0;
		list-style: none;
	}
	.heading {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: 8px 10px 2px;
		color: var(--muted);
		font-size: 11px;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}
	.forget {
		border: none;
		background: none;
		padding: 0;
		color: var(--accent);
		font-size: 11px;
		text-transform: none;
		letter-spacing: normal;
	}
	[role='option'] button {
		display: flex;
		align-items: center;
		gap: 8px;
		width: 100%;
		padding: 4px 10px;
		border: none;
		border-radius: 0;
		background: none;
		text-align: left;
	}
	[aria-selected='true'] button {
		background: var(--panel-2);
		box-shadow: inset 2px 0 var(--live);
	}
	.mark {
		flex: none;
		width: 16px;
	}
	i {
		display: grid;
		place-items: center;
		width: 14px;
		height: 14px;
		border-radius: 50%;
		background: var(--c);
		color: var(--bg);
		font-style: normal;
		font-size: 10px;
		font-weight: 700;
	}
	i.hollow {
		background: none;
		box-shadow: inset 0 0 0 1.5px var(--c);
	}
	.text {
		display: flex;
		flex-direction: column;
		flex: 1;
		min-width: 0;
	}
	.label,
	.detail {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.detail {
		color: var(--muted);
		font-size: 12px;
	}
	.more {
		padding: 2px 10px 4px 34px;
		color: var(--muted);
		font-size: 12px;
	}
	.hint {
		margin: 0;
		padding: 10px;
		color: var(--muted);
	}
	.keys {
		margin: 0;
		padding: 6px 10px;
		border-top: 1px solid var(--border);
		color: var(--muted);
		font-size: 12px;
	}
</style>
