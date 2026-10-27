import { describe, expect, it } from 'vitest';
import type { Problem } from './api/analysis.ts';
import type { Window } from './api/operations.ts';
import { COMMANDS } from './commands.ts';
import {
	commandEntries,
	ipv4,
	itemEntry,
	problemEntries,
	recentEntries,
	search,
	topologyEntries,
	windowEntries,
	type Group
} from './search.ts';
import { fixture, link } from './test-fixture.ts';
import { indexTopology } from './topology.ts';

// The fixture with addresses, a platform, and a circuit of its own.
const index = indexTopology({
	...structuredClone(fixture),
	devices: fixture.devices.map((d, i) => ({
		...d,
		mgmt_ip: `10.${d.site === 'C' ? 2 : 1}.0.${i + 1}`,
		platform: d.role === 'core' ? 'N9K-C9364C' : 'C9300-48P'
	})),
	links: fixture.links.map((l) =>
		l.id === link('c-wan-01:Gi1/0/2', 'b-wan-01:Gi1/0/1').id
			? { ...l, circuit: { provider: 'Granite Fiber', circuit_id: 'GF-20417' } }
			: l
	)
});
const items = topologyEntries(index);

const labels = (groups: Group[]) => groups.map((g) => [g.label, g.entries.map((e) => e.label)]);
const find = (query: string) => search(query, [items]);
const first = (query: string) => find(query)[0]?.entries[0]?.label;

function problem(id: string, extra: Partial<Problem> = {}): Problem {
	return {
		id,
		kind: 'outage',
		title: 'C cut off',
		detail: '3 devices unreachable',
		target: { kind: 'site', id: 'C' },
		impact: null,
		lost: 3,
		exposed: 0,
		planned: [],
		ack: null,
		...extra
	};
}

