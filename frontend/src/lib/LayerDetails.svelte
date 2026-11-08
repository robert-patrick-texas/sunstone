<!--
@component
Details of something layered over the links, or beyond them: a named
network (what it rides, what rides it, its shared risks, sites, tunnels, and
fabrics), a transport and the circuits into it, an external node and what
reaches it, a tunnel's two ends and the risks it shares, a fabric's members,
or a tenant's networks and nodes.
What is outside the boundary says so. With live state, a network's status:
operational, degraded, or offline, why, what is degraded beneath it, and
its regions, sites, and locations that are not operational; a tunnel's
state; and a fabric's tunnels down and those built spoke to spoke now.
Names are links that select and bring that item into view; a network can be
shown in every view from here.
-->
<script lang="ts">
	import type { Snippet } from 'svelte';
	import { riskFailure, riskItemName, riskSummary } from './across.ts';
	import type { Risk, RiskReport } from './api/risks.ts';
	import type { Fabric, Link } from './api/topology.ts';
	import { carried, fabricTunnels, layersOf, onDemand } from './layers.ts';
	import type { StatusReport } from './api/status.ts';
	import { clock, tunnelName } from './history.ts';
	import { HEALTH_LABEL, linkLive, type LiveIndex } from './live.ts';
	import { STATUS_COLOR, STATUS_GLYPH, STATUS_LABEL, statusOf, statusWord } from './status.ts';
	import {
		checkImpact,
		select,
		showNetwork,
		ui,
		type AnySelection,
		type LayerSelection
	} from './state.svelte.ts';
	import { term } from './terms.ts';
	import { depthColor } from './theme.ts';
	import {
		compareNatural,
		formatSpeed,
		nodeKey,
		shortInterface,
		siteOf,
		type TopologyIndex
	} from './topology.ts';

	const {
		index,
		selection,
		live,
		status = null,
		risks = null
	}: {
		index: TopologyIndex;
		selection: LayerSelection;
		live: LiveIndex | null;
		/** Every network's status, while live state is shown. */
		status?: StatusReport | null;
		/** Each named network's shared risks. */
		risks?: RiskReport | null;
	} = $props();

	/** Shared risks listed before "Show all", and items named in one risk. */
	const RISKS_SHOWN = 6;
	const ITEMS_NAMED = 3;
	/** The network whose shared risks are all listed. */
	let allRisksOf = $state<string | null>(null);
	const allRisks = $derived(allRisksOf === selection.id);

	/** Tunnels the source reports for a fabric, by state. */
	function fabricLive(name: string): { down: string[]; built: string[] } {
		const mine = [...(live?.tunnels.values() ?? [])].filter((t) => t.tunnel.startsWith(`${name}:`));
		return {
			down: mine.filter((t) => t.status === 'down').map((t) => t.tunnel),
			built: mine.filter((t) => t.dynamic && t.status === 'up').map((t) => t.tunnel)
		};
	}

	const layers = $derived(layersOf(index));
	const SHAPE: Record<Fabric['shape'], string> = {
		'hub-spoke': 'Hubs and spokes',
		'hub-spoke-dynamic': 'Hubs and spokes, spoke to spoke on demand',
		'full-mesh': 'Full mesh',
		group: 'Group: members reach each other directly, without tunnels'
	};

	function follow(e: MouseEvent, target: AnySelection): void {
		e.stopPropagation();
		select(target, true);
	}

	function sitesOf(devices: Iterable<string>): string[] {
		return [...new Set([...devices].map((d) => siteOf(index, d)))].sort(compareNatural);
	}

	/** Whether a network is shown in every view now. */
	const shown = (name: string) => ui.networks.includes(name);

	function toggleShown(name: string): void {
		ui.networks = shown(name) ? ui.networks.filter((n) => n !== name) : [...ui.networks, name];
	}

	function circuitState(link: Link): string {
		if (!live) return '';
		const health = linkLive(live, link).health;
		return health === 'ok' ? 'up' : (HEALTH_LABEL[health as keyof typeof HEALTH_LABEL] ?? health);
	}
</script>

