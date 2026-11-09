<!--
@component
What carries a connection and what it is for: its IDs (the enterprise's
CID, a cable ID on our own cable, and the carrier's, each side's where they
differ), who provides its path and the layer-2 service it is part of, its
medium, the port channel it is a member of, the MACsec on its ports, what
LLDP and CDP should show on our port, and its roles at the edge, each with
what it does to the security boundary. Roles not documented say whether they
are implied by the far end, or TBD. MACsec says what it is carried on.
A link's priority says where it comes from and what it does, with who
answers for it first, or that an override here hides it from status; and
each connection names the resources that hold it. Fields an override locks
say so, with what the topology says.
-->
<script lang="ts">
	import type { Fabric, Link, Tunnel } from './api/topology.ts';
	import {
		edgeBoundary,
		edgeLabel,
		fabricRoles,
		lagMembers,
		lagOf,
		linkRoles,
		macsecLinks,
		macsecOn,
		MEDIUM_LABEL,
		pathText,
		serviceText,
		showsOf,
		showsText,
		sidesText,
		tunnelRoles,
		type Roles
	} from './connections.ts';
	import { linkHidden, locked } from './OverridesFor.svelte';
	import { lagId, named, shown, target } from './overrides.svelte.ts';
	import { linkRating, PRIORITY_EFFECT, ratingText, responsibleText } from './priorities.ts';
	import { resourcesHolding } from './resources.ts';
	import { select } from './state.svelte.ts';
	import { linkName, shortInterface, type TopologyIndex } from './topology.ts';

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
		const topology = index.topology;
		if (item.kind === 'link') {
			const { link } = item;
			const macsec = macsecOn(topology, link);
			const lag = lagOf(topology, link);
			const rating = linkRating(topology, link);
			return {
				of: target('link', link.id),
				cidLabel: link.circuit ? 'CID' : 'Cable ID',
				cid: link.enterprise_cid,
				circuit: link.circuit,
				path: pathText(link),
				service: serviceText(topology, link),
				medium: link.medium ? MEDIUM_LABEL[link.medium] : null,
				// Inside MACsec, LLDP and CDP reach the far end whatever the
				// provider passes.
				// With MACsec on its ports or not, the link says what they show.
				shows: acrossService(link),
				lag,
				members: lag ? lagMembers(topology, lag) : [],
				macsec,
				carriedOn: [] as Link[],
				roles: linkRoles(topology, link),
				rating,
				hidden: linkHidden(index, link),
				responsible: named(responsibleText(topology, link, rating)),
				resources: resourcesHolding(index, { kind: 'links', ids: [link.id] })
			};
		}
		const it = item.kind === 'tunnel' ? item.tunnel : item.fabric;
		const macsec = item.kind === 'tunnel' && item.tunnel.kind === 'macsec';
		return {
			of: target(item.kind, it.name),
			cidLabel: 'CID',
			cid: it.enterprise_cid,
			circuit: it.circuit,
			path: it.circuit
				? `Service · ${it.circuit.provider}`
				: macsec
					? 'MACsec, on the physical ports'
					: null,
			service: null,
			medium: null,
			shows: null,
			lag: null,
			members: [] as Link[],
			macsec: [] as Tunnel[],
			carriedOn: item.kind === 'tunnel' && macsec ? macsecLinks(topology, item.tunnel) : [],
			roles: item.kind === 'tunnel' ? tunnelRoles(topology, item.tunnel) : fabricRoles(item.fabric),
			rating: null,
			hidden: false,
			responsible: null,
			resources: resourcesHolding(
				index,
				item.kind === 'tunnel'
					? { kind: 'tunnel', id: item.tunnel.name }
					: { kind: 'fabric', id: item.fabric.name }
			)
		} satisfies Record<string, unknown> & { roles: Roles };
	});

	/**
	 * What a link shows, where across a layer-2 service the far end is our
	 * devices on it: on an E-Tree, a leaf's are the roots.
	 */
	function acrossService(link: Link): string {
		const text = showsText(showsOf(link));
		const b = link.b;
		const service = 'transport' in b ? index.transports.get(b.transport)?.service : null;
		if (!service || !('transport' in b)) return text;
		const ours =
			service === 'e-tree' && b.role !== 'root'
				? 'the roots on the same service'
				: 'our devices on the same service';
		return text
			.replace(/^The far end/, ours.charAt(0).toUpperCase() + ours.slice(1))
			.replace(/the far end$/, ours);
	}

	/** How LLDP and CDP relate to a MACsec connection, in a few words. */
	const SECURED: Record<NonNullable<Tunnel['neighbors']> | 'unsaid', string> = {
		inside: 'LLDP and CDP inside it',
		alongside: 'LLDP and CDP alongside it, in clear',
		none: 'LLDP and CDP do not cross it',
		unsaid: 'not said how LLDP and CDP cross it'
	};

	/** The far end of a MACsec connection on one of a link's ports. */
	function farOf(t: Tunnel, link: Link): string {
		const here = [link.a, link.b].some(
			(e) => 'device' in e && e.device === t.a.device && e.interface === t.a.interface
		);
		const far = here ? t.b : t.a;
		return 'device' in far
			? `${shown(far.device)} ${shortInterface(far.interface)}`
			: shown(far.external);
	}
