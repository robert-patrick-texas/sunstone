/**
 * Failures across the layers, in words. A "what if" answer says, for the
 * whole network and each named network a failure reaches, its status after
 * and what it loses: tunnels, circuits at each site, other links, and sites
 * cut off from it ("black loses 2 of 4 circuits at HOU; blue, grey stay
 * up"). Shared risks name what fails several of a network's tunnels at
 * once. The server works both out (`backend/src/sunstone/across.py`).
 */
import type { NetworkImpact } from './api/analysis.ts';
import type { Risk, RiskItem } from './api/risks.ts';
import type { Status } from './api/status.ts';
import { layersOf } from './layers.ts';
import type { Failure } from './state.svelte.ts';
import { STATUS_LABEL, statusWord } from './status.ts';
import { term } from './terms.ts';
import { compareNatural, isDeviceEnd, linkName, siteOf, type TopologyIndex } from './topology.ts';

/** Most sites named before "and N more". */
const NAMED_SITES = 4;
/** Most sites whose circuits are counted one by one. */
const COUNTED_SITES = 3;

/** What failures do to one network, ready to show. */
export interface NetworkLine {
	/** The named network, or null for the whole. */
	network: string | null;
	name: string;
	/**
	 * Its status, with what it was if that changes: `Operational → Degraded`;
	 * for a problem, from now to fixed: `Degraded → Operational`.
	 */
	status: string;
	after: Status;
	/** Whether its status gets worse. */
	worse: boolean;
	/** What it loses, each a noun phrase: `2 of 15 tunnels`, `2 of 4 circuits at HOU`. */
	losses: string[];
	/** Its sites cut off from it. */
	sitesLost: string[];
	/** Why it reads as it does, when it loses nothing: what it rides is degraded, say. */
	note: string | null;
}

const RANK: Record<Status, number> = { operational: 0, degraded: 1, offline: 2 };

function plural(n: number, noun: string): string {
	return `${n} ${noun}${n === 1 ? '' : 's'}`;
}

/**
 * Words joined as a list: `a`, `a and b`, `a, b, and c`.
 *
 * @param words - The words.
 * @returns The list.
 */
export function andList(words: string[]): string {
	if (words.length <= 2) return words.join(' and ');
	return `${words.slice(0, -1).join(', ')}, and ${words.at(-1)}`;
}

/**
 * Sites named, the first few, then how many more.
 *
 * @param sites - Site codes.
 * @returns For example `ATL, CLT, RDU` or `ATL, BNA, CLT, FTW, and 3 more`.
 */
export function siteList(sites: string[]): string {
	const sorted = [...sites].sort(compareNatural);
	if (sorted.length <= NAMED_SITES) return andList(sorted);
	return `${sorted.slice(0, NAMED_SITES).join(', ')}, and ${sorted.length - NAMED_SITES} more`;
}

/**
 * The circuits and other links a network loses, counted at each site
 * against the circuits it has there.
 *
 * @param index - Topology index.
 * @param network - The named network.
 * @param ids - Its links lost, by id.
 * @returns Noun phrases: `2 of 4 circuits at HOU`, `1 other link`.
 */
function linkLosses(index: TopologyIndex, network: string, ids: string[]): string[] {
	const slice = layersOf(index).slices.get(network);
	const isCircuit = (id: string) => {
		const link = index.links.get(id);
		return !!link && (!!link.circuit || (!isDeviceEnd(link.b) && 'transport' in link.b));
	};
	const lostAt = new Map<string, number>();
	let other = 0;
	for (const id of ids) {
		const link = index.links.get(id);
		if (!link) continue;
		if (!isCircuit(id)) {
			other++;
			continue;
		}
		const site = siteOf(index, link.a.device);
		lostAt.set(site, (lostAt.get(site) ?? 0) + 1);
	}
	const found: string[] = [];
	if (lostAt.size > COUNTED_SITES) {
		const lost = [...lostAt.values()].reduce((s, n) => s + n, 0);
		found.push(`${plural(lost, 'circuit')} at ${lostAt.size} sites`);
	} else {
		for (const [site, lost] of [...lostAt].sort((x, y) => compareNatural(x[0], y[0]))) {
			const has = [...(slice?.links ?? [])].filter((id) => {
				const link = index.links.get(id);
				return isCircuit(id) && link && siteOf(index, link.a.device) === site;
			}).length;
			found.push(`${lost} of ${plural(has, 'circuit')} at ${site}`);
		}
	}
	if (other) found.push(found.length ? `${plural(other, 'other link')}` : plural(other, 'link'));
	return found;
}

/**
 * One network's line in a "what if" answer, or in what fixing a problem
 * would bring back.
 *
 * @param index - Topology index.
 * @param impact - What the failures do to it.
 * @param fixing - Whether it is what fixing a problem would bring back, so a
 *   change of status reads from now to fixed.
 * @returns Its name, status, losses, and why it reads as it does.
 */
