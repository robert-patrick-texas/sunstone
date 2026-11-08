/**
 * A tiny topology for unit tests: hubs A and B (with a core tier) and
 * branch C, which is dual-homed to both hubs over WAN links.
 */
import type { Link, Topology } from './api/topology.ts';
import { indexTopology, type TopologyIndex } from './topology.ts';

export function link(a: string, b: string, speed = 10_000, extra: Partial<Link> = {}): Link {
	const [ad, ai] = a.split(':') as [string, string];
	const [bd, bi] = b.split(':') as [string, string];
	const ends = [`${ad}:${ai}`, `${bd}:${bi}`].sort();
	return {
		a: { device: ad, interface: ai },
		b: { device: bd, interface: bi },
		speed_mbps: speed,
		kind: 'lan',
		carries: [],
		edges: [],
		neighbors: [],
		id: ends.join('--'),
		...extra
	};
}

const wan = {
	kind: 'wan' as const,
	circuit: {
		provider: 'Mesa Carrier',
		circuit_id: { a: 'ME-1', z: 'ME-1' },
		type: 'carrier' as const
	}
};

export const fixture: Topology = {
	sites: [
		{ code: 'A', name: 'Hub A', region: 'South', lat: 32.8, lon: -96.8 },
		{ code: 'B', name: 'Hub B', region: 'East', lat: 39.0, lon: -77.5 },
		{ code: 'C', name: 'Branch C', region: 'South', lat: 29.8, lon: -95.4 }
	],
	devices: [
		{ name: 'a-wan-01', site: 'A', role: 'wan-edge' },
		{ name: 'a-core-01', site: 'A', role: 'core' },
		{ name: 'a-acc-01', site: 'A', role: 'access' },
		{ name: 'b-wan-01', site: 'B', role: 'wan-edge' },
		{ name: 'b-core-01', site: 'B', role: 'core' },
		{ name: 'c-wan-01', site: 'C', role: 'wan-edge' },
		{ name: 'c-acc-01', site: 'C', role: 'access' },
		{ name: 'c-acc-02', site: 'C', role: 'access' }
	],
	links: [
		link('a-wan-01:Hu1/0/1', 'a-core-01:Hu1/0/1', 100_000),
		{
			...link('a-core-01:TenGigabitEthernet1/0/1', 'a-acc-01:TenGigabitEthernet1/0/49'),
			a: { device: 'a-core-01', interface: 'TenGigabitEthernet1/0/1', lag: 'Port-channel1' },
			b: { device: 'a-acc-01', interface: 'TenGigabitEthernet1/0/49', lag: 'Port-channel10' }
		},
		{
			...link('a-core-01:TenGigabitEthernet1/0/2', 'a-acc-01:TenGigabitEthernet1/0/50'),
			a: { device: 'a-core-01', interface: 'TenGigabitEthernet1/0/2', lag: 'Port-channel1' },
			b: { device: 'a-acc-01', interface: 'TenGigabitEthernet1/0/50', lag: 'Port-channel10' }
		},
		link('b-wan-01:Hu1/0/1', 'b-core-01:Hu1/0/1', 100_000),
		link('a-wan-01:Hu1/0/2', 'b-wan-01:Hu1/0/2', 100_000, wan),
		link('c-wan-01:Gi1/0/1', 'a-wan-01:Gi1/0/1', 1_000, wan),
		link('c-wan-01:Gi1/0/2', 'b-wan-01:Gi1/0/1', 1_000, wan),
		link('c-wan-01:Te1/0/1', 'c-acc-01:Te1/0/49'),
		link('c-wan-01:Te1/0/2', 'c-acc-02:Te1/0/49')
	],
	regions: [],
	locations: [],
	networks: [],
	transports: [],
	externals: [],
	tenants: [],
	tunnels: [],
	fabrics: [],
	lags: [],
	terms: {}
};

export function fixtureIndex(): TopologyIndex {
	return indexTopology(structuredClone(fixture));
}

const inet = (device: string, id: string): Link => ({
	a: { device, interface: 'GigabitEthernet0/0/0' },
	b: { transport: 'INET' },
	speed_mbps: 500,
	kind: 'wan',
	circuit: { provider: 'Northwind Fiber', circuit_id: { a: id, z: null }, type: 'carrier' },
	carries: [],
	edges: [],
	neighbors: [],
	id: `${device}:GigabitEthernet0/0/0--transport:INET`
});

/**
 * The tiny topology with layers over it: hub A and branch C on the Internet;
 * blue over black between them, grey over blue, and tenant T1's red network
 * over grey through its encryptor at C; a DMVPN fabric with hubs A and B;
 * and an application reached over the Internet.
 */
export const layeredFixture: Topology = {
	...fixture,
	links: [
		...fixture.links,
		inet('a-wan-01', 'NO-1'),
		inet('c-wan-01', 'NO-2'),
		{
			a: { device: 'c-acc-02', interface: 'Gi1/0/9' },
			b: { external: 'r1-c', interface: 'black' },
			speed_mbps: 1_000,
			kind: 'lan',
			carries: [{ network: 'grey', vlan: 200 }],
			edges: [],
			neighbors: [],
			id: 'c-acc-02:Gi1/0/9--external:r1-c:black'
		}
	],
	networks: [
		{ name: 'black', boundary: 'outside', rides: [], anchors: [], regions: {}, tags: [] },
		{ name: 'blue', boundary: 'inside', rides: [], anchors: [], regions: {}, tags: [] },
		{ name: 'grey', boundary: 'inside', rides: [], anchors: [], regions: {}, tags: [] },
		{ name: 'corp', boundary: 'inside', rides: [], anchors: [], regions: {}, tags: [] },
		{
			name: 'red',
			boundary: 'inside',
			tenant: 'T1',
			rides: ['grey'],
			anchors: [],
			regions: {},
			tags: []
		}
	],
	transports: [{ name: 'INET', kind: 'internet', network: 'black', tags: [] }],
	externals: [
		{ name: 'r1-c', kind: 'tenant', tenant: 'T1', network: 'red', reached_over: [], tags: [] },
		{ name: 'Nimbus Cloud', kind: 'application', reached_over: ['INET'], tags: [] }
	],
	tenants: [{ name: 'T1' }],
	tunnels: [
		{
			name: 'BLUE-A-C',
			network: 'blue',
			rides: 'black',
			kind: 'ip',
			a: { device: 'a-wan-01', interface: 'Tunnel10', source: 'Loopback0' },
			b: { device: 'c-wan-01', interface: 'Tunnel10', source: 'Loopback0' },
			tags: [],
			edges: []
		},
		{
			name: 'GREY-A-C',
			network: 'grey',
			rides: 'blue',
			kind: 'ip',
			a: { device: 'a-acc-01', interface: 'Tunnel20' },
			b: { device: 'c-acc-02', interface: 'Tunnel20' },
			tags: ['secure'],
			edges: []
		}
	],
	fabrics: [
		{
			name: 'DMVPN',
			network: 'corp',
			rides: 'black',
			shape: 'hub-spoke-dynamic',
			members: [
				{ device: 'a-wan-01', interface: 'Tunnel100', role: 'hub' },
				{ device: 'b-wan-01', interface: 'Tunnel100', role: 'hub' },
				{ device: 'c-wan-01', interface: 'Tunnel100', role: 'spoke' }
			],
			tags: [],
			edges: []
		}
	],
	terms: {}
};

export function layeredIndex(): TopologyIndex {
	return indexTopology(structuredClone(layeredFixture));
}
