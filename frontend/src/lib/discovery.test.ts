import { describe, expect, it } from 'vitest';
import type { Comparison, Finding } from './api/discovery.ts';
import { deviceCheck, findingTarget, groupFindings, linkCheck } from './discovery.ts';
import { fixtureIndex } from './test-fixture.ts';

const index = fixtureIndex();
const [first, second] = index.topology.links.map((l) => l.id) as [string, string];

function finding(id: string, extra: Partial<Finding> = {}): Finding {
	return {
		id,
		kind: 'not-seen',
		title: id,
		detail: '',
		link: null,
		documented: [],
		seen: [],
		devices: [],
		...extra
	};
}

const COMPARISON: Comparison = {
	source: 'simulated',
	at: '2026-10-27T15:00:00Z',
	polled: ['a-wan-01', 'a-core-01'],
	links: { [first]: 'not-seen', [second]: 'unchecked' },
	confirmed: 7,
	findings: [
		finding('wrong', { kind: 'wrong-port', link: second, devices: ['a-core-01', 'a-acc-01'] }),
		finding('missing', { link: first, devices: ['a-wan-01', 'a-core-01'] }),
		finding('silent', { kind: 'no-neighbors', devices: ['c-acc-01'] })
	]
};

describe('groupFindings', () => {
	it('groups by kind, most misleading first', () => {
		expect(groupFindings(COMPARISON.findings).map((g) => [g.kind, g.items.length])).toEqual([
			['wrong-port', 1],
			['not-seen', 1],
			['no-neighbors', 1]
		]);
	});
});

describe('findingTarget', () => {
	it('selects the link a finding is about, or else its device', () => {
		expect(findingTarget(COMPARISON.findings[1]!)).toEqual({ kind: 'links', ids: [first] });
		expect(findingTarget(COMPARISON.findings[2]!)).toEqual({ kind: 'device', id: 'c-acc-01' });
		expect(findingTarget(finding('nothing'))).toBeNull();
	});
});

describe('linkCheck and deviceCheck', () => {
	it('count links the server leaves out as confirmed', () => {
		expect(linkCheck(COMPARISON, first)).toBe('not-seen');
		expect(linkCheck(COMPARISON, 'anything-else')).toBe('confirmed');
	});

	it('say whether a device answered and what involves it', () => {
		const core = deviceCheck(COMPARISON, index, 'a-core-01');
		expect(core.polled).toBe(true);
		// Its three links: one not seen, one not checked, one confirmed.
		expect([core.links, core.confirmed]).toEqual([3, 1]);
		expect(core.findings.map((f) => f.id)).toEqual(['wrong', 'missing']);
		expect(deviceCheck(COMPARISON, index, 'c-acc-01').polled).toBe(false);
	});
});
