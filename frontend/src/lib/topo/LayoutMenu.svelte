<!--
@component
Save the topology view's current picture under a name, or open or delete a
saved one. The backend keeps them, so they outlast the page.
-->
<script lang="ts">
	import {
		deleteLayout,
		getLayout,
		listLayouts,
		saveLayout,
		type LayoutIn,
		type LayoutSummary,
		type SavedLayout
	} from '../api/layouts.ts';

	const { snapshot, onOpen }: { snapshot: () => LayoutIn; onOpen: (layout: SavedLayout) => void } =
		$props();

	const SCOPE_LABEL: Record<string, string> = {
		network: 'Whole network',
		neighborhood: 'Neighborhood',
		path: 'Path'
	};

	let root: HTMLDivElement;
	let open = $state(false);
	let name = $state('');
	let layouts = $state<LayoutSummary[]>([]);
	let message = $state('');

	async function attempt(action: () => Promise<void>): Promise<void> {
		message = '';
		try {
			await action();
		} catch (e) {
			message = e instanceof Error ? e.message : String(e);
		}
	}

	async function toggle(): Promise<void> {
		open = !open;
		if (open) await attempt(async () => void (layouts = await listLayouts()));
	}

	function save(e: SubmitEvent): Promise<void> {
		e.preventDefault();
		const chosen = name.trim();
		return attempt(async () => {
			await saveLayout(chosen, snapshot());
			layouts = await listLayouts();
			name = '';
			message = `Saved "${chosen}".`;
		});
	}

	function openLayout(chosen: string): Promise<void> {
		return attempt(async () => {
			onOpen(await getLayout(chosen));
			open = false;
		});
	}

	function remove(chosen: string): Promise<void> {
		return attempt(async () => {
			await deleteLayout(chosen);
			layouts = await listLayouts();
		});
	}

	function onWindowClick(e: MouseEvent): void {
		if (open && e.target instanceof Node && !root.contains(e.target)) open = false;
	}
</script>

<svelte:window onclick={onWindowClick} />

<div class="menu" bind:this={root}>
	<button aria-expanded={open} onclick={toggle}>Saved layouts</button>
	{#if open}
		<div class="popover" role="dialog" aria-label="Saved layouts">
			<form onsubmit={save}>
				<input
					bind:value={name}
					maxlength="64"
					placeholder="Name this layout"
					aria-label="Layout name"
				/>
				<button type="submit" disabled={!name.trim()}>Save</button>
			</form>
			{#if message}<p class="message" aria-live="polite">{message}</p>{/if}
			{#if layouts.length}
				<ul>
					{#each layouts as layout (layout.name)}
						<li>
							<button class="open" onclick={() => openLayout(layout.name)}>
								<span>{layout.name}</span>
								<span class="hint">
									{SCOPE_LABEL[layout.scope] ?? layout.scope} · {new Date(
										layout.saved_at
									).toLocaleString()}
								</span>
							</button>
							<button
								class="delete"
								aria-label={`Delete ${layout.name}`}
								onclick={() => remove(layout.name)}>×</button
							>
						</li>
					{/each}
				</ul>
			{:else}
				<p class="hint">No saved layouts yet.</p>
			{/if}
		</div>
	{/if}
</div>

<style>
	.menu {
		position: relative;
	}
	.popover {
		position: absolute;
		top: calc(100% + 6px);
		/* Open leftward: the menu sits near the right end of the toolbar. */
		right: 0;
		z-index: 10;
		width: 340px;
		padding: 10px;
		background: var(--panel);
		border: 1px solid var(--border);
		border-radius: 8px;
		box-shadow: 0 8px 24px rgb(0 0 0 / 0.4);
	}
	form {
		display: flex;
		gap: 6px;
	}
	input {
		flex: 1;
		min-width: 0;
		padding: 4px 8px;
		font: inherit;
		color: var(--text);
		background: var(--bg);
		border: 1px solid var(--border);
		border-radius: 6px;
	}
	ul {
		list-style: none;
		margin: 10px 0 0;
		padding: 0;
		max-height: 300px;
		overflow-y: auto;
	}
	li {
		display: flex;
		gap: 4px;
	}
	.open {
		flex: 1;
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		border: none;
		background: none;
		text-align: left;
	}
	.open:hover,
	.delete:hover {
		background: var(--panel-2);
	}
	.delete {
		border: none;
		background: none;
		color: var(--muted);
	}
	.hint,
	.message {
		color: var(--muted);
		font-size: 12px;
	}
	.message {
		margin: 8px 0 0;
	}
</style>
