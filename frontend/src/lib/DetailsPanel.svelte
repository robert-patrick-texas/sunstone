<!--
@component
Details of the current selection: a device and its neighbors, a site and
its WAN links, or a set of links. Names in the panel are links that select
and bring that item into view.
-->
<script lang="ts">
	import type { Endpoint, Link } from './api/topology.ts';
	import { expandedSites, select, ui, type Selection } from './state.svelte.ts';
	import { ROLE_COLOR } from './theme.ts';
	import {
		formatSpeed,
		neighborsOf,
		ROLE_LABEL,
		ROLES,
		shortInterface,
		siteOf,
		type TopologyIndex
	} from './topology.ts';

	const { index }: { index: TopologyIndex } = $props();

	const selection = $derived(ui.selection);

	/** Select a name in the panel; the click must not also reach its row, which selects the link. */
	function follow(e: MouseEvent, target: Selection): void {
		e.stopPropagation();
		select(target, true);
	}

	function siteWanLinks(code: string): { local: Endpoint; remote: Endpoint; link: Link }[] {
		return (index.devicesBySite.get(code) ?? []).flatMap((d) =>
			neighborsOf(index, d.name).filter((n) => siteOf(index, n.remote.device) !== code)
		);
	}
</script>

{#snippet deviceLink(name: string)}
	<button class="link" onclick={(e) => follow(e, { kind: 'device', id: name })}>{name}</button>
{/snippet}

{#snippet siteLink(code: string)}
	<button class="link" onclick={(e) => follow(e, { kind: 'site', id: code })}>{code}</button>
{/snippet}

{#snippet endpoint(end: Endpoint)}
	{@render deviceLink(end.device)}
	<span class="mono">{shortInterface(end.interface)}</span>
	{#if end.lag}<span class="tag">{shortInterface(end.lag)}</span>{/if}
{/snippet}

{#if selection}
	<aside class="details" aria-label="Details">
		<button class="close" onclick={() => select(null)} aria-label="Close details">×</button>

		{#if selection.kind === 'device'}
			{@const device = index.devices.get(selection.id)}
			{#if device}
				{@const neighbors = neighborsOf(index, device.name)}
				<h2>{device.name}</h2>
				<p>
					<span class="role" style:--role={ROLE_COLOR[device.role]}>{ROLE_LABEL[device.role]}</span>
					at {@render siteLink(device.site)}
					{index.sites.get(device.site)?.name}
				</p>
				<dl>
					{#if device.platform}<dt>Platform</dt>
						<dd>{device.platform}</dd>{/if}
					{#if device.mgmt_ip}<dt>Management</dt>
						<dd class="mono">{device.mgmt_ip}</dd>{/if}
				</dl>
				<h3>Neighbors ({neighbors.length})</h3>
				<table>
					<thead><tr><th>Local</th><th>Neighbor</th><th>Remote</th><th>Speed</th></tr></thead>
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
							<span class="role" style:--role={ROLE_COLOR[role]}>{count} {ROLE_LABEL[role]}</span>
						{/if}
					{/each}
				</p>
				<button
					onclick={() =>
						expandedSites.has(site.code)
							? expandedSites.delete(site.code)
							: expandedSites.add(site.code)}
				>
					{expandedSites.has(site.code) ? 'Collapse' : 'Expand'} in hierarchy
				</button>
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
									{n.link.circuit ? `${n.link.circuit.provider} ${n.link.circuit.circuit_id}` : ''}
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
			<table>
				<thead><tr><th>A end</th><th>B end</th><th>Speed</th></tr></thead>
				<tbody>
					{#each links as link (link.id)}
						<tr>
							<td>{@render endpoint(link.a)}</td>
							<td>{@render endpoint(link.b)}</td>
							<td>
								{formatSpeed(link.speed_mbps)}
								{#if link.kind === 'wan'}<span class="tag wan">WAN</span>{/if}
							</td>
						</tr>
						{#if link.circuit}
							<tr class="sub">
								<td colspan="3">Circuit {link.circuit.circuit_id} · {link.circuit.provider}</td>
							</tr>
						{/if}
					{/each}
				</tbody>
			</table>
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