</script>

<h3>Connection</h3>
<dl>
	{#if facts.cid}
		<dt>{facts.cidLabel}</dt>
		<dd>
			<span class="mono">{sidesText(facts.cid)}</span>
			{@render locked(facts.of, 'enterprise_cid')}
		</dd>
	{/if}
	{#if facts.circuit}
		<dt>Carrier CID</dt>
		<dd class="mono">{sidesText(facts.circuit.circuit_id)}</dd>
	{/if}
	{#if facts.path}
		<dt>Path</dt>
		<dd>{facts.path}</dd>
	{/if}
	{#if facts.service}
		<dt>Service</dt>
		<dd>{facts.service}</dd>
	{/if}
	{#if facts.carriedOn.length}
		<dt>Carried on</dt>
		<dd>
			{#each facts.carriedOn as l, i (l.id)}{#if i}{' and '}{/if}<button
					class="link"
					onclick={() => select({ kind: 'links', ids: [l.id] }, true)}>{named(linkName(l))}</button
				>{/each}
		</dd>
	{/if}
	{#if facts.medium}
		<dt>Medium</dt>
		<dd>{facts.medium} {@render locked(facts.of, 'medium')}</dd>
	{/if}
	{#if facts.lag}
		<dt>Port channel</dt>
		<dd>
			<button
				class="link"
				onclick={() => select({ kind: 'links', ids: facts.members.map((m) => m.id) }, true)}
				>{shortInterface(facts.lag.a.interface)} – {shortInterface(facts.lag.b.interface)}</button
			>
			{#if facts.lag.enterprise_cid}<span class="mono">· {sidesText(facts.lag.enterprise_cid)}</span
				>
				{@render locked(target('lag', lagId(facts.lag)), 'enterprise_cid')}{/if}
			<span class="muted"
				>· {facts.members.length} member{facts.members.length === 1 ? '' : 's'}</span
			>
		</dd>
	{/if}
	{#if facts.macsec.length && item.kind === 'link'}
		<dt>MACsec</dt>
		<dd>
			{#each facts.macsec as t, i (t.name)}{#if i}<br />{/if}<button
					class="link"
					onclick={() => select({ kind: 'tunnel', id: t.name }, true)}>{t.name}</button
				>
				<span class="muted">· to {farOf(t, item.link)} · {SECURED[t.neighbors ?? 'unsaid']}</span
				>{/each}
		</dd>
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
{#if facts.rating || facts.resources.length}
	<dl>
		{#if facts.rating}
			<dt>Priority</dt>
			<dd>
				{#if facts.hidden}
					Ignored <span class="muted">· hidden from status here</span>
				{:else}
					{named(ratingText(facts.rating))}
					<span class="muted">· {PRIORITY_EFFECT[facts.rating.priority]}</span>
				{/if}
				{@render locked(facts.of, 'priority')}
			</dd>
			<dt title="Who answers for it first when it is down">Responsible</dt>
			<dd>{facts.responsible}</dd>
		{/if}
		{#if facts.resources.length}
			<dt title="The resources that list it as a member">Resources</dt>
			<dd>
				{#each facts.resources as r, i (r.name)}{#if i}{', '}{/if}<button
						class="link"
						onclick={() => select({ kind: 'resource', id: r.name }, true)}>{r.name}</button
					>{/each}
			</dd>
		{/if}
	</dl>
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
	/* As the details panel's own names. */
	.link {
		border: none;
		background: none;
		padding: 0;
		color: var(--accent);
		font: inherit;
		cursor: pointer;
		text-align: left;
	}
	.link:hover {
		text-decoration: underline;
	}
</style>
