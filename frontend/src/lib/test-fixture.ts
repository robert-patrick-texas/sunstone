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
		id: ends.join('--'),
		...extra
	};
}

const wan = { kind: 'wan' as const, circuit: { provider: 'Mesa Carrier', circuit_id: 'ME-1' } };

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
	]
};

export function fixtureIndex(): TopologyIndex {
	return indexTopology(structuredClone(fixture));
}