export function networkLine(
	index: TopologyIndex,
	impact: NetworkImpact,
	fixing = false
): NetworkLine {
	const { network, before, after } = impact;
	const losses: string[] = [];
	if (impact.tunnels_lost.length) {
		const word = term(index, 'tunnel', impact.tunnels !== 1).toLowerCase();
		losses.push(`${impact.tunnels_lost.length} of ${impact.tunnels} ${word}`);
	}
	if (network !== null) losses.push(...linkLosses(index, network, impact.links_lost));
	const changed = before !== after.status;
	let note: string | null = null;
	if (losses.length === 0 && impact.sites_lost.length === 0) {
		const caveat = after.caveats[0];
		const group = after.groups[0];
		note =
			after.status === 'operational' && caveat
				? `over ${caveat.split(':')[0]}`
				: (after.reasons[0] ??
					(group ? `${group.name} ${STATUS_LABEL[group.status].toLowerCase()}` : null));
	}
	return {
		network,
		name: after.name,
		status: !changed
			? statusWord(after)
			: fixing
				? `${statusWord(after)} → ${STATUS_LABEL[before]}`
				: `${STATUS_LABEL[before]} → ${statusWord(after)}`,
		after: after.status,
		worse: RANK[after.status] > RANK[before],
		losses,
		sitesLost: impact.sites_lost,
		note
	};
}

/**
 * What a network's line says beside its status: what it loses, or else
 * that it stays up and why it reads as it does.
 *
 * @param line - The network's line.
 * @returns For example `2 of 15 tunnels · HOU cut off`, or `Stays up, over black degraded at HOU`.
 */
export function lineDetail(line: NetworkLine): string {
	const sites = line.sitesLost.length ? [`${siteList(line.sitesLost)} cut off`] : [];
	const lost = [...line.losses, ...sites];
	if (lost.length) return lost.join(' · ');
	const up = line.network !== null && line.after === 'operational';
	return [up ? 'Stays up' : '', line.note ?? ''].filter(Boolean).join(', ');
}

/** Most networks named in a problem's line before "and N more". */
const PROBLEM_NETWORKS = 3;

/**
 * What a problem takes from the named networks, in a few words, for the
 * problems list: each network that loses something, and what.
 *
 * @param index - Topology index.
 * @param networks - What fixing the problem would bring back to each network.
 * @returns For example `blue: 1 of 9 tunnels · HOU cut off; grey: 2 of 9 tunnels`,
 *   or null when it takes nothing from any named network.
 */
export function problemNetworks(index: TopologyIndex, networks: NetworkImpact[]): string | null {
	const lines = networks
		.filter((n) => n.network !== null)
		.map((n) => networkLine(index, n))
		.filter((l) => l.losses.length || l.sitesLost.length);
	if (lines.length === 0) return null;
	const parts = lines.slice(0, PROBLEM_NETWORKS).map((l) => `${l.name}: ${lineDetail(l)}`);
	if (lines.length > PROBLEM_NETWORKS) parts.push(`${lines.length - PROBLEM_NETWORKS} more`);
	return parts.join('; ');
}

/**
 * What a shared risk does, in a few words.
 *
 * @param index - Topology index.
 * @param risk - The risk.
 * @param tunnels - How many tunnels its network has.
 * @returns For example `6 of 15 tunnels · cuts off ATL, CLT, and RDU`.
 */
export function riskSummary(index: TopologyIndex, risk: Risk, tunnels: number): string {
	const word = term(index, 'tunnel', true).toLowerCase();
	const cuts = risk.sites.length ? ` · cuts off ${siteList(risk.sites)}` : '';
	return `${risk.tunnels.length} of ${tunnels} ${word}${cuts}`;
}

/**
 * What one item of a shared risk is called.
 *
 * @param index - Topology index.
 * @param item - A device, link, or provider.
 * @returns A device's name, a link's short name, or a provider's name.
 */
export function riskItemName(index: TopologyIndex, item: RiskItem): string {
	if (item.kind !== 'link') return item.id;
	const link = index.links.get(item.id);
	return link ? linkName(link) : item.id;
}

/**
 * The failure a risk's item stands for, to ask "what if" of it.
 *
 * @param item - A device, link, or provider.
 * @returns The failure.
 */
export function riskFailure(item: RiskItem): Failure {
	if (item.kind === 'link') return { kind: 'links', ids: [item.id] };
	return { kind: item.kind, id: item.id };
}

/**
 * Every circuit one provider has in the network.
 *
 * @param index - Topology index.
 * @param provider - The provider's name.
 * @returns The links its circuits are.
 */
export function circuitsOf(index: TopologyIndex, provider: string): string[] {
	return index.topology.links.filter((l) => l.circuit?.provider === provider).map((l) => l.id);
}
