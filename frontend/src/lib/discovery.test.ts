import { afterEach, describe, expect, it } from 'vitest';
import type { Change, PortNow, Review } from './api/changes.ts';
import type { Comparison, Finding } from './api/discovery.ts';
import {
	changedTarget,
	changeLine,
	changeOf,
	deviceCheck,
	expectationOf,
	findingTarget,
	groupFindings,
	linkCheck,
	linkEnds,
	overrideOffers,
	portNow,
	reviewEffects,
	reviewWarning,
	seenWhen
} from './discovery.ts';
import { clock } from './history.ts';
import { overrides, target } from './overrides.svelte.ts';
import { fixtureIndex, layeredIndex } from './test-fixture.ts';
import { farDevice, indexTopology } from './topology.ts';

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
	tunnels: {},
	confirmed: 7,
	endpoints: {},
	seen: [],
	gone: [],
	expected: [],
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

	it('leave out links that do not say what they show, and count endpoints', () => {
		// c-wan-01 has four cables and, in the layered fixture, an Internet
		// circuit that does not say what LLDP and CDP show across it.
		const wan = deviceCheck(COMPARISON, layeredIndex(), 'c-wan-01');
		expect([wan.links, wan.confirmed, wan.endpoints]).toEqual([4, 4, 0]);
		const topology = structuredClone(layeredIndex().topology);
		const inet = 'c-wan-01:GigabitEthernet0/0/0--transport:INET';
		topology.links = topology.links.map((l) =>
			l.id === inet ? { ...l, neighbors: ['provider' as const] } : l
		);
		const said = deviceCheck(
			{ ...COMPARISON, links: { [inet]: 'provider' }, endpoints: { 'c-wan-01': 3 } },
			indexTopology(topology),
			'c-wan-01'
		);
		// The provider's equipment, seen as documented, counts as confirmed.
		expect([said.links, said.confirmed, said.endpoints]).toEqual([5, 5, 3]);
	});
});

describe('seenWhen', () => {
	const from = '2026-10-27T10:00:00Z';
	const until = '2026-10-27T12:45:00Z';
	const history = '2026-10-26T15:00:00Z';

	it('says since when a finding has been seen, as far back as history goes', () => {
		expect(seenWhen(finding('a', { first_seen: from }), history)).toBe(`since ${clock(from)}`);
		expect(seenWhen(finding('a'), history)).toBe(`since before ${clock(history)}`);
		expect(seenWhen(finding('a'), null)).toBe('');
	});

	it('says when a finding seen for a while stopped being seen', () => {
		const seen = finding('a', { first_seen: from, last_seen: until });
		expect(seenWhen(seen, history)).toBe(`${clock(from)} – ${clock(until)}`);
		expect(seenWhen(finding('a', { last_seen: until }), null)).toBe(`until ${clock(until)}`);
	});
});

function port(device: string, interface_: string, oper?: 'up' | 'down'): PortNow {
	return {
		device,
		interface: interface_,
		reading: oper
			? {
					device,
					interface: interface_,
					oper,
					in_pct: oper === 'up' ? 8.2 : 0,
					out_pct: oper === 'up' ? 13.9 : 0,
					observed_at: '2026-10-27T15:00:00Z',
					stale: false
				}
			: null
	};
}

function review(kind: 'move' | 'retire', extra: Partial<Review> = {}): Review {
	return {
		finding: finding('f', { fix: { kind, summary: 'Fix it', before: null, after: null } }),
		removes: [],
		adds: [],
		exposed: {},
		restored: [],
		cut_off: [],
		cleared: [],
		raised: [],
		involved: [],
		...extra
	};
}

describe('reviews', () => {
	it('read each port as Live does now', () => {
		expect(portNow(port('d-dist-02', 'TenGigabitEthernet1/0/48', 'up'))).toBe(
			'd-dist-02 Te1/0/48: up · 8% in, 14% out'
		);
		expect(portNow(port('d-dist-01', 'TenGigabitEthernet1/0/7', 'down'))).toBe(
			'd-dist-01 Te1/0/7: down'
		);
		expect(portNow(port('d-acc-01', 'Gi1/0/48'))).toBe('d-acc-01 Gi1/0/48: not monitored');
	});

	it('warn against retiring a link Live shows carrying traffic', () => {
		const ends = [port('a', 'Te1/0/1', 'up'), port('b', 'Te1/0/2', 'up')];
		expect(reviewWarning(review('retire', { removes: ends }))).toMatch(
			/^Live shows it up .* both ends/
		);
		expect(reviewWarning(review('move', { removes: [ends[0]!] }))).toBe(
			'Live shows a Te1/0/1 up: something is still plugged into it.'
		);
		expect(reviewWarning(review('move', { removes: [port('a', 'Te1/0/1', 'down')] }))).toBeNull();
	});

	it('say what a fix does to redundancy and to problems', () => {
		const effects = reviewEffects(
			review('move', {
				exposed: { 'd-acc-05': ['d-dist-02'], 'd-acc-06': ['d-core-01', 'd-dist-01'] },
				cleared: ['d-dist-01 – d-acc-05 down']
			})
		);
		expect(effects).toEqual([
			'd-acc-05 would depend on d-dist-02 alone',
			'd-acc-06 would depend on d-core-01 and d-dist-01',
			'Clears “d-dist-01 – d-acc-05 down”'
		]);
		expect(reviewEffects(review('move'))).toEqual([]);
	});

	it('find the change that put a link where it is', () => {
		const moved = index.topology.links[0]!;
		const change = (id: string, after: typeof moved | null): Change => ({
			id,
			finding: 'f',
			title: 'f',
			fix: { kind: after ? 'move' : 'retire', summary: '', before: moved, after },
			note: '',
			by: 'Pat',
			at: '2026-10-27T15:00:00Z'
		});
		const changes = [change('later', null), change('first', moved)];
		expect(changeOf(changes, moved.id)?.id).toBe('first');
		expect(changeOf(changes, 'other')).toBeUndefined();
		expect(changeLine(changes[1]!)).toBe(`Moved to ${linkEnds(moved)}`);
		expect(changeLine(changes[0]!)).toBe(`Retired ${linkEnds(moved)}`);
		expect(changeLine({ ...change('x', null), fix: { kind: 'expect', summary: '' } })).toBe(
			'Expected: f'
		);
		const documented: Change = {
			...change('d', moved),
			fix: {
				kind: 'document',
				summary: 'Document that Circuit DAL-IAD-01 shows nothing',
				before: moved,
				after: { ...moved, neighbors: ['nothing'] }
			}
		};
		expect(changeLine(documented)).toBe('Documented that Circuit DAL-IAD-01 shows nothing');
		expect(changedTarget(null, moved)).toEqual({ kind: 'device', id: moved.a.device });
		expect(changedTarget(moved, null)).toEqual({ kind: 'links', ids: [moved.id] });
	});
});

