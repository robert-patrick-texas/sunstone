import { describe, expect, it } from 'vitest';
import { fixtureIndex } from '../test-fixture.ts';
import { devicePositions, pairKey, sitePairs } from './geojson.ts';

describe('sitePairs', () => {
	it('groups inter-site links by unordered site pair and skips intra-site links', () => {
		const pairs = sitePairs(fixtureIndex());
		const summary = Object.fromEntries(pairs.map((p) => [p.key, p.capacityMbps]));
		expect(summary).toEqual({ 'A|B': 100_000, 'A|C': 1_000, 'B|C': 1_000 });
	});

	it('keys pairs the same way whichever site comes first', () => {
		expect(pairKey('C', 'A')).toBe(pairKey('A', 'C'));
	});
});

describe('devicePositions', () => {
	it('places every device near its own site, each at a distinct point', () => {
		const index = fixtureIndex();
		const positions = devicePositions(index);
		expect(positions.size).toBe(index.topology.devices.length);
		const seen = new Set<string>();
		for (const device of index.topology.devices) {
			const [lon, lat] = positions.get(device.name) ?? [NaN, NaN];
			const site = index.sites.get(device.site);
			expect(Math.abs(lon - (site?.lon ?? 0))).toBeLessThan(0.02);
			expect(Math.abs(lat - (site?.lat ?? 0))).toBeLessThan(0.02);
			seen.add(`${lon},${lat}`);
		}
		expect(seen.size).toBe(positions.size);
	});

	it('puts upper tiers on inner rings', () => {
		const index = fixtureIndex();
		const positions = devicePositions(index);
		const site = index.sites.get('A');
		const distance = (name: string) => {
			const [lon, lat] = positions.get(name) ?? [0, 0];
			return Math.hypot(lon - (site?.lon ?? 0), lat - (site?.lat ?? 0));
		};
		expect(distance('a-wan-01')).toBeLessThan(distance('a-core-01'));
		expect(distance('a-core-01')).toBeLessThan(distance('a-acc-01'));
	});
});
