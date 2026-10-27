import { describe, expect, it } from 'vitest';
import { fixtureIndex } from '../test-fixture.ts';
import type { NetworkState } from '../api/state.ts';
import type { Impact } from '../impact.ts';
import { indexState } from '../live.ts';
import {
	deviceFeatures,
	devicePositions,
	linkFeatures,
	pairKey,
	siteFeatures,
	sitePairs
} from './geojson.ts';

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

describe('live properties', () => {
	const AT = '2026-10-27T15:00:00Z';
	const state: NetworkState = {
		source: 'test',
		generated_at: AT,
		positions: [],
		devices: [
			{ device: 'c-wan-01', status: 'up', observed_at: AT, stale: false, reachability: [] },
			{ device: 'c-acc-01', status: 'down', observed_at: AT, stale: false, reachability: [] }
		],
		interfaces: [
			{
				device: 'c-wan-01',
				interface: 'Te1/0/2',
				oper: 'up',
				in_pct: 5,
				out_pct: 30,
				observed_at: AT,
				stale: false
			}
		]
	};

	it('are absent without live state', () => {
		const index = fixtureIndex();
		const props = deviceFeatures(index, devicePositions(index)).features[0]?.properties;
		expect(props).toEqual({ name: 'a-wan-01', role: 'wan-edge' });
	});

	it('give devices their health and glyph, and sites their worst health', () => {
		const index = fixtureIndex();
		const live = indexState(state);
		const devices = deviceFeatures(index, devicePositions(index), live).features;
		const byName = Object.fromEntries(devices.map((f) => [f.properties?.['name'], f.properties]));
		expect(byName['c-acc-01']).toMatchObject({ health: 'down', glyph: '×' });
		expect(byName['c-wan-01']).toMatchObject({ health: 'up' });
		expect(byName['c-wan-01']).not.toHaveProperty('glyph');
		const site = siteFeatures(index, live).features.find((f) => f.properties?.['code'] === 'C');
		expect(site?.properties).toMatchObject({ health: 'down', label: 'C · 1 down' });
	});

	it('give way to an impact, which marks only what it touches', () => {
		const index = fixtureIndex();
		const live = indexState(state);
		// c-wan-01 fails, cutting off branch C's switches.
		const impact: Impact = {
			failed: { devices: new Set(['c-wan-01']), links: new Set() },
			cutOff: new Set(['c-acc-01', 'c-acc-02']),
			exposed: new Map()
		};
		const devices = deviceFeatures(index, devicePositions(index), live, impact).features;
		const byName = Object.fromEntries(devices.map((f) => [f.properties?.['name'], f.properties]));
		expect(byName['c-wan-01']).toMatchObject({ impact: 'failed', glyph: '×' });
		// c-acc-01 is down in live state, but here it is cut off, which has no glyph.
		expect(byName['c-acc-01']).toMatchObject({ impact: 'cutoff' });
		expect(byName['c-acc-01']).not.toHaveProperty('glyph');
		expect(byName['a-wan-01']).not.toHaveProperty('impact');
		const site = siteFeatures(index, live, impact).features.find(
			(f) => f.properties?.['code'] === 'C'
		);
		expect(site?.properties).toMatchObject({ impact: 'failed', label: 'C · 3 lost' });
		const lines = linkFeatures(index.topology.links, devicePositions(index), live, impact).features;
		const lost = lines.filter((f) => f.properties?.['impact'] === 'lost');
		expect(lost).toHaveLength(4);
	});

	it('leave load off links with no measurement instead of writing 0', () => {
		const index = fixtureIndex();
		const live = indexState(state);
		const lines = linkFeatures(index.topology.links, devicePositions(index), live).features;
		const byId = Object.fromEntries(lines.map((f) => [f.properties?.['id'], f.properties]));
		expect(byId['c-acc-02:Te1/0/49--c-wan-01:Te1/0/2']).toMatchObject({ health: 'ok', util: 30 });
		const core = byId['a-acc-01:TenGigabitEthernet1/0/49--a-core-01:TenGigabitEthernet1/0/1'];
		expect(core).toMatchObject({ health: 'unmonitored' });
		expect(core).not.toHaveProperty('util');
	});
});
