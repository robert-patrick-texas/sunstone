<!--
@component
The overrides on one object, whatever their state, each with Renew and
Withdraw, and making one there, or a rule like one. A device also lists
those on its ports, and offers to override one: one of its documented
interfaces, or one typed. Then the rules on the object: those that apply,
each with Not here to take the object out of it; those an override here, or
a newer rule, wins over; and those it is taken out of, with Apply here
again. A device has the rules on its ports among them.

The details views also take from here what overrides and rules add around
an object: its name in the topology under a new one, and whether it is
hidden from the map or from status (`overridden`); its other names, tags
beside its own, and labels (`facts`); and "Locked here", or by which rule,
by a field a lock keeps (`locked`).
-->
<script module lang="ts">
	import type { Target } from './api/overrides.ts';
	import type { Link } from './api/topology.ts';
	import { lagOf } from './connections.ts';
	import {
		aliases,
		hiddenFromMap,
		hiddenFromStatus,
		labelled,
		lagId,
		lockOf,
		on,
		tagged,
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
	 * @returns "Locked here · the topology says access", "Locked by rule Lab gear",
	 *   or null with no lock applying.
	 */
	function lockNote(of: Target, field: string, label?: string): string | null {
		const lock = lockOf(of, field);
		if (lock?.state !== 'active') return null;
		const by = lock.rule ? `by rule ${lock.rule.name}` : 'here';
		const head = label ? `${label} locked ${by}` : `Locked ${by}`;
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
	import {
		exceptFromRule,
		includeInRule,
		type OverrideKind,
		type OverrideNow,
		type RuleNow
	} from './api/overrides.ts';
	import { clock } from './history.ts';
	import OverrideForm from './OverrideForm.svelte';
	import OverrideItem from './OverrideItem.svelte';
	import {
		describeRule,
		onPorts,
		presetFrom,
		reloadOverrides,
		RULE_KINDS,
		rulesOn,
		targetKey,
		type RuleDraft
	} from './overrides.svelte.ts';
	import RuleForm from './RuleForm.svelte';
	import { rememberName, ui } from './state.svelte.ts';
	import { compareNatural, isDeviceEnd, shortInterface } from './topology.ts';

	const { of, index }: { of: Target; index: TopologyIndex } = $props();
	const uid = $props.id();

	/**
	 * The form open, by the key of what it was opened on, so it closes when the
	 * details show something else: on the object, choosing a port, on the port,
	 * or a rule like an override listed (`preset`). Replaced, never changed.
	 */
	let making = $state.raw<{
		on: string;
		step: 'object' | 'choose' | 'port' | 'rule';
		preset?: RuleDraft;
	} | null>(null);
	let iface = $state('');
	const step = $derived(making?.on === targetKey(of) ? making.step : null);

	const listed = $derived([...on(of), ...(of.kind === 'device' ? onPorts(of.id) : [])]);
	const ruled = $derived(rulesOn(of));
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

	/** Whether a rule can be made like an override: one of a kind rules have, applying now. */
	function likable(o: OverrideNow): boolean {
		return o.state === 'active' && (RULE_KINDS as readonly OverrideKind[]).includes(o.kind);
	}

	/** Open the rule form on a rule like an override listed here. */
	function likeThis(o: OverrideNow): void {
		making = { on: targetKey(of), step: 'rule', preset: presetFrom(o, index) };
	}

	/** What a rule does here; one on ports, on which of the device's. */
	function doesHere(r: RuleNow): string {
		if (r.match.of !== 'port') return describeRule(r);
		const ports = r.match.interface.map(shortInterface).join(', ');
		return r.kind === 'one-device' ? `One device on ${ports}` : `${describeRule(r)} on ${ports}`;
	}

	/** Show every rule, and every override, in the side panel. */
	function showRules(): void {
		ui.sideTab = 'overrides';
		ui.problemsOpen = true;
	}

	/**
	 * Why taking the object out of a rule, or putting it back, was refused, by
	 * the key of the object; `name` when it was for want of a name, to ask for one.
	 */
	let refused = $state<{ on: string; text: string; name: boolean } | null>(null);
	const refusal = $derived(refused?.on === targetKey(of) ? refused : null);
	let busy = $state(false);

	/** Take the object out of a rule, or put it back, signed by who is using Sunstone. */
	async function stand(change: (by: string) => Promise<unknown>): Promise<void> {
		const on = targetKey(of);
		const by = ui.person.trim();
		if (!by) {
			refused = { on, text: 'Give your name first', name: true };
			return;
		}
		rememberName(by);
		busy = true;
		refused = null;
		try {
			await change(by);
			await reloadOverrides();
		} catch (err) {
			refused = { on, text: err instanceof Error ? err.message : String(err), name: false };
		} finally {
			busy = false;
		}
	}

	function choose(e: SubmitEvent): void {
		e.preventDefault();
		if (iface.trim()) start('port');
	}
</script>

{#snippet overridden(of: Target)}
	{@const name = topologyName(of)}
	{@const map = hiddenFromMap(of)}
	{@const status = hiddenFromStatus(of)}
	{#if name}<p class="renamed">{name} in the topology</p>{/if}
	{#if map}
		<p class="note">
			Hidden from the map <span class="muted"
				>{map.rule ? `· by rule ${map.rule.name} ` : ''}· still found by search</span
			>
		</p>
	{/if}
	{#if status}
		<p class="note">
			Hidden from status <span class="muted"
				>{status.rule ? `· by rule ${status.rule.name} ` : ''}· counts toward no status and raises
				no problem</span
			>
		</p>
	{/if}
{/snippet}

{#snippet facts(of: Target, own: readonly string[] = [])}
	{@const others = aliases(of).filter((a) => a !== renameOf(of)?.value)}
	{@const added = tagged(of)}
	{@const given = labelled(of)}
	{#if others.length || own.length || added.length || given.length}
		<dl class="facts">
			{#if others.length}<dt>Also known as</dt>
				<dd>{others.join(', ')}</dd>{/if}
			{#if own.length || added.length}<dt>Tags</dt>
				<dd>
					{own.join(', ')}{#each added as t, i (t.value)}{own.length || i ? ', ' : ''}{t.value}
						<span class="muted">({t.rule ? `rule ${t.rule.name}` : 'added here'})</span>{/each}
				</dd>{/if}
			{#each given as l (l.key)}<dt
					title={l.rule ? `From rule ${l.rule.name}` : 'A label given here'}
				>
					{l.key}
				</dt>
				<dd>{l.value}</dd>{/each}
		</dl>
	{/if}
{/snippet}

{#snippet locked(of: Target, field: string, label?: string)}
	{@const note = lockNote(of, field, label)}
	{#if note}<span class="locked">· {note}</span>{/if}
{/snippet}

{#snippet ruleLink(rule: RuleNow)}
	<button type="button" class="link" title="Show the rules in the Overrides tab" onclick={showRules}
		><b>{rule.name}</b></button
	>
{/snippet}

<h3>Overrides{listed.length ? ` (${listed.length})` : ''}</h3>
{#each listed as o (o.id)}
	<OverrideItem
		{o}
		{index}
		withTarget={o.target.kind === 'port'}
		onrule={likable(o) ? likeThis : undefined}
	/>
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
{:else if step === 'rule'}
	<!-- Made afresh for each override it is like. -->
	{#key making}
		<RuleForm {index} preset={making?.preset} onmade={close} oncancel={close} />
	{/key}
{:else}
	<p class="actions">
		<button onclick={() => start('object')}>Override…</button>
		{#if of.kind === 'device'}
			<button onclick={() => start('choose')}>Override a port…</button>
		{/if}
	</p>
{/if}
{#if ruled.length}
	<h3>Rules ({ruled.length})</h3>
	{#each ruled as r (r.rule.id)}
		{@const out = r.excepted}
		<p class="rule" class:muted={r.how === 'overridden'}>
			{#if out}
				Rule {@render ruleLink(r.rule)} does not apply here
				<span class="muted">· taken out by {out.by}, {clock(out.at)}</span>
				<button
					type="button"
					disabled={busy}
					aria-label="Apply here again: {r.rule.name}"
					onclick={() => stand((by) => includeInRule(r.rule.id, of, by))}>Apply here again</button
				>
			{:else}
				From rule {@render ruleLink(r.rule)}: {doesHere(r.rule)}{r.how === 'overridden'
					? '; overridden here'
					: ''}
				{#if r.how === 'applies'}
					<button
						type="button"
						disabled={busy}
						aria-label="Not here: {r.rule.name}"
						onclick={() => stand((by) => exceptFromRule(r.rule.id, of, by))}>Not here</button
					>
				{/if}
			{/if}
		</p>
	{/each}
	{#if refusal}
		<p class="error" role="alert">{refusal.text}</p>
		{#if refusal.name}
			<label>
				Your name
				<input bind:value={ui.person} maxlength="64" autocomplete="name" />
			</label>
		{/if}
	{/if}
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
	.rule button {
		margin-left: 4px;
		white-space: nowrap;
	}
	.rule .link {
		margin: 0;
		border: none;
		background: none;
		padding: 0;
		font: inherit;
		color: var(--accent);
		cursor: pointer;
	}
	.rule .link:hover {
		text-decoration: underline;
	}
	.error {
		color: var(--down);
		font-size: 12px;
	}
</style>
