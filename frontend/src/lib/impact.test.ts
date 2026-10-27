import { describe, expect, it } from 'vitest';
import {
	deviceImpact,
	failuresOf,
	impactOf,
	linksImpact,
	noFailures,
	reach,
	worstImpact
} from './impact.ts';
import { fixtureIndex } from './test-fixture.ts';

// The fixture: cores a-core-01 and b-core-01; a-acc-01 hangs off a-core-01
// by a two-link LAG; branch C's one router c-wan-01 links to both hubs and
// to its two access switches.
const CIRCUIT_TO_A = 'a-wan-01:Gi1/0/1--c-wan-01:Gi1/0/1';

describe('reach', () => {
	it('reaches everything and finds where redundancy already ends', () => {
		const index = fixtureIndex();
		const { reached, fragile } = reach(index, noFailures());
		expect(reached.size).toBe(index.topology.devices.length);
		expect(Object.fromEntries(fragile)).toEqual({
			'a-acc-01': ['a-core-01'],
			'c-acc-01': ['c-wan-01'],
			'c-acc-02': ['c-wan-01']
		});
	});

	it('counts a parallel link as a second link but not a second way past its device', () => {
		const index = fixtureIndex();
		const lag = index.topology.links.filter((l) => l.a.lag === 'Port-channel1');
		const one = reach(index, { devices: new Set(), links: new Set([lag[0]?.id ?? '']) });
		expect(one.reached.has('a-acc-01')).toBe(true);
		expect(one.fragile.get('a-acc-01')).toEqual(['a-core-01']);
	});
});

describe('impactOf', () => {
	it('cuts off what hangs on a failed device only', () => {
		const index = fixtureIndex();
		const impact = impactOf(index, failuresOf(index, [{ kind: 'device', id: 'c-wan-01' }]));
		expect([...impact.cutOff].sort()).toEqual(['c-acc-01', 'c-acc-02']);
		expect(impact.exposed.size).toBe(0);
	});

	it('reports devices that lose their second way, with the device they now depend on', () => {
		const index = fixtureIndex();
		const impact = impactOf(index, failuresOf(index, [{ kind: 'links', ids: [CIRCUIT_TO_A] }]));
		expect(impact.cutOff.size).toBe(0);
		// The access switches had no redundancy to lose, so only the router counts.
		expect(Object.fromEntries(impact.exposed)).toEqual({ 'c-wan-01': ['b-wan-01'] });
	});

	it('fails a whole site', () => {
		const index = fixtureIndex();
		const impact = impactOf(index, failuresOf(index, [{ kind: 'site', id: 'A' }]));
		expect(impact.failed.devices).toEqual(new Set(['a-wan-01', 'a-core-01', 'a-acc-01']));
		expect(impact.cutOff.size).toBe(0);
		// One core device is left, so everything now depends on it.
		expect(Object.fromEntries(impact.exposed)).toEqual({
			'b-wan-01': ['b-core-01'],
			'c-wan-01': ['b-core-01', 'b-wan-01']
		});
	});

	it('does not count again what earlier failures already did', () => {
		const index = fixtureIndex();
		const before = failuresOf(index, [{ kind: 'links', ids: [CIRCUIT_TO_A] }]);
		const impact = impactOf(index, failuresOf(index, [{ kind: 'device', id: 'b-wan-01' }]), before);
		expect([...impact.cutOff].sort()).toEqual(['c-acc-01', 'c-acc-02', 'c-wan-01']);
		// a-wan-01 had a way through b-wan-01; c-wan-01 was already exposed, so it is not again.
		expect(Object.fromEntries(impact.exposed)).toEqual({ 'a-wan-01': ['a-core-01'] });
	});
});

describe('drawing helpers', () => {
	it('rank failed over cut off over exposed, and tell lost links from partly lost ones', () => {
		const index = fixtureIndex();
		const impact = impactOf(index, failuresOf(index, [{ kind: 'device', id: 'c-wan-01' }]));
		expect(deviceImpact(impact, 'c-wan-01')).toBe('failed');
		expect(deviceImpact(impact, 'c-acc-01')).toBe('cutoff');
		expect(deviceImpact(impact, 'a-wan-01')).toBeNull();
		expect(worstImpact(impact, ['a-wan-01', 'c-acc-01', 'c-wan-01'])).toBe('failed');
		const circuits = index.topology.links.filter((l) => l.kind === 'wan');
		expect(linksImpact(impact, circuits)).toBe('partial');
		expect(linksImpact(impact, circuits.slice(1))).toBe('lost');
	});
});
