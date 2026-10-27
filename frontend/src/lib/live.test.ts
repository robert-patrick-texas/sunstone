import { describe, expect, it } from 'vitest';
import type { DeviceState, InterfaceState, NetworkState } from './api/state.ts';
import {
	bundleLive,
	deviceHealth,
	groupHealth,
	indexState,
	linkLive,
	type LinkLive
} from './live.ts';
import { fixture } from './test-fixture.ts';

const AT = '2026-10-27T15:00:00Z';

function device(name: string, extra: Partial<DeviceState> = {}): DeviceState {
	const reachability = [{ position: 'west', rtt_ms: 2, loss_pct: 0 }];
	return { device: name, status: 'up', observed_at: AT, stale: false, reachability, ...extra };
}

function reading(dev: string, ifname: string, extra: Partial<InterfaceState> = {}) {
	const base = { oper: 'up' as const, in_pct: 10, out_pct: 40, observed_at: AT, stale: false };
	return { device: dev, interface: ifname, ...base, ...extra };
}

function live(devices: DeviceState[], interfaces: InterfaceState[]) {
	const state: NetworkState = {
		source: 'test',
		generated_at: AT,
		positions: [{ name: 'west', site: 'A' }],
		devices,
		interfaces
	};
	return indexState(state);
}

// c-wan-01:Te1/0/1 (A end) to c-acc-01:Te1/0/49 (B end)
const LINK = fixture.links.find((l) => l.a.interface === 'Te1/0/1' && l.a.device === 'c-wan-01')!;

describe('deviceHealth', () => {
	it('tells every state apart, and never treats missing data as up', () => {
		const index = live(
			[
				device('up'),
				device('lossy', { reachability: [{ position: 'west', rtt_ms: 3, loss_pct: 2 }] }),
				device('down', { status: 'down' }),
				device('stale', { stale: true, status: 'down' })
			],
			[]
		);
		expect(
			['up', 'lossy', 'down', 'stale', 'elsewhere'].map((d) => deviceHealth(index, d))
		).toEqual(['up', 'degraded', 'down', 'nodata', 'unmonitored']);
	});
});

describe('linkLive', () => {
	it('reads both directions from the A end', () => {
		const index = live([device('c-wan-01')], [reading('c-wan-01', 'Te1/0/1')]);
		expect(linkLive(index, LINK)).toEqual({ health: 'ok', aToB: 40, bToA: 10, utilPct: 40 });
	});

	it('reads them from the B end when only B is monitored, flipping in and out', () => {
		const index = live([device('c-acc-01')], [reading('c-acc-01', 'Te1/0/49')]);
		expect(linkLive(index, LINK)).toEqual({ health: 'ok', aToB: 10, bToA: 40, utilPct: 40 });
	});

	it('is unmonitored when neither end is watched', () => {
		expect(linkLive(live([], []), LINK).health).toBe('unmonitored');
	});

	it('has no data, not zero load, when the only readings are stale', () => {
		const index = live(
			[device('c-wan-01', { stale: true })],
			[reading('c-wan-01', 'Te1/0/1', { stale: true })]
		);
		expect(linkLive(index, LINK)).toEqual({
			health: 'nodata',
			aToB: null,
			bToA: null,
			utilPct: null
		});
	});

	it('is down when either device is down or an end reports it down', () => {
		expect(linkLive(live([device('c-acc-01', { status: 'down' })], []), LINK).health).toBe('down');
		const oper = live([device('c-wan-01')], [reading('c-wan-01', 'Te1/0/1', { oper: 'down' })]);
		expect(linkLive(oper, LINK).health).toBe('down');
	});
});

describe('bundleLive', () => {
	const ok = (pct: number): LinkLive => ({ health: 'ok', aToB: pct, bToA: 0, utilPct: pct });
	const down: LinkLive = { health: 'down', aToB: null, bToA: null, utilPct: null };
	const nodata: LinkLive = { health: 'nodata', aToB: null, bToA: null, utilPct: null };

	it('shows the busiest link', () => {
		expect(bundleLive([ok(20), ok(70)])).toEqual({ health: 'ok', utilPct: 70 });
	});

	it('is partial when only some links are down, down when all are', () => {
		expect(bundleLive([ok(20), down])).toEqual({ health: 'partial', utilPct: 20 });
		expect(bundleLive([down, down])).toEqual({ health: 'down', utilPct: null });
	});

	it('has no data when nothing is measured but something is watched', () => {
		expect(bundleLive([nodata])).toEqual({ health: 'nodata', utilPct: null });
	});
});

describe('groupHealth', () => {
	it('reports the worst device and counts each state', () => {
		const index = live([device('a'), device('b', { status: 'down' })], []);
		const { health, counts } = groupHealth(index, ['a', 'b', 'c']);
		expect(health).toBe('down');
		expect(counts).toEqual({ up: 1, degraded: 0, down: 1, nodata: 0, unmonitored: 1 });
	});
});
