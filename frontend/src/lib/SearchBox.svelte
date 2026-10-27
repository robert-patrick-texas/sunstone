<!--
@component
Find a site or device by name, code, or management address. Choosing a
result selects it and brings it into view. Press `/` to jump here.
-->
<script lang="ts">
	import { select } from './state.svelte.ts';
	import type { TopologyIndex } from './topology.ts';

	const { index }: { index: TopologyIndex } = $props();

	const MAX_RESULTS = 12;

	interface Result {
		kind: 'site' | 'device';
		id: string;
		label: string;
		hint: string;
	}

	let input: HTMLInputElement;
	let query = $state('');
	let active = $state(0);
	const results = $derived(search(query));

	function search(text: string): Result[] {
		const q = text.trim().toLowerCase();
		if (!q) return [];
		const sites: Result[] = index.topology.sites
			.filter((s) => s.code.toLowerCase().includes(q) || s.name.toLowerCase().includes(q))
			.map((s) => ({ kind: 'site', id: s.code, label: `${s.code} · ${s.name}`, hint: 'site' }));
		const devices: Result[] = [];
		for (const d of index.topology.devices) {
			if (sites.length + devices.length >= MAX_RESULTS) break;
			if (d.name.toLowerCase().includes(q) || d.mgmt_ip?.startsWith(q)) {
				devices.push({ kind: 'device', id: d.name, label: d.name, hint: d.mgmt_ip ?? d.site });
			}
		}
		return [...sites, ...devices].slice(0, MAX_RESULTS);
	}

	function choose(result: Result | undefined): void {
		if (!result) return;
		select({ kind: result.kind, id: result.id }, true);
		query = '';
		input.blur();
	}

	function onKeydown(e: KeyboardEvent): void {
		if (e.key === 'ArrowDown') active = Math.min(active + 1, results.length - 1);
		else if (e.key === 'ArrowUp') active = Math.max(active - 1, 0);
		else if (e.key === 'Enter') choose(results[active]);
		else if (e.key === 'Escape') {
			query = '';
			input.blur();
		} else return;
		e.preventDefault();
	}

	function onWindowKeydown(e: KeyboardEvent): void {
		if (e.key === '/' && !(e.target instanceof HTMLInputElement)) {
			e.preventDefault();
			input.focus();
		}
	}
</script>

<svelte:window onkeydown={onWindowKeydown} />

<div class="search">
	<input
		bind:this={input}
		bind:value={query}
		oninput={() => (active = 0)}
		onkeydown={onKeydown}
		type="search"
		placeholder="Search sites and devices  ( / )"
		aria-label="Search sites and devices"
	/>
	{#if results.length}
		<ul role="listbox">
			{#each results as r, i (r.kind + r.id)}
				<li role="option" aria-selected={i === active}>
					<button onmousedown={(e) => e.preventDefault()} onclick={() => choose(r)}>
						<span>{r.label}</span><span class="hint">{r.hint}</span>
					</button>
				</li>
			{/each}
		</ul>
	{/if}
</div>

<style>
	.search {
		position: relative;
		width: min(360px, 40vw);
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
	ul {
		position: absolute;
		top: calc(100% + 4px);
		left: 0;
		right: 0;
		z-index: 10;
		margin: 0;
		padding: 4px 0;
		list-style: none;
		background: var(--panel);
		border: 1px solid var(--border);
		border-radius: 6px;
		box-shadow: 0 8px 24px rgb(0 0 0 / 0.4);
	}
	button {
		display: flex;
		justify-content: space-between;
		gap: 12px;
		width: 100%;
		padding: 5px 10px;
		border: none;
		background: none;
		text-align: left;
		cursor: pointer;
	}
	[aria-selected='true'] button,
	button:hover {
		background: var(--panel-2);
	}
	.hint {
		color: var(--muted);
		font-size: 12px;
	}
</style>
