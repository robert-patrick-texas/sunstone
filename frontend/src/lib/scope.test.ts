import { describe, expect, it } from 'vitest';
import { NO_REGION, scopeOf } from './scope.ts';
import { layeredFixture, layeredIndex } from './test-fixture.ts';
import { indexTopology } from './topology.ts';

const index = layeredIndex();
const ON_GREY_BLUE_A = 'a-acc-01';
const CIRCUIT_A_B = 'a-wan-01:Hu1/0/2--b-wan-01:Hu1/0/2';

describe('scopeOf', () => {
	it('takes in everything with no network chosen', () => {
		const scope = scopeOf(index, []);
		expect(scope.networks).toEqual([]);
		expect(scope.has(['b-core-01'], [])).toBe(true);
		expect(scope.has([], [])).toBe(true);
	});

	it("takes in a network's own parts, and those beneath it at its sites", () => {
		// Grey is at A and C, over blue over black.
		const scope = scopeOf(index, ['grey']);
		expect([...scope.under].sort()).toEqual(['black', 'blue']);
		expect(scope.has([ON_GREY_BLUE_A], [])).toBe(true);
		// Black's router at A carries what grey rides; B is not one of grey's sites.
		expect(scope.has(['a-wan-01'], [])).toBe(true);
		expect(scope.has(['b-wan-01'], [])).toBe(false);
		expect(scope.has([], ['a-wan-01:GigabitEthernet0/0/0--transport:INET'])).toBe(true);
		expect(scope.has([], [CIRCUIT_A_B])).toBe(false);
		expect(scope.has([], [], ['BLUE-A-C'])).toBe(true);
		expect(scope.has([], [], ['DMVPN:b-wan-01~c-wan-01'])).toBe(false);
	});

	it("leaves out what is beneath but not at the network's sites", () => {
		// Red is only at C: grey's tunnel from A is not part of it.
		const scope = scopeOf(index, ['red']);
		expect(scope.has([], [], ['GREY-A-C'])).toBe(false);
		expect(scope.has(['c-wan-01'], [])).toBe(true);
		expect(scope.has(['a-wan-01'], [])).toBe(false);
	});

	it("knows a fabric's tunnels by the fabric's network", () => {
		expect(scopeOf(index, ['corp']).has([], [], ['DMVPN:b-wan-01~c-wan-01'])).toBe(true);
	});

	it("groups by the topology's regions, those with sites in scope", () => {
		expect(scopeOf(index, []).regions.map((r) => [r.name, [...r.sites]])).toEqual([
			['South', ['A', 'C']],
			['East', ['B']]
		]);
		expect(scopeOf(index, ['grey']).regions.map((r) => r.name)).toEqual(['South']);
		expect(scopeOf(index, []).regionOf('B')).toBe('East');
	});

	it("groups by a network's own regions when it is the one chosen", () => {
		const topology = structuredClone(layeredFixture);
		const grey = topology.networks.find((n) => n.name === 'grey')!;
		grey.regions = { 'grey-west': ['A'], 'grey-east': ['C'] };
		const own = indexTopology(topology);
		expect(scopeOf(own, ['grey']).regions.map((r) => r.name)).toEqual(['grey-west', 'grey-east']);
		expect(scopeOf(own, ['grey']).regionOf('C')).toBe('grey-east');
		// With two chosen, the topology's regions.
		expect(scopeOf(own, ['grey', 'corp']).regions.map((r) => r.name)).toEqual(['South', 'East']);
	});

	it('puts sites in no region last', () => {
		const topology = structuredClone(layeredFixture);
		delete topology.sites.find((s) => s.code === 'B')!.region;
		const scope = scopeOf(indexTopology(topology), []);
		expect(scope.regions.map((r) => r.name)).toEqual(['South', NO_REGION]);
		expect(scope.regionOf('B')).toBe(NO_REGION);
	});
});
