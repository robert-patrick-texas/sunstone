<!--
@component
Making an override on one object or port: its kind, the field or key and
value it needs, a note, who makes it, and until when. Making one shares it
with everyone; one of a kind an object has one of at a time (a rename, a
lock of a field, a label of a key) takes the place of the one there.
-->
<script lang="ts">
	import { makeOverride, type Override, type OverrideKind, type Target } from './api/overrides.ts';
	import {
		APPLIES_TO,
		CHOICES,
		FIELD_LABEL,
		KIND_CHOICES,
		KIND_LABEL,
		LOCKABLE,
		fieldValue,
		reloadOverrides,
		targetName
	} from './overrides.svelte.ts';
	import { rememberName, ui } from './state.svelte.ts';
	import type { TopologyIndex } from './topology.ts';

	const {
		of,
		index,
		kinds,
		preset,
		onmade,
		oncancel
	}: {
		/** What the override is on. */
		of: Target;
		index: TopologyIndex;
		/** The kinds to offer; every kind the target can have when left out. */
		kinds?: readonly OverrideKind[];
		/** A kind, key, and value to start from, as a discovery finding suggests. */
		preset?: { kind: OverrideKind; key?: string; value?: string };
		/** Called with the override once made and the list fetched again. */
		onmade?: (made: Override) => void;
		oncancel: () => void;
	} = $props();

	/** How long an override lasts, by the menu's choice; `until` takes a time. */
	const LASTS: { id: string; label: string; hours: number | null }[] = [
		{ id: 'never', label: 'Until withdrawn', hours: null },
		{ id: '1h', label: '1 hour', hours: 1 },
		{ id: '8h', label: '8 hours', hours: 8 },
		{ id: '24h', label: '24 hours', hours: 24 },
		{ id: '7d', label: '7 days', hours: 24 * 7 },
		{ id: 'until', label: 'Until…', hours: null }
	];

	const offered = $derived(
		(Object.keys(APPLIES_TO) as OverrideKind[]).filter(
			(k) => APPLIES_TO[k].includes(of.kind) && (!kinds || kinds.includes(k))
		)
	);
	// The form starts from the preset, if any; the target does not change while it is open.
	// svelte-ignore state_referenced_locally
	let kind = $state<OverrideKind>(preset?.kind ?? offered[0] ?? 'tag');
	// svelte-ignore state_referenced_locally
	let key = $state(preset?.key ?? '');
	// svelte-ignore state_referenced_locally
	let value = $state(preset?.value ?? '');
	let note = $state('');
	let lasts = $state('never');
	let until = $state('');
	let saving = $state(false);
	let problem = $state<string | null>(null);

	const fields = $derived(of.kind === 'port' ? [] : LOCKABLE[of.kind]);
	const choices = $derived(
		kind !== 'lock'
			? null
			: key === 'kind'
				? (KIND_CHOICES[of.kind] ?? null)
				: (CHOICES[key] ?? null)
	);
	const sites = $derived([...index.sites.keys()]);
	const needsKey = $derived(kind === 'label' || kind === 'lock');
	const needsValue = $derived(kind !== 'hide-map' && kind !== 'hide-status');
	const valueLabel = $derived(
		kind === 'rename'
			? 'New name'
			: kind === 'alias'
				? 'Other name'
				: kind === 'one-device'
					? 'The device it is'
					: kind === 'ignore-neighbor'
						? 'Neighbor to ignore, as reported'
						: 'Value'
	);

	/** Start a lock from the field's value now, so locking it as it is is one click. */
	function chooseField(field: string): void {
		key = field;
		value = fieldValue(index, of, field);
	}

	function expires(): string | null {
		if (lasts === 'until') return until ? new Date(until).toISOString() : null;
		const hours = LASTS.find((l) => l.id === lasts)?.hours;
		return hours ? new Date(Date.now() + hours * 3_600_000).toISOString() : null;
	}

	async function save(e: SubmitEvent): Promise<void> {
		e.preventDefault();
		rememberName(ui.person.trim());
		saving = true;
		problem = null;
		try {
			const made = await makeOverride({
				target: $state.snapshot(of),
				kind,
				key: needsKey ? key.trim() : null,
				value: needsValue ? value.trim() : null,
				note,
				by: ui.person,
				expires: expires()
			});
			await reloadOverrides();
			onmade?.(made);
		} catch (err) {
			problem = err instanceof Error ? err.message : String(err);
		} finally {
			saving = false;
		}
	}
</script>

<form onsubmit={save} aria-label="Override {targetName(of, index)}">
	<h3>Override {targetName(of, index)}</h3>
	<label>
		Kind
		<select bind:value={kind} disabled={offered.length < 2} aria-label="Kind">
			{#each offered as k (k)}
				<option value={k}>{KIND_LABEL[k]}</option>
			{/each}
		</select>
	</label>
	{#if kind === 'lock'}
		<label>
			Field
			<select
				value={key}
				onchange={(e) => chooseField(e.currentTarget.value)}
				required
				aria-label="Field"
			>
				<option value="" disabled>Choose a field</option>
				{#each fields as f (f)}
					<option value={f}>{FIELD_LABEL[f] ?? f}</option>
				{/each}
			</select>
		</label>
	{:else if kind === 'label'}
		<label>
			Key
			<input bind:value={key} required maxlength="200" placeholder="rack" />
		</label>
	{/if}
	{#if needsValue}
		<label>
			{valueLabel}
			{#if kind === 'lock' && key === 'site'}
				<select bind:value required aria-label={valueLabel}>
					{#each sites as s (s)}
						<option value={s}>{s}</option>
					{/each}
				</select>
			{:else if choices}
				<select bind:value required aria-label={valueLabel}>
					{#each choices as c (c)}
						<option value={c}>{c}</option>
					{/each}
				</select>
			{:else}
				<input bind:value required maxlength="200" />
			{/if}
		</label>
	{/if}
	<label>
		Note
		<textarea bind:value={note} rows="2" maxlength="1000" placeholder="Why, and who asked"
		></textarea>
	</label>
	<label>
		Lasts
		<select bind:value={lasts} aria-label="Lasts">
			{#each LASTS as l (l.id)}
				<option value={l.id}>{l.label}</option>
			{/each}
		</select>
	</label>
	{#if lasts === 'until'}
		<label>Until <input type="datetime-local" bind:value={until} required /></label>
	{/if}
	<label>
		Your name
		<input bind:value={ui.person} required maxlength="64" autocomplete="name" />
	</label>
	{#if problem}<p class="error" role="alert">Could not override: {problem}</p>{/if}
	<p class="actions">
		<button type="submit" disabled={saving}>Override</button>
		<button type="button" onclick={oncancel}>Cancel</button>
	</p>
</form>

<style>
	form {
		display: flex;
		flex-direction: column;
		gap: 8px;
		margin: 4px 0;
	}
	h3 {
		margin: 0;
		font-size: 13px;
	}
	label {
		display: flex;
		flex-direction: column;
		gap: 2px;
		color: var(--muted);
		font-size: 12px;
	}
	input,
	select,
	textarea {
		font: inherit;
		font-size: 13px;
		color: var(--text);
		background: var(--bg);
		border: 1px solid var(--border);
		border-radius: 4px;
		padding: 4px 6px;
	}
	.error {
		margin: 0;
		color: var(--down);
		font-size: 12px;
	}
	.actions {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		margin: 0;
	}
</style>