describe('expectationOf', () => {
	it('finds the expected finding that explains a link, with its change', () => {
		const link = index.topology.links[0]!;
		const silent = link.a.device;
		const away = index.topology.links.find((l) => ![l.a.device, farDevice(l)].includes(silent))!;
		const expected = finding('silent', { kind: 'no-neighbors', devices: [silent] });
		const comparison = { ...COMPARISON, expected: [expected] };
		const change: Change = {
			id: 'c',
			finding: 'silent',
			title: 'silent',
			fix: { kind: 'expect', summary: '' },
			note: 'LLDP off by policy',
			by: 'Pat',
			at: '2026-10-27T15:00:00Z'
		};
		expect(expectationOf(comparison, [change], link)).toEqual({ finding: expected, change });
		// While the switch does not answer, its links are findings of their own, covered by it.
		const covered = finding('link', { link: link.id, covered_by: 'silent' });
		expect(expectationOf({ ...COMPARISON, expected: [covered] }, [change], link)).toEqual({
			finding: covered,
			change
		});
		expect(expectationOf(comparison, [change], away)).toBeNull();
		expect(expectationOf(COMPARISON, [change], link)).toBeNull();
	});
});

describe('overrideOffers', () => {
	afterEach(() => {
		overrides.list = [];
	});

	const here = { device: 'a-core-01', interface: 'TenGigabitEthernet1/0/1' };
	const onPort = target('port', here.device, here.interface);
	const wrong = finding('wrong', {
		kind: 'wrong-neighbor',
		documented: [here, { device: 'a-acc-01', interface: 'TenGigabitEthernet1/0/49' }],
		seen: [here, { device: 'a-sw-70', interface: 'Gi0/1' }],
		devices: ['a-core-01', 'a-acc-01']
	});

	it('offers another name, one device, or ignoring a neighbor not in the topology', () => {
		expect(overrideOffers(wrong, index)).toEqual([
			{
				label: 'a-sw-70 is a-acc-01…',
				kind: 'alias',
				of: target('device', 'a-acc-01'),
				value: 'a-sw-70'
			},
			{
				label: 'One device on a-core-01 Te1/0/1…',
				kind: 'one-device',
				of: onPort,
				value: 'a-acc-01'
			},
			{
				label: 'Ignore a-sw-70 on a-core-01 Te1/0/1…',
				kind: 'ignore-neighbor',
				of: onPort,
				value: 'a-sw-70'
			}
		]);
	});

	it('offers ignoring an unknown neighbor, and nothing for one in the topology', () => {
		const unknown = finding('unknown', {
			kind: 'unknown-device',
			seen: [here, { device: 'lab-sw-01', interface: 'Gi0/1' }],
			devices: ['a-core-01']
		});
		expect(overrideOffers(unknown, index).map((o) => [o.kind, o.label])).toEqual([
			['ignore-neighbor', 'Ignore lab-sw-01 on a-core-01 Te1/0/1…']
		]);
		const known = { ...wrong, seen: [here, { device: 'a-wan-01', interface: 'Hu1/0/1' }] };
		expect(overrideOffers(known, index)).toEqual([]);
		expect(overrideOffers({ ...wrong, kind: 'wrong-port' }, index)).toEqual([]);
	});

	it('names devices as shown here, keeping their keys as values', () => {
		overrides.list = [
			{
				id: 'o1',
				target: target('device', 'a-acc-01'),
				kind: 'rename',
				key: null,
				value: 'ACC-ONE',
				note: '',
				by: 'Pat',
				at: '2026-11-08T12:00:00Z',
				expires: null,
				state: 'active'
			}
		];
		const [alias, one] = overrideOffers(wrong, index);
		expect([alias?.label, alias?.of.id, one?.value]).toEqual([
			'a-sw-70 is ACC-ONE…',
			'a-acc-01',
			'a-acc-01'
		]);
		expect(portNow(port('a-acc-01', 'Gi1/0/48'))).toBe('ACC-ONE Gi1/0/48: not monitored');
		expect(reviewEffects(review('move', { cut_off: ['a-acc-01'] }))).toEqual([
			'ACC-ONE would have no documented way to the core'
		]);
		const link = index.topology.links.find(
			(l) => l.a.device === 'a-core-01' && l.b && 'device' in l.b && l.b.device === 'a-acc-01'
		)!;
		expect(linkEnds(link)).toMatch(/ – ACC-ONE /);
	});
});
