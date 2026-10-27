import { describe, expect, it } from 'vitest';
import type { DeviceState, InterfaceState } from './api/state.ts';
import { indexState } from './live.ts';
import { findProblems } from './problems.ts';
import { fixtureIndex } from './test-fixture.ts';

const AT = '2026-10-27T15:00:00Z';
const EARLIER = '2026-10-27T14:50:00Z';

function device(name: string, extra: Partial<DeviceState> = {}): DeviceState {
	const reachability = [{ position: 'west', rtt_ms: 2, loss_pct: 0 }];
	return { device: name, status: 'up', observed_at: AT, stale: false, reachability, ...extra };
}

function reading(dev: string, ifname: string, extra: Partial<InterfaceState> = {}): InterfaceState {
	const base = { oper: 'up' as const, in_pct: 10, out_pct: 20, observed_at: AT, stale: false };
	return { device: dev, interface: ifname, ...base, ...extra };
}

function problemsFor(devices: DeviceState[], interfaces: InterfaceState[]) {
	const live = indexState({
		source: 'test',
		generated_at: AT,
		positions: [{ name: 'west', site: 'A' }],
		devices,
		interfaces
	});
	return findProblems(fixtureIndex(), live);
}

const HUBS = ['a-core-01', 'b-core-01', 'a-wan-01', 'b-wan-01'].map((d) => device(d));

describe('findProblems', () => {
	it('makes one outage of a branch whose router is unreachable', () => {
		const problems = problemsFor(
			[...HUBS, device('c-wan-01', { status: 'down' })],
			[
				reading('a-wan-01', 'Gi1/0/1', { oper: 'down' }),
				reading('b-wan-01', 'Gi1/0/1', { oper: 'down' })
			]
		);
		expect(problems).toHaveLength(1);
		const [outage] = problems;
		expect(outage).toMatchObject({
			kind: 'outage',
			title: 'C cut off',
			detail: '3 devices · 2 circuits ME-1, ME-1 down',
			target: { kind: 'site', id: 'C' },
			lost: 3,
			exposed: 0
		});
		// The router is where reach stops; its unmonitored switches are cut off behind it.
		expect([...(outage?.impact?.failed.devices ?? [])]).toEqual(['c-wan-01']);
		expect([...(outage?.impact?.cutOff ?? [])].sort()).toEqual(['c-acc-01', 'c-acc-02']);
		expect(outage?.impact?.failed.links.size).toBe(2);
	});

	it('ranks a link down, congestion, packet loss, and stale readings, in that order', () => {
		const problems = problemsFor(
			[
				...HUBS.filter((d) => d.device !== 'b-wan-01'),
				device('b-wan-01', { reachability: [{ position: 'west', rtt_ms: 30, loss_pct: 2.5 }] }),
				device('c-wan-01'),
				device('c-acc-01', { stale: true, observed_at: EARLIER })
			],
			[
				reading('a-wan-01', 'Gi1/0/1', { oper: 'down' }),
				reading('c-wan-01', 'Gi1/0/1', { oper: 'down' }),
				reading('a-wan-01', 'Hu1/0/2', { out_pct: 97, in_pct: 12 })
			]
		);
		expect(problems.map((p) => [p.kind, p.title, p.detail])).toEqual([
			[
				'link-down',
				'Circuit ME-1 down',
				'c-wan-01 Gi1/0/1 ↔ a-wan-01 Gi1/0/1 · 1 device left without redundancy'
			],
			['congested', 'Circuit ME-1 at 97%', 'a-wan-01 Hu1/0/2 → b-wan-01 · 100G link'],
			['loss', 'b-wan-01', '2.5% from west'],
			['nodata', 'c-acc-01', 'last reading 10 min before this snapshot']
		]);
		expect(problems[0]?.impact?.exposed.get('c-wan-01')).toEqual(['b-wan-01']);
	});

	it('keeps the same id for a link whether busy or congested', () => {
		const busy = problemsFor(HUBS, [reading('a-wan-01', 'Hu1/0/2', { out_pct: 85 })]);
		const congested = problemsFor(HUBS, [reading('a-wan-01', 'Hu1/0/2', { out_pct: 99 })]);
		expect(busy[0]?.kind).toBe('busy');
		expect(congested[0]?.kind).toBe('congested');
		expect(busy[0]?.id).toBe(congested[0]?.id);
	});

	it('finds nothing wrong when everything is up', () => {
		expect(problemsFor(HUBS, [])).toEqual([]);
	});
});
