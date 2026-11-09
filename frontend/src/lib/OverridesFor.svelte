<!--
@component
The overrides on one object, whatever their state, each with Renew and
Withdraw, and making one there. A device also lists those on its ports, and
offers to override one: one of its documented interfaces, or one typed.

The details views also take from here what overrides add around an object:
its name in the topology under a new one, and whether it is hidden from the
map or from status (`overridden`); its other names, tags beside its own, and
labels (`facts`); and "Locked here" by a field a lock keeps (`locked`).
-->
<script module lang="ts">
	import type { Target } from './api/overrides.ts';
	import type { Link } from './api/topology.ts';
	import { lagOf } from './connections.ts';
	import {
		aliases,
		hiddenFromStatus,
		labels,
		lagId,
		lockOf,
		on,
		tags,
		target
	} from './overrides.svelte.ts';
	import { deviceEnds, siteOf, type TopologyIndex } from './topology.ts';

	export { facts, locked, overridden };

	/** The rename that applies now on a target, if any. */
	function renameOf(of: Target) {
		return on(of).find((o) => o.kind === 'rename' && o.state === 'active');
	}

	/**
	 * A renamed object's name in the topology.
	 *
	 * @param of - A site, device, or external node.
	 * @returns A device's or external node's key, or a site's name before the
	 *   rename; null when it is not renamed here.
	 */
	export function topologyName(of: Target): string | null {
		const rename = renameOf(of);
		if (!rename) return null;
		return of.kind === 'site' ? (rename.topology_value ?? null) : of.id;
	}

	/**
	 * What a lock that applies says by the field it keeps.
	 *
	 * @param of - The object.
	 * @param field - The field.
	 * @param label - The field's name, where the line it is on does not say.
	 * @returns "Locked here · the topology says access", or null with no lock applying.
	 */
	function lockNote(of: Target, field: string, label?: string): string | null {
		const lock = lockOf(of, field);
		if (lock?.state !== 'active') return null;
		const head = label ? `${label} locked here` : 'Locked here';
		const says = lock.topology_value;
		if (says === null || says === undefined) return head;
		return `${head} · the topology says ${says === '' ? 'nothing' : says}`;
	}

	/**
	 * Whether a device counts toward no status by an override here.
	 *
	 * @param index - The topology, for the device's site.
	 * @param device - The device's name.
	 * @returns True when it, or its site, is hidden from status.
	 */
	export function deviceHidden(index: TopologyIndex, device: string): boolean {
		return [target('device', device), target('site', siteOf(index, device))].some((t) =>
			hiddenFromStatus(t)
		);
	}

	/**
	 * Whether a link counts toward no status by an override here.
	 *
	 * @param index - The topology.
	 * @param link - The link.
	 * @returns True when it, its port channel, a device of it or that device's
	 *   site, or its far end is hidden from status.
	 */
	export function linkHidden(index: TopologyIndex, link: Link): boolean {
		const lag = lagOf(index.topology, link);
		const b = link.b;
		return (
			hiddenFromStatus(target('link', link.id)) !== undefined ||
			(lag !== null && hiddenFromStatus(target('lag', lagId(lag))) !== undefined) ||
			deviceEnds(link).some((e) => deviceHidden(index, e.device)) ||
			('external' in b && hiddenFromStatus(target('external', b.external)) !== undefined)
		);
	}
</script>

<script lang="ts">
	import OverrideForm from './OverrideForm.svelte';
	import OverrideItem from './OverrideItem.svelte';
	import { onPorts, targetKey } from './overrides.svelte.ts';
	import { compareNatural, isDeviceEnd } from './topology.ts';

	const { of, index }: { of: Target; index: TopologyIndex } = $props();
	const uid = $props.id();

	/**
	 * The form open, by the key of what it was opened on, so it closes when the
	 * details show something else: on the object, choosing a port, or on the port.
	 */
	let making = $state<{ on: string; step: 'object' | 'choose' | 'port' } | null>(null);
	let iface = $state('');
	const step = $derived(making?.on === targetKey(of) ? making.step : null);

	const listed = $derived([...on(of), ...(of.kind === 'device' ? onPorts(of.id) : [])]);
	const ports = $derived(of.kind === 'device' ? portsOf(of.id) : []);
	const port = $derived(target('port', of.id, iface.trim()));

	/** A device's documented interfaces: those its links have. */
	function portsOf(device: string): string[] {
		const ends = (index.linksByDevice.get(device) ?? []).flatMap((l) => [l.a, l.b]);
		const names = ends.flatMap((e) => (isDeviceEnd(e) && e.device === device ? [e.interface] : []));
		return [...new Set(names)].sort(compareNatural);
	}

	function start(next: 'object' | 'choose' | 'port'): void {
		if (next === 'choose') iface = '';
		making = { on: targetKey(of), step: next };
	}

	function close(): void {
		making = null;
	}

	function choose(e: SubmitEvent): void {
		e.preventDefault();
		if (iface.trim()) start('port');
	}
