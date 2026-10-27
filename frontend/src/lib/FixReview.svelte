<!--
@component
Reviewing the fix a discovery finding offers: the link as documented and as
it would be, what Live reads on the ports involved now, and what the fix
would do to redundancy and to the problems there are now, worked out on the
server. Accepting it, with a note and your name, changes the documentation
for everyone.
-->
<script lang="ts">
	import { acceptFix, fetchReview, type Change, type Review } from './api/changes.ts';
	import type { Finding } from './api/discovery.ts';
	import { linkEnds, portNow, reviewEffects, reviewWarning } from './discovery.ts';
	import { rememberName, ui } from './state.svelte.ts';
	import { formatSpeed } from './topology.ts';

	const {
		finding,
		onaccepted
	}: {
		finding: Finding;
		/** Called once the fix is in the documentation. */
		onaccepted: (change: Change) => void;
	} = $props();

	let review = $state.raw<Review | null>(null);
	let problem = $state<string | null>(null);
	let note = $state('');
	let saving = $state(false);
	const fix = $derived(finding.fix);
	const warning = $derived(review ? reviewWarning(review) : null);
	const effects = $derived(review ? reviewEffects(review) : []);

	// Worked out again for each finding reviewed.
	$effect(() => {
		const id = finding.id;
		let stopped = false;
		review = null;
		problem = null;
		fetchReview(id).then(
			(found) => {
				if (!stopped) review = found;
			},
			(e: unknown) => {
				if (!stopped) problem = e instanceof Error ? e.message : String(e);
			}
		);
		return () => {
			stopped = true;
		};
	});

	async function accept(e: SubmitEvent): Promise<void> {
		e.preventDefault();
		rememberName(ui.person.trim());
		saving = true;
		problem = null;
		try {
			const change = await acceptFix(finding.id, note, ui.person);
			ui.fixing = null;
			onaccepted(change);
		} catch (err) {
			problem = err instanceof Error ? err.message : String(err);
		} finally {
			saving = false;
		}
	}
</script>

{#if fix}
	<form class="review" aria-label="Review fix" onsubmit={accept}>
		<h3>Review fix</h3>
		<p class="title">{finding.title}</p>
		<p><b>{fix.summary}</b></p>
		<dl>
			{#if fix.before}
				<dt>Documented</dt>
				<dd>{linkEnds(fix.before)}</dd>
			{/if}
			<dt>{fix.before ? 'Becomes' : 'Adds'}</dt>
			<dd>
				{#if fix.after}{linkEnds(fix.after)} · {formatSpeed(fix.after.speed_mbps)}{:else}Retired: no
					longer documented{/if}
			</dd>
		</dl>
		{#if review}
			<h4>Live now</h4>
			<ul>
				{#each review.removes as port (port.device + port.interface)}
					<li><span class="tag">documented</span>{portNow(port)}</li>
				{/each}
				{#each review.adds as port (port.device + port.interface)}
					<li><span class="tag">seen</span>{portNow(port)}</li>
				{/each}
			</ul>
			{#if warning}<p class="warning" role="note">{warning}</p>{/if}
			<h4>What it changes</h4>
			{#if effects.length}
				<ul>
					{#each effects as line (line)}<li>{line}</li>{/each}
				</ul>
			{:else}
				<p class="muted">Nothing for redundancy, or for the problems there are now.</p>
			{/if}
		{:else if !problem}
			<p class="muted">Working out what it would do…</p>
		{/if}
		{#if problem}<p class="error" role="alert">{problem}</p>{/if}
		<input bind:value={note} maxlength="1000" placeholder="How it was checked" aria-label="Note" />
		<input
			bind:value={ui.person}
			required
			maxlength="64"
			placeholder="Your name"
			aria-label="Your name"
			autocomplete="name"
		/>
		<p class="actions">
			<button type="submit" disabled={saving || !review}>Accept fix</button>
			<button type="button" onclick={() => (ui.fixing = null)}>Cancel</button>
		</p>
	</form>
{/if}

<style>
	.review {
		display: flex;
		flex-direction: column;
		gap: 6px;
		margin: 0 0 12px;
		padding: 8px;
		border: 1px solid var(--drift);
		border-radius: 6px;
	}
	h3 {
		margin: 0;
		font-size: 13px;
	}
	h4 {
		margin: 4px 0 0;
		font-size: 12px;
		font-weight: normal;
		color: var(--muted);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}
	p {
		margin: 0;
	}
	.title,
	.muted {
		color: var(--muted);
		font-size: 12px;
	}
	dl {
		display: grid;
		grid-template-columns: auto 1fr;
		gap: 2px 8px;
		margin: 0;
		font-size: 12px;
	}
	dt {
		color: var(--muted);
	}
	dd {
		margin: 0;
	}
	ul {
		margin: 0;
		padding-left: 0;
		list-style: none;
		font-size: 12px;
	}
	li {
		margin: 2px 0;
	}
	.tag {
		display: inline-block;
		min-width: 76px;
		color: var(--muted);
	}
	.warning {
		padding: 4px 6px;
		border-left: 3px solid var(--accent);
		font-size: 12px;
	}
	.error {
		color: var(--down);
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
		gap: 6px;
	}
</style>
