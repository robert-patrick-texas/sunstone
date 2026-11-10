/**
 * What the form for making a rule works out: the patterns a test's field
 * gives, the values the topology suggests for it, and what a draft still
 * needs before it can be previewed or made.
 */
import type { OverrideNow, TargetKind } from './api/overrides.ts';
import { linkRoles } from './connections.ts';
import { CHOICES, RULE_UNVALUED, type RuleDraft, type TestField } from './overrides.svelte.ts';
import { compareNatural, type TopologyIndex } from './topology.ts';

/**
 * The patterns a test's field gives.
 *
 * @param text - The field: "ISR4431, C9200-24T".
 * @returns Each pattern between commas, trimmed; none for empty text.
 */
export function patterns(text: string): string[] {
	return text
		.split(',')
		.map((p) => p.trim())
		.filter(Boolean);
}

/**
 * Patterns as a test's field shows them.
 *
 * @param list - The patterns.
 * @returns "ISR4431, C9200-24T".
 */
export function patternText(list: readonly string[]): string {
	return list.join(', ');
}

/**
 * The values the topology has for a test, on a kind of object: site codes,
 * regions, roles (a link's at the edge), platforms, priorities, kinds,
 * media, tenants, and tags, its own and those overrides add.
 *
 * @param index - The topology.
 * @param of - The kind of object; a port's are its device's but the interface.
 * @param test - The test.
 * @param added - The overrides, for the tags they add.
 * @returns The values, each once, in natural order; none for a name or an interface.
 */
export function suggestions(
	index: TopologyIndex,
	of: TargetKind,
	test: TestField,
	added: readonly OverrideNow[] = []
): string[] {
	const t = index.topology;
	const kind = of === 'port' ? 'device' : of;
	let values: (string | null | undefined)[] = [];
	switch (test) {
		case 'site':
			values = [...index.sites.keys()];
			break;
		case 'region':
			values = [...t.regions.map((r) => r.name), ...t.sites.map((s) => s.region)];
			break;
		case 'role':
			values =
				kind === 'link'
					? t.links.flatMap((l) => {
							const roles = linkRoles(t, l);
							if (roles.edges.length) return roles.edges;
							return [roles.source === 'tbd' ? 'tbd' : 'internal'];
						})
					: t.devices.map((d) => d.role);
			break;
		case 'platform':
			values = (kind === 'external' ? t.externals : t.devices).map((o) => o.platform);
			break;
		case 'priority':
			values = [...(CHOICES.priority ?? [])];
			break;
		case 'kind':
			values = (kind === 'link' ? t.links : kind === 'external' ? t.externals : t.transports).map(
				(o) => o.kind
			);
			break;
		case 'medium':
			values = t.links.map((l) => l.medium);
			break;
		case 'tenant':
			values = [...index.tenants.keys(), ...t.externals.map((e) => e.tenant)];
			break;
		case 'tag': {
			const tagged: Partial<Record<TargetKind, Map<string, { tags?: string[] }>>> = {
				external: index.externals,
				transport: index.transports,
				tunnel: index.tunnels,
				fabric: index.fabrics,
				resource: index.resources,
				network: index.networks
			};
			const own = [...(tagged[kind]?.values() ?? [])].flatMap((o) => o.tags ?? []);
			const made = added.filter(
				(o) => o.kind === 'tag' && o.state === 'active' && o.target.kind === kind
			);
			values = [...own, ...made.map((o) => o.value)];
			break;
		}
	}
	const found = values.filter((v): v is string => Boolean(v));
	return [...new Set(found)].sort(compareNatural);
}

/**
 * What a test's suggestions offer as its field reads now: each value not
 * given yet, after those given, so they go on being suggested after a comma.
 *
 * @param text - The field: "ISR4431, C".
 * @param values - The suggestions.
 * @returns "ISR4431, C9200-24T", and the rest; the values alone before any comma.
 */
export function offered(text: string, values: readonly string[]): string[] {
	const cut = text.lastIndexOf(',');
	const head = text.slice(0, cut + 1) + (/^\s*/.exec(text.slice(cut + 1))?.[0] ?? '');
	const given = new Set(patterns(head).map((p) => p.toLowerCase()));
	return values.filter((v) => !given.has(v.toLowerCase())).map((v) => head + v);
}

/**
 * A number of things, as a sentence says it.
 *
 * @param n - How many.
 * @param noun - The thing, one and many, as `NOUNS` gives them.
 * @returns "1 device", "53 devices".
 */
export function counted(n: number, noun: readonly [string, string]): string {
	return `${n} ${noun[n === 1 ? 0 : 1]}`;
}

/**
 * What a draft still needs before it can be previewed or made.
 *
 * @param d - The draft.
 * @returns "an interface", "a key", "a field", "the neighbors' names", or
 *   "a value"; null when it has all it needs.
 */
export function missing(d: Pick<RuleDraft, 'match' | 'kind' | 'key' | 'value'>): string | null {
	if (d.match.of === 'port' && d.match.interface.length === 0) return 'an interface';
	if (d.kind === 'label' && !d.key) return 'a key';
	if (d.kind === 'lock' && !d.key) return 'a field';
	if (RULE_UNVALUED.includes(d.kind) || d.value) return null;
	return d.kind === 'ignore-neighbor' ? "the neighbors' names" : 'a value';
}