</script>

{#snippet overridden(of: Target)}
	{@const name = topologyName(of)}
	{#if name}<p class="renamed">{name} in the topology</p>{/if}
	{#if on(of).some((o) => o.kind === 'hide-map' && o.state === 'active')}
		<p class="note">Hidden from the map <span class="muted">· still found by search</span></p>
	{/if}
	{#if hiddenFromStatus(of)}
		<p class="note">
			Hidden from status <span class="muted">· counts toward no status and raises no problem</span>
		</p>
	{/if}
{/snippet}

{#snippet facts(of: Target, own: readonly string[] = [])}
	{@const others = aliases(of).filter((a) => a !== renameOf(of)?.value)}
	{@const added = tags(of)}
	{@const given = labels(of)}
	{#if others.length || own.length || added.length || given.length}
		<dl class="facts">
			{#if others.length}<dt>Also known as</dt>
				<dd>{others.join(', ')}</dd>{/if}
			{#if own.length || added.length}<dt>Tags</dt>
				<dd>
					{own.join(', ')}{#each added as t, i (t)}{own.length || i ? ', ' : ''}{t}
						<span class="muted">(added here)</span>{/each}
				</dd>{/if}
			{#each given as l (l.key)}<dt title="A label given here">{l.key}</dt>
				<dd>{l.value}</dd>{/each}
		</dl>
	{/if}
{/snippet}

{#snippet locked(of: Target, field: string, label?: string)}
	{@const note = lockNote(of, field, label)}
	{#if note}<span class="locked">· {note}</span>{/if}
{/snippet}

<h3>Overrides{listed.length ? ` (${listed.length})` : ''}</h3>
{#each listed as o (o.id)}
	<OverrideItem {o} {index} withTarget={o.target.kind === 'port'} />
{/each}
{#if step === 'object'}
	<OverrideForm {of} {index} onmade={close} oncancel={close} />
{:else if step === 'choose'}
	<form class="port" aria-label="Choose a port" onsubmit={choose}>
		<label>
			Port
			<input
				bind:value={iface}
				list="{uid}-ports"
				required
				maxlength="200"
				placeholder="One of its interfaces, or type one"
			/>
		</label>
		<datalist id="{uid}-ports">
			{#each ports as p (p)}<option value={p}></option>{/each}
		</datalist>
		<p class="actions">
			<button type="submit">Next</button>
			<button type="button" onclick={close}>Cancel</button>
		</p>
	</form>
{:else if step === 'port'}
	<OverrideForm of={port} {index} onmade={close} oncancel={close} />
{:else}
	<p class="actions">
		<button onclick={() => start('object')}>Override…</button>
		{#if of.kind === 'device'}
			<button onclick={() => start('choose')}>Override a port…</button>
		{/if}
	</p>
{/if}

<style>
	/* As the details panel's own headings, lists, and notes. */
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
		overflow-wrap: anywhere;
	}
	.muted,
	.renamed {
		color: var(--muted);
	}
	.locked {
		color: var(--accent);
		font-size: 12px;
	}
	.note {
		padding-left: 8px;
		border-left: 3px solid var(--accent);
	}
	.port {
		display: flex;
		flex-direction: column;
		gap: 8px;
		margin: 4px 0;
	}
	label {
		display: flex;
		flex-direction: column;
		gap: 2px;
		color: var(--muted);
		font-size: 12px;
	}
	input {
		font: inherit;
		font-size: 13px;
		color: var(--text);
		background: var(--bg);
		border: 1px solid var(--border);
		border-radius: 4px;
		padding: 4px 6px;
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
</style>
