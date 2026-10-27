/**
 * On-call data as the UI shows it: who owns a device, site, or link, who is
 * on call for it, whom a page would go to, and which carriers to call about
 * which circuits. The server works out shifts and escalation; this only
 * looks things up in what it sends.
 */
import type { Carrier, Duty, OnCall, Ownership, Person, TeamNow } from './api/oncall.ts';
import type { Selection } from './state.svelte.ts';
import type { TopologyIndex } from './topology.ts';

/**
 * The team that owns a device, site, or links.
 *
 * @param ownership - Owners from the server.
 * @param item - What to look up.
 * @returns The team's id; for several links, the owner of the first owned.
 *   Null if no route matches it.
 */
export function ownerOf(ownership: Ownership, item: Selection): string | null {
	if (item.kind === 'device') return ownership.devices[item.id] ?? null;
	if (item.kind === 'site') return ownership.sites[item.id] ?? null;
	for (const id of item.ids) {
		const team = ownership.links[id];
		if (team) return team;
	}
	return null;
}

/**
 * A person, by id.
 *
 * @param oncall - On-call data.
 * @param id - Their id.
 * @returns The person; someone no longer in the directory is named by id.
 */
export function personOf(oncall: OnCall, id: string): Person {
	return oncall.people.find((p) => p.id === id) ?? { id, name: id };
}

/** Someone a page would go to, if sent now. */
export interface Step {
	to: Duty;
	person: Person;
	afterMin: number;
}

/**
 * Whom a page to a team would go to if sent now, step by step, as the
 * team's escalation policy says. Steps with no one to page are left out,
 * as the server leaves them out.
 *
 * @param oncall - On-call data.
 * @param team - The team.
 * @returns The steps, first first.
 */
export function wouldPage(oncall: OnCall, team: TeamNow): Step[] {
	const holder: Record<Duty, string | null | undefined> = {
		primary: team.now.primary,
		secondary: team.now.secondary,
		manager: team.manager
	};
	return team.escalation.flatMap((step) => {
		const id = holder[step.to];
		return id ? [{ to: step.to, person: personOf(oncall, id), afterMin: step.after_min }] : [];
	});
}

/**
 * The carriers to call about some links: one entry per circuit.
 *
 * @param oncall - On-call data.
 * @param index - Topology index.
 * @param ids - Link ids.
 * @returns Each circuit among them, with its carrier's contact when there is one.
 */
export function carriersFor(
	oncall: OnCall,
	index: TopologyIndex,
	ids: string[]
): { circuit: string; provider: string; carrier: Carrier | null }[] {
	return ids.flatMap((id) => {
		const circuit = index.links.get(id)?.circuit;
		if (!circuit) return [];
		const carrier = oncall.carriers.find((c) => c.provider === circuit.provider) ?? null;
		return [{ circuit: circuit.circuit_id, provider: circuit.provider, carrier }];
	});
}

/**
 * The links a selection or a problem is about, for finding carriers.
 *
 * @param item - A device, site, or links.
 * @returns The link ids, if it is links; else none.
 */
export function linksOf(item: Selection): string[] {
	return item.kind === 'links' ? item.ids : [];
}
