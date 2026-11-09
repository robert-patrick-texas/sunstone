import { afterEach, describe, expect, it } from 'vitest';
import type { Problem } from './api/analysis.ts';
import type { Window } from './api/operations.ts';
import type { OverrideNow, Target } from './api/overrides.ts';
import { COMMANDS } from './commands.ts';
import { lagId, overrides, target } from './overrides.svelte.ts';
import {
	commandEntries,
	groupLabels,
	ipv4,
	itemEntry,
	problemEntries,
	recentEntries,
	search,
	topologyEntries,
	windowEntries,
	type Group
} from './search.ts';
import { fixture, layeredFixture, link } from './test-fixture.ts';
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
			? {
					...l,
					circuit: {
						provider: 'Granite Fiber',
						circuit_id: { a: 'GF-20417', z: 'GF-20417' },
						type: 'carrier' as const
					}
				}
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
		team: null,
		urgency: 'high',
		priority: 'medium',
		paging: null,
		networks: [],
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

describe('networks and what is layered over the links', () => {
	const layered = indexTopology({
		...structuredClone(layeredFixture),
		terms: { tenant: 'Customer' }
	});
	const entries = topologyEntries(layered);
	const look = (query: string) => search(query, [entries], groupLabels(layered));

	it('finds a network, a tunnel by its tag, and a fabric', () => {
		expect(labels(look('grey')).slice(0, 2)).toEqual([
			['Networks', ['grey']],
			['Tunnels', ['GREY-A-C']]
		]);
		expect(look('secure')[0]?.entries[0]?.target).toEqual({
			kind: 'item',
			item: { kind: 'tunnel', id: 'GREY-A-C' }
		});
		expect(look('dmvpn')[0]?.entries[0]?.detail).toBe('corp · 3 members · 2 tunnels');
	});

	it("finds tenants by Sunstone's word and the organization's, under its word", () => {
		for (const word of ['tenant', 'customer']) {
			expect(labels(look(word))).toContainEqual(['Customers', ['T1']]);
		}
	});

	it('finds a circuit into a transport by the transport', () => {
		const found = look('inet NO-2');
		expect(labels(found)).toEqual([['Links', ['Circuit NO-2']]]);
		expect(found[0]?.entries[0]?.detail).toBe('Northwind Fiber · c-wan-01 – INET · 500M · TBD');
	});
});

describe('resources and priorities', () => {
	const t = structuredClone(layeredFixture);
	t.links = t.links.map((l) =>
		l.circuit?.circuit_id.a === 'NO-1'
			? { ...l, enterprise_cid: { a: 'A-INET-01', z: null }, priority: 'high' as const }
			: l.id === link('c-wan-01:Te1/0/1', 'c-acc-01:Te1/0/49').id
				? { ...l, priority: 'medium' as const }
				: l
	);
	t.devices = t.devices.map((d) => (d.name === 'b-core-01' ? { ...d, priority: 'high' } : d));
	t.resources = [
		{
			name: 'Global Access',
			description: 'Ways out to the world',
			tags: ['tic'],
			circuits: ['A-INET-01'],
			tunnels: [],
			fabrics: [],
			resources: []
		}
	];
	const layered = indexTopology(t);
	const look = (query: string) => search(query, [topologyEntries(layered)], groupLabels(layered));

	it('finds a resource by name, tag, or a word of its description, and selects it', () => {
		for (const query of ['global', 'tic', 'world']) {
			expect(labels(look(query))).toEqual([['Resources', ['Global Access']]]);
		}
		const [found] = look('tic')[0]?.entries ?? [];
		expect(found?.detail).toBe('Ways out to the world · 1 member');
		expect(found?.target).toEqual({
			kind: 'item',
			item: { kind: 'resource', id: 'Global Access' }
		});
	});

	it('finds links and devices by priority, defaults included', () => {
		expect(labels(look('high priority'))).toEqual([
			['Devices', ['b-core-01']],
			['Links', ['b-wan-01 Hu1/0/1 – b-core-01 Hu1/0/1', 'Circuit A-INET-01']]
		]);
		// The tenant's encryptor is low for access, by default.
		expect(labels(look('low'))).toEqual([['Links', ['c-acc-02 Gi1/0/9 – r1-c black']]]);
	});

	it('finds medium only where it is set, not by default', () => {
		expect(labels(look('medium'))).toEqual([['Links', ['c-wan-01 Te1/0/1 – c-acc-01 Te1/0/49']]]);
	});
});

