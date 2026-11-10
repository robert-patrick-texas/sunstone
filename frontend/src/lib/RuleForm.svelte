<!--
@component
Making a rule: an override on everything that matches. Its name, what it
matches (a kind of object and tests), what it does (a kind, key, and value),
a note, who makes it, and until when; with a live preview of what it would
apply on, what wins over it there, and for a rule on ports, the discovery
findings it would set aside and raise.

The contract other components use: `index`, `preset`, `onmade`, `oncancel`.
-->
<script lang="ts">
	import {
		makeRule,
		previewRule,
		type Match,
		type Rule,
		type RuleKind,
		type RulePreview,
		type TargetKind
	} from './api/overrides.ts';
	import {
		CHOICES,
		FIELD_LABEL,
		KIND_CHOICES,
		LOCKABLE,
		NOUNS,
		RULE_APPLIES,
		RULE_KINDS,
		RULE_KIND_LABEL,
		RULE_UNVALUED,
		TESTS,
		TEST_FIELDS,
		TEST_LABEL,
		emptyMatch,
		named,
		overrides,
		reloadOverrides,
		ruleName,
		targetName,
		type RuleDraft,
		type TestField
	} from './overrides.svelte.ts';
	import { counted, missing, offered, patternText, patterns, suggestions } from './ruleForm.ts';
	import { rememberName, ui } from './state.svelte.ts';
	import type { TopologyIndex } from './topology.ts';

	const {
		index,
		preset,
		onmade,
		oncancel
	}: {
		index: TopologyIndex;
		/** A rule to start from: one like an override ("Make a rule like this…"), or one discovery offers. */
		preset?: RuleDraft;
		/** Called with the rule once made and the list fetched again. */
		onmade?: (made: Rule) => void;
		oncancel: () => void;
	} = $props();
	const uid = $props.id();

	/** How long a rule lasts, by the menu's choice; `until` takes a time. */
	const LASTS: { id: string; label: string; hours: number | null }[] = [
		{ id: 'never', label: 'Until withdrawn', hours: null },
		{ id: '1h', label: '1 hour', hours: 1 },
		{ id: '8h', label: '8 hours', hours: 8 },
		{ id: '24h', label: '24 hours', hours: 24 },
		{ id: '7d', label: '7 days', hours: 24 * 7 },
		{ id: 'until', label: 'Until…', hours: null }
	];
	/** Every kind of object a rule can be on. */
	const OBJECTS = Object.keys(TESTS) as TargetKind[];
	/** How many of what it would apply on the preview names. */
	const NAMED = 5;
	/** How long typing settles before the preview asks again. */
	const SETTLE_MS = 300;

	// The form starts from the preset, if any; it does not change while the form is open.
	// svelte-ignore state_referenced_locally
	let of = $state<TargetKind>(preset?.match.of ?? 'device');
	/** Each test's patterns, as typed. */
	// svelte-ignore state_referenced_locally
	const tests = $state(
		Object.fromEntries(TEST_FIELDS.map((f) => [f, patternText(preset?.match[f] ?? [])])) as Record<
			TestField,
			string
		>
	);
	// svelte-ignore state_referenced_locally
	let kind = $state<RuleKind>(preset?.kind ?? 'tag');
	// svelte-ignore state_referenced_locally
	let key = $state(preset?.key ?? '');
	// svelte-ignore state_referenced_locally
	let value = $state(preset?.value ?? '');
	// svelte-ignore state_referenced_locally
	let note = $state(preset?.note ?? '');
	/** The name typed; until then, it follows what the rule matches and does. */
	let typed = $state<string | null>(null);
	let lasts = $state('never');
	let until = $state('');
	let saving = $state(false);
	let problem = $state<string | null>(null);

	const kinds = $derived(RULE_KINDS.filter((k) => RULE_APPLIES[k].includes(of)));
	const fields = $derived(of === 'port' ? [] : LOCKABLE[of]);
	const keyed = $derived(kind === 'label' || kind === 'lock');
	const valued = $derived(!RULE_UNVALUED.includes(kind));
	const choices = $derived(
		kind !== 'lock'
			? null
			: key === 'site'
				? [...index.sites.keys()]
				: key === 'kind'
					? (KIND_CHOICES[of] ?? null)
					: (CHOICES[key] ?? null)
	);
	const valueLabel = $derived(kind === 'ignore-neighbor' ? 'Neighbors named' : 'Value');

	/** What the rule matches and does, as the form gives it now. */
	const body = $derived.by(() => {
		const match: Match = emptyMatch(of);
		for (const f of TESTS[of]) match[f] = patterns(tests[f]);
		return { match, kind, key: keyed ? key.trim() : null, value: valued ? value.trim() : null };
	});
	const lacking = $derived(missing(body));
	/**
	 * The preset's own name, while the rule is still as preset; else one from
	 * what it matches and does, once it has all it needs.
	 */
	const auto = $derived(
		preset && ruleName(body) === ruleName(preset) ? preset.name : lacking ? '' : ruleName(body)
	);
	const name = $derived(typed ?? auto);
	/** What the preview asks about, as text, so it asks again only when that changes. */
	const asking = $derived(lacking ? null : JSON.stringify(body));

	/** The latest preview's answer, and what it was asked about. */
	let answer = $state<{ for: string; preview: RulePreview | null; problem: string | null } | null>(
		null
	);
	/** Which request is the latest; an answer to any other is stale. */
	let asked = 0;

	$effect(() => {
		const about = asking;
		const n = ++asked;
		if (about === null) return;
		const timer = setTimeout(() => void ask(n, about), SETTLE_MS);
		return () => clearTimeout(timer);
	});

	async function ask(n: number, about: string): Promise<void> {
		const by = ui.person.trim() || 'preview';
		try {
			const preview = await previewRule({ name: 'preview', note: '', ...body, by });
			if (n === asked) answer = { for: about, preview, problem: null };
		} catch (err) {
			const problem = err instanceof Error ? err.message : String(err);
			if (n === asked) answer = { for: about, preview: null, problem };
		}
	}

	/** Keep the tests the new kind of object takes, and what it does valid there. */
	function chooseOf(next: TargetKind): void {
		of = next;
		for (const f of TEST_FIELDS) if (!TESTS[next].includes(f)) tests[f] = '';
		if (!kinds.includes(kind)) chooseKind(kinds[0] ?? 'tag');
		else if (kind === 'lock') {
			if (!fields.includes(key)) key = '';
			value = '';
		}
	}

	/** A key and value mean another thing for each kind; start them afresh. */
	function chooseKind(next: RuleKind): void {
		kind = next;
		key = '';
		value = '';
	}

	function chooseField(field: string): void {
		key = field;
		value = '';
	}

	function expires(): string | null {
		if (lasts === 'until') return until ? new Date(until).toISOString() : null;
		const hours = LASTS.find((l) => l.id === lasts)?.hours;
		return hours ? new Date(Date.now() + hours * 3_600_000).toISOString() : null;
	}

	/** Names, as many as the preview gives, and how many more. */
	function some(list: RulePreview['matches']): string {
		const names = list.slice(0, NAMED).map((t) => targetName(t, index));
		const more = list.length - names.length;
		return more > 0 ? `${names.join(', ')}, and ${more} more` : names.join(', ');
	}

	async function save(e: SubmitEvent): Promise<void> {
		e.preventDefault();
		rememberName(ui.person.trim());
		saving = true;
		problem = null;
		try {
			const made = await makeRule({
				name: name.trim(),
				...body,
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

<form onsubmit={save} aria-label="New rule">
	<h3>New rule</h3>
	<label>
		Rule name
		<input value={name} oninput={(e) => (typed = e.currentTarget.value)} required maxlength="80" />
	</label>
	<label>
		On
		<select
			value={of}
			onchange={(e) => chooseOf(e.currentTarget.value as TargetKind)}
			aria-label="On"
		>
			{#each OBJECTS as k (k)}
				<option value={k}>{NOUNS[k][1].charAt(0).toUpperCase() + NOUNS[k][1].slice(1)}</option>
			{/each}
		</select>
	</label>
	{#each TESTS[of] as f (f)}
		{@const values = suggestions(index, of, f, overrides.list)}
		<label>
			{TEST_LABEL[f]}
			<input
				bind:value={tests[f]}
				required={f === 'interface'}
				placeholder={f === 'interface' ? 'Gi1/0/48, */0/48' : undefined}
				list={values.length ? `${uid}-${f}` : undefined}
				autocomplete="off"
			/>
		</label>
		{#if values.length}
			<datalist id="{uid}-{f}">
				{#each offered(tests[f], values) as v (v)}
					<option value={v}></option>
				{/each}
			</datalist>
		{/if}
	{/each}
	<p class="hint">* matches anything; each test must hold, any of its values may</p>
	<label>
		Does
		<select
			value={kind}
			onchange={(e) => chooseKind(e.currentTarget.value as RuleKind)}
			disabled={kinds.length < 2}
			aria-label="Does"
		>
			{#each kinds as k (k)}
				<option value={k}>{RULE_KIND_LABEL[k]}</option>
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
	{#if valued}
		<label>
			{valueLabel}
			{#if choices}
				<select bind:value required aria-label={valueLabel}>
					<option value="" disabled>Choose a value</option>
					{#each choices as c (c)}
						<option value={c}>{c}</option>
					{/each}
				</select>
			{:else}
				<input
					bind:value
					required
					maxlength="200"
					placeholder={kind === 'ignore-neighbor' ? 'SEP*, or * for any' : undefined}
				/>
			{/if}
		</label>
	{/if}
	<section
		class="preview"
		class:waiting={answer !== null && !lacking && answer.for !== asking}
		aria-label="Preview"
		aria-live="polite"
	>
		{#if lacking}
			<p class="muted">Give {lacking} to see what it would apply on.</p>
		{:else if !answer}
			<p class="muted">Working out what it would apply on…</p>
		{:else if answer.preview}
			{@const p = answer.preview}
			{@const noun = NOUNS[of === 'port' ? 'device' : of]}
			{#if p.matches.length === 0}
				<p>Matches nothing now</p>
			{:else}
				<p>Matches {counted(p.matches.length, noun)}</p>
				<p class="muted">{some(p.matches)}</p>
			{/if}
			{#if p.overridden.length}
				<p class="muted">
					{p.overridden.length} where an override on the object or a newer rule wins
				</p>
			{/if}
			{#if of === 'port'}
				{#if p.set_aside.length}
					<p>Would set aside {counted(p.set_aside.length, ['finding', 'findings'])}:</p>
					<ul>
						{#each p.set_aside as title, i (i)}
							<li>{named(title)}</li>
						{/each}
					</ul>
				{:else}
					<p class="muted">Would set aside no findings</p>
				{/if}
				{#if p.raised.length}
					<p class="warning">Would raise {p.raised.length}:</p>
					<ul>
						{#each p.raised as title, i (i)}
							<li>{named(title)}</li>
						{/each}
					</ul>
				{/if}
			{/if}
			{#if p.reason}
				<p class="warning reason">The topology would not take it: {p.reason}</p>
			{/if}
		{:else}
			<p class="muted">{answer.problem}</p>
		{/if}
	</section>
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
	{#if problem}<p class="error" role="alert">Could not make the rule: {problem}</p>{/if}
	<p class="actions">
		<button type="submit" disabled={saving}>Make rule</button>
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
	p {
		margin: 0;
	}
	.hint,
	.muted {
		color: var(--muted);
		font-size: 12px;
	}
	.preview {
		display: flex;
		flex-direction: column;
		gap: 2px;
		padding: 6px 8px;
		border: 1px solid var(--border);
		border-radius: 4px;
		font-size: 13px;
	}
	.waiting {
		opacity: 0.6;
	}
	.preview ul {
		margin: 0;
		padding-left: 16px;
		font-size: 12px;
	}
	.warning {
		color: var(--accent);
	}
	.reason {
		white-space: pre-line;
	}
	.error {
		color: var(--down);
		font-size: 12px;
	}
	.actions {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}
</style>
