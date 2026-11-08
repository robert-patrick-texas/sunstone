<!--
@component
What carries a connection and what it is for: its IDs (the enterprise's
CID, a cable ID on our own cable, and the carrier's, each side's where they
differ), who provides its path, its medium, what LLDP and CDP should show on
our port, and its roles at the edge, each with what it does to the security
boundary. Roles not documented say whether they are implied by the far end,
or TBD.
-->
<script lang="ts">
	import type { Fabric, Link, Tunnel } from './api/topology.ts';
	import {
		edgeBoundary,
		edgeLabel,
		fabricRoles,
		linkRoles,
		MEDIUM_LABEL,
		pathText,
		SHOWS_LABEL,
		showsOf,
		sidesText,
		tunnelRoles,
		type Roles
	} from './connections.ts';
	import type { TopologyIndex } from './topology.ts';

	const {
		index,
		item
	}: {
		index: TopologyIndex;
		item:
			| { kind: 'link'; link: Link }
			| { kind: 'tunnel'; tunnel: Tunnel }
			| { kind: 'fabric'; fabric: Fabric };
	} = $props();

	const facts = $derived.by(() => {
		if (item.kind === 'link') {
			const { link } = item;
			const shows = showsOf(link);
			return {
				cidLabel: link.circuit ? 'CID' : 'Cable ID',
				cid: link.enterprise_cid,
				circuit: link.circuit,
				path: pathText(link),
				medium: link.medium ? MEDIUM_LABEL[link.medium] : null,
				shows: shows ? SHOWS_LABEL[shows] : 'Not said',
				roles: linkRoles(index.topology, link)
			};
		}
		const it = item.kind === 'tunnel' ? item.tunnel : item.fabric;
		return {
			cidLabel: 'CID',
			cid: it.enterprise_cid,
			circuit: it.circuit,
			path: it.circuit ? `Service · ${it.circuit.provider}` : null,
			medium: null,
			shows: null,
			roles:
				item.kind === 'tunnel' ? tunnelRoles(index.topology, item.tunnel) : fabricRoles(item.fabric)
		} satisfies Record<string, unknown> & { roles: Roles };
	});
</script>

<h3>Connection</h3>
<dl>
	{#if facts.cid}
		<dt>{facts.cidLabel}</dt>
		<dd class="mono">{sidesText(facts.cid)}</dd>
	{/if}
	{#if facts.circuit}
		<dt>Carrier CID</dt>
		<dd class="mono">{sidesText(facts.circuit.circuit_id)}</dd>
	{/if}
	{#if facts.path}
		<dt>Path</dt>
		<dd>{facts.path}</dd>
	{/if}
	{#if facts.medium}
		<dt>Medium</dt>
		<dd>{facts.medium}</dd>
	{/if}
	{#if facts.shows}
		<dt title="What LLDP and CDP should show on our port">Neighbors</dt>
		<dd>{facts.shows}</dd>
	{/if}
	<dt>Edge</dt>
	<dd>
		{#if facts.roles.source === 'tbd'}
			<b>TBD</b>
			<span class="muted">· not documented; routing policy at its site decides</span>
		{:else if facts.roles.edges.length === 0}
			Internal <span class="muted">· between two of our devices</span>
		{:else}
			{facts.roles.edges.map(edgeLabel).join(', ')}
			{#if facts.roles.source === 'implied'}<span class="muted">· implied by the far end</span>{/if}
		{/if}
	</dd>
</dl>
{#if facts.roles.edges.length}
	<ul class="edges">
		{#each facts.roles.edges as edge (edge)}
			<li><b>{edgeLabel(edge)}</b> <span class="muted">· {edgeBoundary(edge)}</span></li>
		{/each}
	</ul>
{/if}

<style>
	/* As the details panel's own headings and lists. */
	h3 {
		margin: 16px 0 6px;
		font-size: 13px;
		color: var(--muted);
		text-transform: uppercase;
		letter-spacing: 0.04em;
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
	.mono {
		font-family: ui-monospace, 'Cascadia Mono', Menlo, monospace;
		font-size: 12px;
	}
	.muted {
		color: var(--muted);
	}
	.edges {
		margin: 6px 0 0;
		padding-left: 18px;
	}
	.edges li {
		margin: 2px 0;
	}
</style>