describe('overrides', () => {
	afterEach(() => {
		overrides.list = [];
	});

	let next = 0;
	function made(of: Target, kind: OverrideNow['kind'], more: Partial<OverrideNow> = {}) {
		next += 1;
		return {
			id: `o${next}`,
			target: of,
			kind,
			key: null,
			value: null,
			note: '',
			by: 'Pat',
			at: '2026-11-08T12:00:00Z',
			expires: null,
			renewed: null,
			withdrawn: null,
			state: 'active',
			reason: null,
			topology_value: null,
			...more
		} satisfies OverrideNow;
	}

	const layered = indexTopology(structuredClone(layeredFixture));
	// Entries are built after the overrides are set, as the search box does.
	const look = (query: string, on = index) =>
		labels(search(query, [topologyEntries(on)], groupLabels(on)));

	it('finds a device by an alias, and shows it by its name', () => {
		overrides.list = [made(target('device', 'c-acc-01'), 'alias', { value: 'c-sw-70' })];
		expect(look('c-sw-70')).toEqual([['Devices', ['c-acc-01']]]);
	});

	it('finds a renamed device by either name, and shows it and its links by the new one', () => {
		overrides.list = [made(target('device', 'a-acc-01'), 'rename', { value: 'A-ACC-ONE' })];
		expect(look('a-acc-one')[0]).toEqual(['Devices', ['A-ACC-ONE']]);
		expect(look('a-acc-01')[0]).toEqual(['Devices', ['A-ACC-ONE']]);
		expect(look('A-ACC-ONE Te1/0/50')).toContainEqual([
			'Links',
			['a-core-01 Te1/0/2 – A-ACC-ONE Te1/0/50']
		]);
	});

	it('finds a renamed external node and the link to it by the new name', () => {
		overrides.list = [made(target('external', 'r1-c'), 'rename', { value: 'R1-ENC01' })];
		expect(look('r1-enc01', layered)).toEqual([
			['Externals', ['R1-ENC01']],
			['Links', ['c-acc-02 Gi1/0/9 – R1-ENC01 black']]
		]);
	});

	it("finds a site by an alias, and problems about a device by the device's new name", () => {
		overrides.list = [
			made(target('site', 'C'), 'alias', { value: 'Houston' }),
			made(target('device', 'c-wan-01'), 'rename', { value: 'C-EDGE' })
		];
		expect(look('houston')).toEqual([['Sites', ['C · Branch C']]]);
		const problems = problemEntries(index, [
			problem('p1', { title: 'c-wan-01 down', target: { kind: 'device', id: 'c-wan-01' } })
		]);
		expect(labels(search('c-edge', [problems]))).toEqual([['Problems', ['C-EDGE down']]]);
	});

	it('finds anything by tags and labels added here, a label by key:value or its value', () => {
		const member = link('a-core-01:TenGigabitEthernet1/0/1', 'a-acc-01:TenGigabitEthernet1/0/49');
		const channel = {
			a: { device: 'a-core-01', interface: 'Port-channel1' },
			b: { device: 'a-acc-01', interface: 'Port-channel10' },
			id: 'a-acc-01:Port-channel10--a-core-01:Port-channel1'
		};
		const bundled = indexTopology({ ...structuredClone(fixture), lags: [channel] });
		overrides.list = [
			made(target('device', 'a-acc-01'), 'tag', { value: 'lab' }),
			made(target('link', member.id), 'label', { key: 'rack', value: 'B12' }),
			made(target('tunnel', 'GREY-A-C'), 'label', { key: 'owner', value: 'noc' }),
			made(target('lag', lagId(channel)), 'tag', { value: 'bundle' })
		];
		expect(look('lab')).toEqual([['Devices', ['a-acc-01']]]);
		for (const query of ['rack:b12', 'b12']) {
			expect(look(query)).toEqual([['Links', ['a-core-01 Te1/0/1 – a-acc-01 Te1/0/49']]]);
		}
		expect(look('owner:noc', layered)).toEqual([['Tunnels', ['GREY-A-C']]]);
		expect(look('bundle', bundled)).toEqual([['Links', ['Port channel Po1']]]);
	});

	it('leaves out what does not apply now', () => {
		overrides.list = [
			made(target('device', 'a-acc-01'), 'tag', { value: 'lab', state: 'expired' }),
			made(target('device', 'a-acc-01'), 'alias', { value: 'old-name', state: 'not-applied' })
		];
		expect(look('lab')).toEqual([]);
		expect(look('old-name')).toEqual([]);
	});
});
