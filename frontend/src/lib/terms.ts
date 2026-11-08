/**
 * The words Sunstone uses for what is layered over the links, and the
 * organization's own words for them, from the topology's `terms`: with
 * `tenant: Customer`, tenants are called customers everywhere, and search
 * finds them by either word.
 */
import type { Term } from './api/topology.ts';
import type { TopologyIndex } from './topology.ts';

export const DEFAULT_TERMS: Record<Term, string> = {
	network: 'Network',
	transport: 'Transport',
	external: 'External',
	application: 'Application',
	partner: 'Partner',
	tenant: 'Tenant',
	tunnel: 'Tunnel',
	fabric: 'Fabric'
};

/**
 * What a thing is called here.
 *
 * @param index - Topology index.
 * @param key - Sunstone's term.
 * @param plural - The plural, made by adding an "s".
 * @returns The organization's word if it has one, else Sunstone's; capitalized.
 */
export function term(index: TopologyIndex, key: Term, plural = false): string {
	const word = index.topology.terms[key] ?? DEFAULT_TERMS[key];
	return plural ? `${word}s` : word;
}

/**
 * Every word a thing goes by, for search.
 *
 * @param index - Topology index.
 * @param key - Sunstone's term.
 * @returns Sunstone's word, and the organization's when it differs.
 */
export function termWords(index: TopologyIndex, key: Term): string[] {
	return [...new Set([DEFAULT_TERMS[key], term(index, key)])];
}