{#snippet networkLink(name: string)}
	<button class="link" onclick={(e) => follow(e, { kind: 'network', id: name })}>
		<span class="dot" style:--depth={depthColor(layers.slices.get(name)?.depth ?? 0)}></span>{name}
	</button>
{/snippet}

{#snippet deviceLink(name: string)}
	<button class="link" onclick={(e) => follow(e, { kind: 'device', id: name })}>{name}</button>
{/snippet}

{#snippet siteLink(code: string)}
	<button class="link" onclick={(e) => follow(e, { kind: 'site', id: code })}>{code}</button>
{/snippet}

{#snippet externalLink(name: string)}
	<button class="link" onclick={(e) => follow(e, { kind: 'external', id: name })}>{name}</button>
{/snippet}

{#snippet list(names: string[], render: Snippet<[string]>)}
	{#each names as name, i (name)}{i > 0 ? ', ' : ''}{@render render(name)}{/each}
{/snippet}

{#snippet riskItems(risk: Risk)}
	{#each risk.items.slice(0, ITEMS_NAMED) as item, i (item.kind + item.id)}{i > 0
			? ', '
			: ''}{#if item.kind === 'device'}{@render deviceLink(
				item.id
			)}{:else if item.kind === 'link'}<button
				class="link"
				onclick={(e) => follow(e, { kind: 'links', ids: [item.id] })}
				>{riskItemName(index, item)}</button
			>{:else}{item.id}{/if}{/each}{#if risk.items.length > ITEMS_NAMED}<span class="muted"
			>{` and ${risk.items.length - ITEMS_NAMED} more`}</span
		>{/if}
{/snippet}

{#snippet boundary(outside: boolean)}
	<span class="tag" class:outside>{outside ? 'Outside the boundary' : 'Inside the boundary'}</span>
{/snippet}

{#snippet sites(codes: string[])}
	<h3>Sites ({codes.length})</h3>
	<p class="wrap">
		{#each codes as code, i (code)}{i > 0 ? ' ' : ''}{@render siteLink(code)}{/each}
	</p>
{/snippet}

{#if selection.kind === 'network'}
	{@const network = index.networks.get(selection.id)}
	{@const slice = layers.slices.get(selection.id)}
	{#if network && slice}
		<p class="kind">{term(index, 'network')}</p>
		<h2>
			<span class="dot" style:--depth={depthColor(slice.depth)}></span>{network.name}
		</h2>
		<p>{@render boundary(network.boundary === 'outside')}</p>
		{#if network.description}<p class="muted">{network.description}</p>{/if}
		{#if statusOf(status, network.name)}
			{@const now = statusOf(status, network.name)!}
			<p class="now" style:--c={STATUS_COLOR[now.status]}>
				<i aria-hidden="true">{STATUS_GLYPH[now.status]}</i><b>{statusWord(now)}</b>
				<span class="muted">· {now.reached} of {now.sites} sites reached</span>
			</p>
			{#each now.reasons as reason (reason)}<p class="reason">{reason}</p>{/each}
			{#each now.caveats as caveat (caveat)}<p class="reason muted">* {caveat}</p>{/each}
			{#if now.groups.length}
				<h3>Not operational ({now.groups.length})</h3>
				<table>
					<tbody>
						{#each now.groups as g (g.kind + g.id)}
							<tr
								onclick={() =>
									g.kind === 'site' ? select({ kind: 'site', id: g.id }, true) : undefined}
							>
								<td>{g.name} <span class="muted">{g.kind}</span></td>
								<td style:color={STATUS_COLOR[g.status]}>{STATUS_LABEL[g.status]}</td>
								<td class="muted">{g.reasons[0] ?? ''}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			{/if}
		{/if}
		<p class="actions">
			<button
				onclick={() =>
					shown(network.name) ? toggleShown(network.name) : showNetwork(network.name)}
			>
				{shown(network.name) ? 'Stop showing' : 'Show in every view'}
			</button>
			{#if ui.networks.length > 0 && !shown(network.name)}
				<button onclick={() => toggleShown(network.name)}>Show with {ui.networks.join(', ')}</button
				>
			{/if}
			{#if ui.view !== 'logical'}
				<button
					onclick={() => {
						if (!shown(network.name)) showNetwork(network.name);
						ui.view = 'logical';
					}}>Logical view</button
				>
			{/if}
		</p>
		<dl>
			{#if network.tenant}
				<dt>{term(index, 'tenant')}</dt>
				<dd>
					<button
						class="link"
						onclick={(e) => follow(e, { kind: 'tenant', id: network.tenant ?? '' })}
						>{network.tenant}</button
					>
				</dd>
			{/if}
			<dt>Rides</dt>
			<dd>
				{#if slice.rides.size}{@render list([...slice.rides], networkLink)}{:else}Nothing: these are
					the circuits{/if}
			</dd>
			{#if slice.riders.size}
				<dt>Ridden by</dt>
				<dd>{@render list([...slice.riders].sort(compareNatural), networkLink)}</dd>
			{/if}
			<dt>Has</dt>
			<dd>
				{slice.devices.size} devices, {slice.links.size} links{#if slice.tunnels.length}, {slice
						.tunnels.length} tunnels{/if}{#if slice.fabrics.length}, {slice.fabrics.length} fabrics{/if}
			</dd>
		</dl>
		{@const own = risks?.networks.find((n) => n.network === network.name)}
		{#if own}
			{@const total = own.risks.length + own.more}
			<h3>Shared risk{total ? ` (${total})` : ''}</h3>
			{#if total}
				<p class="muted">
					{term(index, 'tunnel', true)} that look like separate paths but fail together: any one of these
					failing alone takes down the {term(index, 'tunnel', true).toLowerCase()} beside it.
				</p>
				{#if risks?.at}
					<p class="muted">
						With what is down at {clock(risks.at)}, only what is still up counts. A new one is a
						risk only because of it, and comes first.
					</p>
				{/if}
				<table class="risks">
					<tbody>
						{#each own.risks.slice(0, allRisks ? undefined : RISKS_SHOWN) as risk (risk.tunnels.join())}
							{@const first = risk.items[0]}
							<tr>
								<td
									>{#if risk.new}<span class="tag new">New</span>
									{/if}{@render riskItems(risk)}</td
								>
								<td class="muted">{riskSummary(index, risk, own.tunnels)}</td>
								<td class="nowrap">
									{#if first}<button
											class="link"
											aria-label="What if {riskItemName(index, first)} fails"
											onclick={() => checkImpact([riskFailure(first)])}>What if</button
										>{/if}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
				{#if !allRisks && own.risks.length > RISKS_SHOWN}
					<p>
						<button class="link" onclick={() => (allRisksOf = network.name)}
							>Show all {total}</button
						>
					</p>
				{:else if own.more}
					<p class="muted">and {own.more} more</p>
				{/if}
			{:else}
				<p class="muted">
					None: no one device, link, or provider beneath it takes two of its {term(
						index,
						'tunnel',
						true
					).toLowerCase()} at once.
				</p>
			{/if}
		{/if}
		{#if slice.fabrics.length}
			<h3>{term(index, 'fabric', true)}</h3>
			<table>
				<tbody>
					{#each slice.fabrics as f (f.name)}
						<tr onclick={() => select({ kind: 'fabric', id: f.name }, true)}>
							<td>{f.name}</td>
							<td class="muted">{f.technology ?? ''}</td>
							<td class="muted nowrap">{f.members.length} members</td>
						</tr>
					{/each}
				</tbody>
			</table>
		{/if}
		{#if slice.tunnels.length}
			<h3>{term(index, 'tunnel', true)}</h3>
			<table>
				<thead><tr><th>Name</th><th>Ends</th><th>Over</th></tr></thead>
				<tbody>
					{#each slice.tunnels as t (t.name)}
						<tr onclick={() => select({ kind: 'tunnel', id: t.name }, true)}>
							<td>{t.name}</td>
							<td class="mono">
								{siteOf(index, t.a.device)} – {'device' in t.b
									? siteOf(index, t.b.device)
									: t.b.external}
							</td>
							<td>{t.rides}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		{/if}
		{@const beyond = [...slice.nodes].sort(compareNatural)}
		{#if beyond.length}
			<h3>Beyond the boundary</h3>
			<p class="wrap">
				{#each beyond as key, i (key)}
					{@const [kind, name] = [key.slice(0, key.indexOf(':')), key.slice(key.indexOf(':') + 1)]}
					{i > 0 ? ', ' : ''}<button
						class="link"
						onclick={(e) =>
							follow(e, { kind: kind === 'transport' ? 'transport' : 'external', id: name })}
						>{name}</button
					>
				{/each}
			</p>
		{/if}
		{@render sites([...slice.sites].sort(compareNatural))}
	{/if}
{:else if selection.kind === 'transport'}
	{@const transport = index.transports.get(selection.id)}
	{#if transport}
		{@const circuits = index.linksByNode.get(nodeKey({ transport: transport.name })) ?? []}
		<p class="kind">{term(index, 'transport')}</p>
		<h2>{transport.name}</h2>
		<p>
			{@render boundary(true)}
			<span class="tag">{transport.kind === 'internet' ? 'Internet' : 'Private WAN'}</span>
		</p>
		{#if transport.description}<p class="muted">{transport.description}</p>{/if}
		<dl>
			{#if transport.provider}<dt>Provider</dt>
				<dd>{transport.provider}</dd>{/if}
			{#if transport.network}<dt>{term(index, 'network')}</dt>
				<dd>{@render networkLink(transport.network)}</dd>{/if}
			<dt>Circuits</dt>
			<dd>{circuits.length} from {sitesOf(circuits.map((l) => l.a.device)).length} sites</dd>
		</dl>
		<h3>Circuits</h3>
		<table>
			<thead>
				<tr
					><th>Device</th><th>Circuit</th><th>Speed</th>{#if live}<th>Now</th>{/if}</tr
				>
			</thead>
			<tbody>
				{#each circuits as link (link.id)}
					<tr onclick={() => select({ kind: 'links', ids: [link.id] }, true)}>
						<td>
							{@render deviceLink(link.a.device)}
							<span class="mono">{shortInterface(link.a.interface)}</span>
						</td>
						<td class="muted">
							{link.circuit ? `${link.circuit.provider} ${link.circuit.circuit_id}` : ''}
						</td>
						<td>{formatSpeed(link.speed_mbps)}</td>
						{#if live}<td>{circuitState(link)}</td>{/if}
					</tr>
				{/each}
			</tbody>
		</table>
		{@const services = index.topology.externals.filter((e) =>
			e.reached_over.includes(transport.name)
		)}
		{#if services.length}
			<h3>Reached over it</h3>
			<p class="wrap">
				{@render list(
					services.map((e) => e.name),
					externalLink
				)}
			</p>
		{/if}
	{/if}
{:else if selection.kind === 'external'}
	{@const external = index.externals.get(selection.id)}
	{#if external}
		{@const links = index.linksByNode.get(nodeKey({ external: external.name })) ?? []}
		{@const tunnels = index.topology.tunnels.filter(
			(t) => 'external' in t.b && t.b.external === external.name
		)}
		<p class="kind">{term(index, external.kind)} · {term(index, 'external')}</p>
		<h2>{external.name}</h2>
		<p>{@render boundary(true)}</p>
		<p class="muted">
			{#if external.kind === 'tenant'}
				Run by its {term(index, 'tenant').toLowerCase()}: known from our end only.
			{:else if external.kind === 'partner'}
				Run by the partner: known from our end only.
			{:else}
				A service someone else runs.
			{/if}
		</p>
		{#if external.description}<p class="muted">{external.description}</p>{/if}
		<dl>
			{#if external.tenant}
				<dt>{term(index, 'tenant')}</dt>
				<dd>
					<button
						class="link"
						onclick={(e) => follow(e, { kind: 'tenant', id: external.tenant ?? '' })}
						>{external.tenant}</button
					>
				</dd>
			{/if}
			{#if external.network}<dt>{term(index, 'network')}</dt>
				<dd>{@render networkLink(external.network)}</dd>{/if}
			{#if external.platform}<dt>Platform</dt>
				<dd>{external.platform}</dd>{/if}
			{#if external.reached_over.length}
				<dt>Reached over</dt>
				<dd>
					{#each external.reached_over as t, i (t)}{i > 0 ? ', ' : ''}<button
							class="link"
							onclick={(e) => follow(e, { kind: 'transport', id: t })}>{t}</button
						>{/each}
				</dd>
			{/if}
		</dl>
		{#if links.length}
			<h3>Connected at</h3>
			<table>
				<tbody>
					{#each links as link (link.id)}
						<tr onclick={() => select({ kind: 'links', ids: [link.id] }, true)}>
							<td>{@render siteLink(siteOf(index, link.a.device))}</td>
							<td>
								{@render deviceLink(link.a.device)}
								<span class="mono">{shortInterface(link.a.interface)}</span>
							</td>
							<td class="muted">{carried(index, link).join(', ')}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		{/if}
		{#if tunnels.length}
			<h3>{term(index, 'tunnel', true)} to it</h3>
			<table>
				<tbody>
					{#each tunnels as t (t.name)}
						<tr onclick={() => select({ kind: 'tunnel', id: t.name }, true)}>
							<td>{t.name}</td>
							<td>{@render deviceLink(t.a.device)}</td>
							<td class="mono">{'peer' in t.b ? (t.b.peer ?? '') : ''}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		{/if}
	{/if}
{:else if selection.kind === 'tunnel'}
	{@const tunnel = index.tunnels.get(selection.id)}
	{#if tunnel}
		<p class="kind">{term(index, 'tunnel')}</p>
		<h2>{tunnel.name}</h2>
		<dl>
			<dt>{term(index, 'network')}</dt>
			<dd>{@render networkLink(tunnel.network)}</dd>
			<dt>Over</dt>
			<dd>{@render networkLink(tunnel.rides)}</dd>
			{#if tunnel.technology}<dt>Technology</dt>
				<dd>{tunnel.technology}</dd>{/if}
			{#if live}
				{@const now = live.tunnels.get(tunnel.name)}
				<dt>Now</dt>
				<dd style:color={now?.status === 'down' ? STATUS_COLOR.offline : undefined}>
					{now ? (now.status === 'up' ? 'Up' : 'Down') : 'Not reported'}
				</dd>
			{/if}
		</dl>
		<table>
			<thead><tr><th>End</th><th>Interface</th><th>Source</th></tr></thead>
			<tbody>
				<tr>
					<td
						>{@render deviceLink(tunnel.a.device)}
						<span class="muted">{siteOf(index, tunnel.a.device)}</span></td
					>
					<td class="mono">{tunnel.a.interface}</td>
					<td class="mono">{tunnel.a.source ? shortInterface(tunnel.a.source) : ''}</td>
				</tr>
				<tr>
					{#if 'device' in tunnel.b}
						<td
							>{@render deviceLink(tunnel.b.device)}
							<span class="muted">{siteOf(index, tunnel.b.device)}</span></td
						>
						<td class="mono">{tunnel.b.interface}</td>
						<td class="mono">{tunnel.b.source ? shortInterface(tunnel.b.source) : ''}</td>
					{:else}
						<td
							>{@render externalLink(tunnel.b.external)}
							<span class="tag outside">Run by them</span></td
						>
						<td class="mono" colspan="2">{tunnel.b.peer ?? ''}</td>
					{/if}
				</tr>
			</tbody>
		</table>
		{#if tunnel.tags.length}<p class="muted">Tags: {tunnel.tags.join(', ')}</p>{/if}
		{@const shared = (
			risks?.networks.find((n) => n.network === tunnel.network)?.risks ?? []
		).filter((r) => r.tunnels.includes(tunnel.name))}
		{#if shared.length}
			<h3>Shared risk ({shared.length})</h3>
			<p class="muted">Each of these failing alone takes it down with others.</p>
			<table class="risks">
				<tbody>
					{#each shared as risk (risk.tunnels.join())}
						{@const others = risk.tunnels.filter((t) => t !== tunnel.name)}
						<tr>
							<td
								>{#if risk.new}<span class="tag new">New</span>
								{/if}{@render riskItems(risk)}</td
							>
							<td class="muted">
								with {others.slice(0, 2).map(tunnelName).join(', ')}{others.length > 2
									? ` and ${others.length - 2} more`
									: ''}{risk.sites.length ? ` · cuts off ${risk.sites.join(', ')}` : ''}
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		{/if}
	{/if}
{:else if selection.kind === 'fabric'}
	{@const fabric = index.fabrics.get(selection.id)}
	{#if fabric}
		{@const pairs = fabricTunnels(fabric).length}
		{@const dynamic = onDemand(fabric)}
		<p class="kind">{term(index, 'fabric')}</p>
		<h2>{fabric.name}</h2>
		<dl>
			<dt>{term(index, 'network')}</dt>
			<dd>{@render networkLink(fabric.network)}</dd>
			<dt>Over</dt>
			<dd>{@render networkLink(fabric.rides)}</dd>
			{#if fabric.technology}<dt>Technology</dt>
				<dd>{fabric.technology}</dd>{/if}
			<dt>Shape</dt>
			<dd>{SHAPE[fabric.shape]}</dd>
			<dt>{term(index, 'tunnel', true)}</dt>
			<dd>
				{pairs}{#if dynamic}, and up to {dynamic} more spoke to spoke on demand{/if}
			</dd>
		</dl>
		{#if live}
			{@const now = fabricLive(fabric.name)}
			<p class:reason={now.down.length > 0}>
				{now.down.length ? `${now.down.length} down` : 'All up'}{#if dynamic}
					· {now.built.length} spoke to spoke now{/if}
			</p>
			{#each now.down as t (t)}<p class="reason">{tunnelName(t)} down</p>{/each}
			{#each now.built as t (t)}<p class="muted">{tunnelName(t)}</p>{/each}
		{/if}
		<h3>Members ({fabric.members.length})</h3>
		<table>
			<thead><tr><th>Device</th><th>Site</th><th>Role</th><th>Interface</th></tr></thead>
			<tbody>
				{#each fabric.members as m (m.device)}
					<tr onclick={() => select({ kind: 'device', id: m.device }, true)}>
						<td>{@render deviceLink(m.device)}</td>
						<td>{siteOf(index, m.device)}</td>
						<td class:hub={m.role === 'hub'}>{m.role}</td>
						<td class="mono">{m.interface}</td>
					</tr>
				{/each}
			</tbody>
		</table>
	{/if}
{:else}
	{@const tenant = index.tenants.get(selection.id)}
	{#if tenant}
		{@const networks = index.topology.networks.filter((n) => n.tenant === tenant.name)}
		{@const nodes = index.topology.externals.filter((e) => e.tenant === tenant.name)}
		<p class="kind">{term(index, 'tenant')}</p>
		<h2>{tenant.name}</h2>
		{#if tenant.description}<p class="muted">{tenant.description}</p>{/if}
		{#if networks.length}
			<h3>{term(index, 'network', true)}</h3>
			<p>
				{@render list(
					networks.map((n) => n.name),
					networkLink
				)}
			</p>
		{/if}
		{#if nodes.length}
			<h3>Its nodes ({nodes.length})</h3>
			<table>
				<tbody>
					{#each nodes as e (e.name)}
						{@const at = index.linksByNode.get(nodeKey({ external: e.name }))?.[0]}
						<tr onclick={() => select({ kind: 'external', id: e.name }, true)}>
							<td>{e.name}</td>
							<td class="muted">{e.platform ?? ''}</td>
							<td
								>{#if at}{@render siteLink(siteOf(index, at.a.device))}{/if}</td
							>
						</tr>
					{/each}
				</tbody>
			</table>
		{/if}
	{/if}
{/if}

<style>
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
	.kind {
		color: var(--muted);
		font-size: 12px;
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
	.nowrap {
		white-space: nowrap;
	}
	.wrap {
		line-height: 1.7;
	}
	.tag {
		font-size: 10px;
		padding: 0 4px;
		border-radius: 3px;
		background: var(--panel-2);
		border: 1px solid var(--border);
		color: var(--muted);
		margin-right: 4px;
	}
	.tag.outside {
		border-style: dashed;
		border-color: var(--muted);
	}
	.tag.new {
		border-color: var(--live);
		color: var(--text);
	}
	.dot {
		display: inline-block;
		width: 8px;
		height: 8px;
		border-radius: 50%;
		background: var(--depth);
		margin-right: 5px;
	}
	.hub {
		font-weight: 600;
	}
	.now {
		display: flex;
		align-items: baseline;
		gap: 5px;
		color: var(--c);
	}
	.now i {
		font-style: normal;
		font-weight: 700;
	}
	.reason {
		font-size: 12px;
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
