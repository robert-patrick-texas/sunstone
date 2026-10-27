import { describe, expect, it } from 'vitest';
import { fixtureIndex } from './test-fixture.ts';
import { formatSpeed, neighborsOf, shortInterface } from './topology.ts';

describe('shortInterface', () => {
	it.each([
		['TenGigabitEthernet1/0/1', 'Te1/0/1'],
		['HundredGigE1/0/3', 'Hu1/0/3'],
		['GigabitEthernet0/0/0', 'Gi0/0/0'],
		['Port-channel10', 'Po10'],
		['mgmt0', 'mgmt0']
	])('%s → %s', (name, short) => expect(shortInterface(name)).toBe(short));
});

describe('formatSpeed', () => {
	it.each([
		[100, '100M'],
		[1_000, '1G'],
		[2_500, '2.5G'],
		[220_000, '220G'],
		[1_200_000, '1.2T']
	])('%d → %s', (mbps, text) => expect(formatSpeed(mbps)).toBe(text));
});

describe('neighborsOf', () => {
	it('orients each link with the device own end first, in interface order', () => {
		const rows = neighborsOf(fixtureIndex(), 'c-wan-01');
		expect(rows.map((r) => [r.local.interface, r.remote.device])).toEqual([
			['Gi1/0/1', 'a-wan-01'],
			['Gi1/0/2', 'b-wan-01'],
			['Te1/0/1', 'c-acc-01'],
			['Te1/0/2', 'c-acc-02']
		]);
	});

	it('works when the device is the b end', () => {
		const rows = neighborsOf(fixtureIndex(), 'a-acc-01');
		expect(rows.map((r) => r.local.lag)).toEqual(['Port-channel10', 'Port-channel10']);
		expect(rows.every((r) => r.remote.device === 'a-core-01')).toBe(true);
	});
});

describe('indexTopology', () => {
	it('orders each site top tier first', () => {
		const names = fixtureIndex()
			.devicesBySite.get('A')
			?.map((d) => d.name);
		expect(names).toEqual(['a-wan-01', 'a-core-01', 'a-acc-01']);
	});
});
