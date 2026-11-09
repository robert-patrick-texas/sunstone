/**
 * How urgent each cable and circuit is, mirroring the backend's `ratings`
 * in `model.py`: a link's own priority, else one its devices or its far end
 * give (the higher where both ends do), else the highest default of its
 * roles. Access and interconnect default to low, since the party downstream
 * answers for them first; the rest to medium; nothing to high.
 */
import type { Link, Priority, Term, Topology } from './api/topology.ts';
import { linkRoles } from './connections.ts';
import { DEFAULT_TERMS } from './terms.ts';
import { isDeviceEnd } from './topology.ts';

/** What a default priority is for: an edge role, `internal`, or `tbd`. */
export type PriorityRole =
	| 'access'
	| 'transit'
	| 'interconnect'
	| 'ingress'
	| 'egress'
	| 'peering'
	| 'open'
	| 'internal'
	| 'tbd';

/** From least to most urgent. */
export const PRIORITIES: readonly Priority[] = ['ignored', 'low', 'medium', 'high'];

export const PRIORITY_LABEL: Record<Priority, string> = {
	ignored: 'Ignored',
	low: 'Low',
	medium: 'Medium',
	high: 'High'
};

/** What each priority does when its cable or circuit is down. */
export const PRIORITY_EFFECT: Record<Priority, string> = {
	ignored: 'counts toward no status and raises no problem',
	low: 'degrades its site at most',
	medium: 'degrades as far as the status rules take it',
	high: 'degrades as far as the status rules take it, and its problems come first'
};

export const DEFAULT_PRIORITIES: Record<PriorityRole, Priority> = {
	access: 'low',
	interconnect: 'low',
	transit: 'medium',
	ingress: 'medium',
	egress: 'medium',
	peering: 'medium',
	open: 'medium',
	internal: 'medium',
	tbd: 'medium'
};

/** A link's priority, where it comes from, and who answers for it first. */
export interface Rating {
	priority: Priority;
	/** `link`: its own; `device`: a device's or its far end's; `default`: for its roles. */
	source: 'link' | 'device' | 'default';
	/** The device or external node that sets it, or the role whose default it is. */
	by: string | null;
	/** The party downstream for access or interconnect alone; null for the enterprise. */
	responsible: string | null;
}

const rank = (p: Priority): number => PRIORITIES.indexOf(p);

// The priorities devices set, by name, worked out once per topology: rating
// every link of the 3,000-device sample looks each end up.
const byDevice = new WeakMap<Topology['devices'], Map<string, Priority>>();

function devicePriority(topology: Topology, name: string): Priority | undefined {
	let found = byDevice.get(topology.devices);
	if (!found) {
		found = new Map();
		for (const d of topology.devices) if (d.priority) found.set(d.name, d.priority);
		byDevice.set(topology.devices, found);
	}
	return found.get(name);
}

/**
 * A link's priority.
 *
 * @param topology - The topology.
 * @param link - The link.
 * @returns Its rating, as the backend works it out.
 */
export function linkRating(topology: Topology, link: Link): Rating {
	const roles = linkRoles(topology, link);
	const responsible = downstream(topology, link, roles.edges);
	if (link.priority) return { priority: link.priority, source: 'link', by: null, responsible };
	const given: [Priority, string][] = [];
	for (const end of [link.a, link.b]) {
		if (isDeviceEnd(end)) {
			const p = devicePriority(topology, end.device);
			if (p) given.push([p, end.device]);
		} else if ('external' in end) {
			const p = topology.externals.find((e) => e.name === end.external)?.priority;
			if (p) given.push([p, end.external]);
		}
	}
	if (given.length) {
		const [priority, by] = given.reduce((x, y) => (rank(y[0]) > rank(x[0]) ? y : x));
		return { priority, source: 'device', by, responsible };
	}
	const defaults: Record<PriorityRole, Priority> = {
		...DEFAULT_PRIORITIES,
		...(topology.priorities ?? {})
	};
	const keys: PriorityRole[] = roles.edges.length
		? roles.edges
		: [roles.source === 'tbd' ? 'tbd' : 'internal'];
	const by = keys.reduce((x, y) => (rank(defaults[y]) > rank(defaults[x]) ? y : x));
	return { priority: defaults[by], source: 'default', by, responsible };
}

/** Who answers first for a link for access or interconnect alone. */
function downstream(topology: Topology, link: Link, edges: readonly string[]): string | null {
	if (!edges.length || !edges.every((e) => e === 'access' || e === 'interconnect')) return null;
	const b = link.b;
	if ('external' in b) {
		const e = topology.externals.find((x) => x.name === b.external);
		return e?.kind === 'tenant' && e.tenant ? e.tenant : b.external;
	}
	if ('transport' in b) {
		const t = topology.transports.find((x) => x.name === b.transport);
		return t ? (t.provider ?? t.name) : b.transport;
	}
	return null;
}

/**
 * A rating in a few words: "High · set on the link", "Low · access, by default".
 *
 * @param rating - The rating.
 * @returns Its label and where it comes from.
 */
export function ratingText(rating: Rating): string {
	const from =
		rating.source === 'link'
			? 'set on the link'
			: rating.source === 'device'
				? `from ${rating.by}`
				: `${rating.by}, by default`;
	return `${PRIORITY_LABEL[rating.priority]} · ${from}`;
}

/**
 * Who answers first for a link, and what kind of party they are, in the
 * organization's own words where it has them.
 *
 * @param topology - The topology.
 * @param link - The link.
 * @param rating - Its rating.
 * @returns "Enterprise", or for example "Alpha (tenant)", "Nimbus Cloud
 *   (application)", or "Mesa Carrier (provider of MPLS)".
 */
export function responsibleText(topology: Topology, link: Link, rating: Rating): string {
	const who = rating.responsible;
	if (who === null) return 'Enterprise';
	const word = (key: Term) => (topology.terms[key] ?? DEFAULT_TERMS[key]).toLowerCase();
	const b = link.b;
	if ('external' in b) {
		const kind = topology.externals.find((e) => e.name === b.external)?.kind;
		return kind ? `${who} (${word(kind)})` : who;
	}
	if ('transport' in b) {
		return who === b.transport
			? `${who} (${word('transport')})`
			: `${who} (provider of ${b.transport})`;
	}
	return who;
}
