<!--
@component
Every keyboard shortcut, by what it is for, from the same list the keys and
search use, so the help cannot drift from what the keys do. Opened with `?`
or the header's ? button; Escape or Close shuts it.
-->
<script lang="ts">
	import { COMMANDS } from './commands.ts';

	let { open = $bindable(false) }: { open: boolean } = $props();

	let dialog: HTMLDialogElement;
	const groups = [...new Set(COMMANDS.map((c) => c.group))].map((group) => ({
		group,
		commands: COMMANDS.filter((c) => c.group === group && c.keys.length > 0)
	}));

	$effect(() => {
		if (open && !dialog.open) dialog.showModal();
		else if (!open && dialog.open) dialog.close();
	});
</script>

<dialog bind:this={dialog} onclose={() => (open = false)} aria-labelledby="shortcuts-title">
	<h2 id="shortcuts-title">Keyboard shortcuts</h2>
	<div class="groups">
		{#each groups as g (g.group)}
			<section>
				<h3>{g.group}</h3>
				<dl>
					{#each g.commands as c (c.id)}
						<dt>
							{#each c.keys as k, i (k)}{#if i}<span class="or">or</span>{/if}<kbd>{k}</kbd>{/each}
						</dt>
						<dd>{c.label}</dd>
					{/each}
				</dl>
			</section>
		{/each}
		<section>
			<h3>Wall display</h3>
			<dl>
				<dt><kbd>Space</kbd></dt>
				<dd>Pause or resume</dd>
				<dt><kbd>←</kbd><span class="or">or</span><kbd>→</kbd></dt>
				<dd>Previous or next</dd>
				<dt><kbd>Esc</kbd></dt>
				<dd>Leave the wall display</dd>
			</dl>
		</section>
	</div>
	<p class="note">
		Keys work anywhere except while typing in a box. <kbd>Ctrl+K</kbd> is <kbd>⌘K</kbd> on a Mac. Search
		runs every command, including those without keys, such as Path from the selected device, Back to now,
		and Wall display: type what you want to do.
	</p>
	<p class="actions"><button onclick={() => dialog.close()}>Close</button></p>
</dialog>

<style>
	dialog {
		width: min(760px, 92vw);
		max-height: 86vh;
		padding: 18px 22px;
		background: var(--panel);
		color: var(--text);
		border: 1px solid var(--border);
		border-radius: 8px;
		box-shadow: 0 16px 48px rgb(0 0 0 / 0.5);
	}
	dialog::backdrop {
		background: rgb(0 0 0 / 0.5);
	}
	h2 {
		margin: 0 0 10px;
		font-size: 17px;
	}
	.groups {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
		gap: 4px 28px;
	}
	h3 {
		margin: 12px 0 6px;
		font-size: 12px;
		font-weight: normal;
		color: var(--muted);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}
	dl {
		display: grid;
		grid-template-columns: max-content 1fr;
		gap: 5px 14px;
		margin: 0;
	}
	dt {
		text-align: right;
		white-space: nowrap;
	}
	dd {
		margin: 0;
	}
	.or {
		margin: 0 4px;
		color: var(--muted);
		font-size: 12px;
	}
	.note {
		margin: 16px 0 0;
		color: var(--muted);
		font-size: 13px;
	}
	.actions {
		margin: 14px 0 0;
		text-align: right;
	}
</style>
