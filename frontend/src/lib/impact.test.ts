import { describe, expect, it } from 'vitest';
import { deviceImpact, linksImpact, worstImpact, type Impact } from './impact.ts';
import { fixtureIndex } from './test-fixture.ts';

// What the server answers for c-wan-01 failing: branch C's switches are cut
// off. (The analysis itself is tested with the backend.)
const C_WAN_FAILS: Impact = {
	failed: { devices: new Set(['c-wan-01']), links: new Set() },
	cutOff: new Set(['c-acc-01', 'c-acc-02']),
	exposed: new Map()
};

describe('drawing helpers', () => {
	it('rank failed over cut off over exposed, and tell lost links from partly lost ones', () => {
		const index = fixtureIndex();
		const impact = C_WAN_FAILS;
		expect(deviceImpact(impact, 'c-wan-01')).toBe('failed');
		expect(deviceImpact(impact, 'c-acc-01')).toBe('cutoff');
		expect(deviceImpact(impact, 'a-wan-01')).toBeNull();
		expect(worstImpact(impact, ['a-wan-01', 'c-acc-01', 'c-wan-01'])).toBe('failed');
		const circuits = index.topology.links.filter((l) => l.kind === 'wan');
		expect(linksImpact(impact, circuits)).toBe('partial');
		expect(linksImpact(impact, circuits.slice(1))).toBe('lost');
	});

	it('count a failed link as lost even when both its ends are fine', () => {
		const index = fixtureIndex();
		const circuit = index.topology.links.find((l) => l.kind === 'wan');
		const impact: Impact = {
			failed: { devices: new Set(), links: new Set([circuit?.id ?? '']) },
			cutOff: new Set(),
			exposed: new Map([['c-wan-01', ['b-wan-01']]])
		};
		expect(linksImpact(impact, circuit ? [circuit] : [])).toBe('lost');
		expect(deviceImpact(impact, 'c-wan-01')).toBe('exposed');
	});
});
