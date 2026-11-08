import { describe, expect, it } from 'vitest';
import type { Link, Topology } from './api/topology.ts';
import {
	cidOf,
	edgeBoundary,
	fabricRoles,
	idWords,
	joins,
	linkRoles,
	pathText,
	rolesText,
	showsOf,
	sidesText,
	tunnelRoles
} from './connections.ts';
import { groupLabels, search, topologyEntries } from './search.ts';
import { layeredFixture } from './test-fixture.ts';
import { indexTopology, linkName } from './topology.ts';

const topology: Topology = structuredClone(layeredFixture);
const byId = (id: string): Link => {
	const found = topology.links.find((l) => l.id === id);
	if (!found) throw new Error(id);
	return found;
};
const INET = 'c-wan-01:GigabitEthernet0/0/0--transport:INET';
const WAN = 'a-wan-01:Gi1/0/1--c-wan-01:Gi1/0/1';
const CABLE = 'c-acc-01:Te1/0/49--c-wan-01:Te1/0/1';
const TENANT = 'c-acc-02:Gi1/0/9--external:r1-c:black';

describe('linkRoles', () => {
	it('implies roles only where the far end leaves no doubt', () => {
		expect(linkRoles(topology, byId(WAN))).toEqual({ edges: ['transit'], source: 'implied' });
		expect(linkRoles(topology, byId(CABLE))).toEqual({ edges: [], source: 'implied' });
		expect(linkRoles(topology, byId(TENANT))).toEqual({ edges: ['access'], source: 'implied' });
		// Routing policy at the site decides what a circuit into a transport is for.
		expect(linkRoles(topology, byId(INET))).toEqual({ edges: [], source: 'tbd' });
		const said = { ...byId(INET), edges: ['transit', 'egress'] as Link['edges'] };
		expect(linkRoles(topology, said)).toEqual({ edges: ['transit', 'egress'], source: 'declared' });
	});

	it('says them in a few words', () => {
		expect(rolesText(linkRoles(topology, byId(INET)))).toBe('TBD');
		expect(rolesText(linkRoles(topology, byId(CABLE)))).toBe('Internal');
		expect(rolesText(linkRoles(topology, byId(WAN)))).toBe('Transit (implied)');
		expect(edgeBoundary('egress')).toMatch(/outward/);
	});

	it('makes tunnels between our devices and fabrics transit', () => {
		const [tunnel] = topology.tunnels;
		const [fabric] = topology.fabrics;
		if (!tunnel || !fabric) throw new Error('fixture');
		expect(tunnelRoles(topology, tunnel).edges).toEqual(['transit']);
		expect(fabricRoles(fabric)).toEqual({ edges: ['transit'], source: 'implied' });
	});
});

describe('ids', () => {
	it('names a circuit by the enterprise CID, else the carrier’s', () => {
		const inet = byId(INET);
		expect(linkName(inet)).toBe('Circuit NO-2');
		const ours = { ...inet, enterprise_cid: { a: 'C-INET-01', z: null } };
		expect(cidOf(ours)).toBe('C-INET-01');
		expect(linkName(ours)).toBe('Circuit C-INET-01');
		const xc = {
			...byId(WAN),
			circuit: {
				provider: 'Granite Colo',
				circuit_id: { a: 'XC-1', z: 'XC-1' },
				type: 'cross-connect' as const
			}
		};
		expect(linkName(xc)).toBe('Cross-connect XC-1');
		expect(pathText(xc)).toBe('Cross-connect · Granite Colo');
		expect(pathText(byId(CABLE))).toBe('Our own cable');
	});

	it('writes each side once, or the A side alone where Z has none', () => {
		expect(sidesText({ a: 'A-B-01', z: 'A-B-01' })).toBe('A-B-01');
		expect(sidesText({ a: 'AUS-SAT-01', z: 'SAT-AUS-01' })).toBe('AUS-SAT-01 (A) · SAT-AUS-01 (Z)');
		expect(sidesText({ a: 'DAL-INET-01', z: null })).toBe('DAL-INET-01 (A)');
	});

	it('finds every value in a free-form carrier CID', () => {
		expect(idWords({ a: 'ME-1 / Pecos Bell 12/KXFU/204411', z: null })).toEqual([
			'ME-1 / Pecos Bell 12/KXFU/204411',
			'ME-1',
			'Pecos Bell 12/KXFU/204411'
		]);
	});

	it('joins a transport only through circuits for transit, or TBD', () => {
		expect(joins(byId(INET))).toBe(true);
		expect(joins({ ...byId(INET), edges: ['transit', 'egress'] })).toBe(true);
		expect(joins({ ...byId(INET), edges: ['peering'] })).toBe(false);
		expect(joins({ ...byId(TENANT), edges: ['access'] })).toBe(true);
	});

	it('takes what a port shows to be the far end only between our devices', () => {
		expect(showsOf(byId(WAN))).toEqual(['far-end']);
		expect(showsOf(byId(INET))).toEqual([]);
		expect(showsOf({ ...byId(INET), neighbors: ['provider'] })).toEqual(['provider']);
	});
});

describe('search by what carries a connection', () => {
	const changed = structuredClone(layeredFixture);
	changed.links = changed.links.map((l) =>
		l.id === INET
			? {
					...l,
					edges: ['transit', 'egress'],
					enterprise_cid: { a: 'C-INET-01', z: null },
					circuit: {
						provider: 'Northwind Fiber',
						circuit_id: { a: 'NO-2 / Pecos Bell 12/KXFU/204411', z: null },
						type: 'carrier'
					}
				}
			: l.id === CABLE
				? { ...l, enterprise_cid: { a: 'C-C0007', z: 'C-C0007' }, medium: 'fiber' }
				: l
	);
	const index = indexTopology(changed);
	const look = (query: string) =>
		search(query, [topologyEntries(index)], groupLabels(index))[0]?.entries.map((e) => e.label);

	it('finds a circuit by either CID, or part of the carrier’s', () => {
		expect(look('C-INET-01')).toEqual(['Circuit C-INET-01']);
		expect(look('KXFU/204411')).toEqual(['Circuit C-INET-01']);
		expect(look('C-C0007')).toEqual(['c-wan-01 Te1/0/1 – c-acc-01 Te1/0/49']);
	});

	it('finds connections by role, TBD included', () => {
		expect(look('egress')).toEqual(['Circuit C-INET-01']);
		expect(look('tbd')).toEqual(['Circuit NO-1']);
	});
});