describe('search', () => {
	it('finds nothing for nothing', () => {
		expect(find('')).toEqual([]);
		expect(find('   ')).toEqual([]);
	});

	it('puts an exact name first, then names it starts, then words inside names', () => {
		expect(first('c-acc-01')).toBe('c-acc-01');
		expect(labels(find('acc')).find(([l]) => l === 'Devices')).toEqual([
			'Devices',
			['a-acc-01', 'c-acc-01', 'c-acc-02']
		]);
	});

	it('finds a site by code or name before the devices at it', () => {
		const groups = find('c');
		expect(groups[0]?.label).toBe('Sites');
		expect(groups[0]?.entries[0]?.label).toBe('C · Branch C');
		expect(first('branch')).toBe('C · Branch C');
	});

	it('needs every word to match, in any field', () => {
		expect(labels(find('a core'))).toContainEqual(['Devices', ['a-core-01']]);
		expect(find('core n9k').flatMap((g) => g.entries.map((e) => e.label))).toEqual([
			'a-core-01',
			'b-core-01'
		]);
		expect(find('a-core-01 nothing-like-this')).toEqual([]);
	});

	it('finds a device by management address, but only from its start', () => {
		expect(first('10.1.0.2')).toBe('a-core-01');
		expect(find('0.2').flatMap((g) => g.entries)).toEqual([]);
	});

	it('finds the devices in an address range', () => {
		const groups = find('10.2.0.0/16');
		// In address order: c-wan-01 is listed before the access switches.
		expect(labels(groups)).toEqual([['Devices', ['c-wan-01', 'c-acc-01', 'c-acc-02']]]);
		expect(find('10.2.0.0/33')).toEqual([]);
	});

	it('finds a link by its circuit, carrier, or interface in either form', () => {
		expect(first('GF-20417')).toBe('Circuit GF-20417');
		expect(first('granite')).toBe('Circuit GF-20417');
		const byInterface = find('a-core-01 Te1/0/2').find((g) => g.label === 'Links');
		expect(byInterface?.entries.map((e) => e.label)).toEqual([
			'a-core-01 Te1/0/2 – a-acc-01 Te1/0/50'
		]);
		const spelledOut = find('a-core-01 tengigabitethernet1/0/2').find((g) => g.label === 'Links');
		expect(spelledOut?.entries).toEqual(byInterface?.entries);
	});

	it('finds the links in a port channel', () => {
		const group = find('po10').find((g) => g.label === 'Links');
		expect(group?.entries).toHaveLength(2);
	});

	it('finds problems by title, what they are about, and who is on them', () => {
		const problems = problemEntries(index, [
			problem('p1'),
			problem('p2', {
				title: 'Circuit GF-20417 down',
				target: { kind: 'links', ids: [link('c-wan-01:Gi1/0/2', 'b-wan-01:Gi1/0/1').id] },
				ack: { problem: 'p2', note: 'carrier ticket 4411', by: 'Pat', at: '', cleared_at: null }
			})
		]);
		// An exact name beats a problem about it; problems come first among equals.
		expect(search('C', [items, problems]).map((g) => g.label)).toEqual([
			'Sites',
			'Problems',
			'Devices',
			'Links'
		]);
		expect(search('cut off', [items, problems])[0]?.label).toBe('Problems');
		expect(search('branch', [problems]).flatMap((g) => g.entries.map((e) => e.key))).toEqual([
			'p1'
		]);
		expect(search('4411', [problems])[0]?.entries[0]?.key).toBe('p2');
		// Descriptions match at the start of a word: "unreachable" has no "each".
		expect(search('unreach', [problems])[0]?.entries[0]?.key).toBe('p1');
		expect(search('each', [problems])).toEqual([]);
		expect(search('pat', [problems])[0]?.entries[0]?.key).toBe('p2');
	});

	it('finds maintenance by title and by what it works on', () => {
		const windows: Window[] = [
			{
				id: 'w1',
				title: 'Replace supervisor',
				start: '2026-10-27T14:00:00Z',
				end: '2026-10-27T15:00:00Z',
				targets: [{ kind: 'device', id: 'a-core-01' }],
				note: '',
				by: 'Sam',
				saved_at: '2026-10-27T13:00:00Z'
			}
		];
		const entries = windowEntries(index, windows);
		expect(search('supervisor', [entries])[0]?.entries[0]?.key).toBe('w1');
		expect(search('a-core-01', [entries])[0]?.entries[0]?.key).toBe('w1');
	});

	it('finds commands by the start of a word, never inside one', () => {
		const commands = commandEntries(COMMANDS);
		expect(search('hier', [commands])[0]?.entries[0]?.label).toBe('Hierarchy view');
		expect(search('tiers', [commands])[0]?.entries[0]?.label).toBe('Hierarchy view');
		expect(search('erarchy', [commands])).toEqual([]);
	});

	it('lists only the best of many matches, and says how many more there are', () => {
		const many = Array.from({ length: 20 }, (_, i) => ({
			...structuredClone(fixture.devices[0]!),
			name: `x-acc-${i + 1}`
		}));
		const big = indexTopology({
			...structuredClone(fixture),
			devices: [...fixture.devices, ...many]
		});
		const [devices] = search('x-acc', [topologyEntries(big)]);
		expect(devices?.entries).toHaveLength(8);
		expect(devices?.entries[1]?.label).toBe('x-acc-2');
		expect(devices?.more).toBe(12);
	});
});

describe('itemEntry and recentEntries', () => {
	it('describe what was looked at, skipping what is gone', () => {
		const entries = recentEntries(index, ['device:a-core-01', 'device:gone', 'site:B']);
		expect(entries.map((e) => [e.label, e.detail])).toEqual([
			['a-core-01', 'Core · A · 10.1.0.2'],
			['B · Hub B', 'East · 2 devices']
		]);
	});

	it('names a bundle of links by how many there are and the sites they join', () => {
		const ids = index.topology.links.filter((l) => l.kind === 'wan').map((l) => l.id);
		const entry = itemEntry(index, { kind: 'links', ids });
		expect([entry?.label, entry?.detail]).toEqual(['3 links', 'A – B – C']);
	});
});

describe('ipv4', () => {
	it('reads addresses and nothing else', () => {
		expect(ipv4('10.1.0.3')).toBe(10 * 2 ** 24 + 2 ** 16 + 3);
		expect(ipv4('10.1.0')).toBeNull();
		expect(ipv4('10.1.0.256')).toBeNull();
		expect(ipv4('fe80::1')).toBeNull();
	});
});
