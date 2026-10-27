import { describe, expect, it } from 'vitest';
import { linksBetween, MAX_LISTED, shortestPaths } from './paths.ts';
import { fixture, fixtureIndex, link } from './test-fixture.ts';
import { indexTopology } from './topology.ts';

describe('shortestPaths', () => {
	it('follows the one path across sites, counting a LAG as one hop', () => {
		const path = shortestPaths(fixtureIndex(), 'c-acc-01', 'a-acc-01');
		expect(path.hops).toBe(4);
		expect(path.count).toBe(1);
		expect(path.listed).toEqual([['c-acc-01', 'c-wan-01', 'a-wan-01', 'a-core-01', 'a-acc-01']]);
		// Both LAG members between a-core-01 and a-acc-01 are on the path.
		expect(path.links.size).toBe(5);
		expect(Object.fromEntries(path.devices)).toEqual({
			'c-acc-01': 0,
			'c-wan-01': 1,
			'a-wan-01': 2,
			'a-core-01': 3,
			'a-acc-01': 4
		});
	});

	it('finds every equally short path', () => {
		const topology = structuredClone(fixture);
		topology.links.push(link('a-core-01:Hu1/0/9', 'b-core-01:Hu1/0/9', 100_000));
		const path = shortestPaths(indexTopology(topology), 'a-core-01', 'b-wan-01');
		expect(path.hops).toBe(2);
		expect(path.count).toBe(2);
		expect(path.listed).toEqual([
			['a-core-01', 'a-wan-01', 'b-wan-01'],
			['a-core-01', 'b-core-01', 'b-wan-01']
		]);
	});

	it('counts paths beyond the ones it lists', () => {
		// A ladder of diamonds doubles the number of paths at every rung.
		const topology = structuredClone(fixture);
		const devices = ['s'];
		for (let rung = 1; rung <= 5; rung++) {
			devices.push(`l${rung}`, `r${rung}`, `m${rung}`);
		}
		for (const name of devices) topology.devices.push({ name, site: 'A', role: 'access' });
		let top = 's';
		for (let rung = 1; rung <= 5; rung++) {
			for (const side of ['l', 'r']) {
				topology.links.push(link(`${top}:down-${side}${rung}`, `${side}${rung}:up`));
				topology.links.push(link(`${side}${rung}:down`, `m${rung}:up-${side}`));
			}
			top = `m${rung}`;
		}
		const path = shortestPaths(indexTopology(topology), 's', 'm5');
		expect(path.count).toBe(32);
		expect(path.listed).toHaveLength(MAX_LISTED);
	});

	it('reports devices that are not connected', () => {
		const topology = structuredClone(fixture);
		topology.devices.push({ name: 'island', site: 'A', role: 'access' });
		const path = shortestPaths(indexTopology(topology), 'a-acc-01', 'island');
		expect([path.hops, path.count, path.devices.size]).toEqual([null, 0, 0]);
	});

	it('treats a device as a zero-hop path to itself', () => {
		const path = shortestPaths(fixtureIndex(), 'a-acc-01', 'a-acc-01');
		expect([path.hops, path.count, path.listed]).toEqual([0, 1, [['a-acc-01']]]);
	});
});

describe('linksBetween', () => {
	it('returns every LAG member in interface order', () => {
		const index = fixtureIndex();
		const path = shortestPaths(index, 'c-acc-01', 'a-acc-01');
		const ends = linksBetween(index, path, 'a-core-01', 'a-acc-01').map((l) => l.a.interface);
		expect(ends).toEqual(['TenGigabitEthernet1/0/1', 'TenGigabitEthernet1/0/2']);
	});
});
