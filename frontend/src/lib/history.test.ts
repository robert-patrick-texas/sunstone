import { describe, expect, it } from 'vitest';
import type { DeviceHistory, StateEvent } from './api/state.ts';
import {
	EVENT_CATEGORIES,
	eventRows,
	linkHistory,
	downsBySteps,
	STEP_MS,
	stepEarlier,
	stepLater
} from './history.ts';
import { fixture, fixtureIndex } from './test-fixture.ts';

const T0 = '2026-10-27T15:00:00Z';
const T1 = '2026-10-27T15:05:00Z';
const ALL = new Set(EVENT_CATEGORIES.map((c) => c.category));
const CIRCUIT = 'a-wan-01:Gi1/0/1--c-wan-01:Gi1/0/1';

const events: StateEvent[] = (
	[
		{ at: T0, kind: 'link-down', link: CIRCUIT },
		{ at: T0, kind: 'down', device: 'c-wan-01' },
		{ at: T0, kind: 'down', device: 'c-acc-01' },
		{ at: T0, kind: 'down', device: 'c-acc-02' },
		{ at: T0, kind: 'nodata', device: 'a-acc-01' },
		{ at: T1, kind: 'up', device: 'c-acc-01' },
		{ at: T1, kind: 'congested', link: CIRCUIT, pct: 97.4 }
	] as Omit<StateEvent, 'planned'>[]
).map((e) => ({ ...e, planned: false }));

describe('eventRows', () => {
	it('lists newest first, groups a site that goes down at once, and names links', () => {
		const rows = eventRows(fixtureIndex(), events, ALL);
		expect(rows.map((r) => [r.at, r.title, r.target])).toEqual([
			[T1, 'Circuit ME-1 at 97%', { kind: 'links', ids: [CIRCUIT] }],
			[T1, 'c-acc-01 back up', { kind: 'device', id: 'c-acc-01' }],
			[T0, 'C: 3 devices down', { kind: 'site', id: 'C' }],
			[T0, 'Circuit ME-1 down', { kind: 'links', ids: [CIRCUIT] }],
			[T0, 'a-acc-01 stopped reporting', { kind: 'device', id: 'a-acc-01' }]
		]);
	});

	it('leaves out the categories turned off', () => {
		const rows = eventRows(fixtureIndex(), events, new Set(['links', 'load'] as const));
		expect(rows.map((r) => r.title)).toEqual(['Circuit ME-1 at 97%', 'Circuit ME-1 down']);
	});
});

describe('downsBySteps', () => {
	it('counts devices and links that went down at each step', () => {
		const steps = downsBySteps(events, Date.parse(T0) - STEP_MS);
		expect(Object.fromEntries(steps)).toEqual({ 1: 4 });
	});
});

describe('linkHistory', () => {
	it('reads both directions from whichever end the history is of', () => {
		const link = fixture.links.find((l) => l.id === CIRCUIT)!;
		const history = (device: string, ifname: string): DeviceHistory => ({
			device,
			start: T0,
			step_s: 300,
			status: ['up', 'up'],
			rtt_ms: {},
			loss_pct: {},
			interfaces: [
				{ interface: ifname, oper: ['up', 'down'], in_pct: [10, null], out_pct: [40, null] }
			]
		});
		// The link's A end is c-wan-01.
		expect(linkHistory(history('c-wan-01', 'Gi1/0/1'), link)).toEqual({
			aToB: [40, null],
			bToA: [10, null],
			down: [false, true]
		});
		expect(linkHistory(history('a-wan-01', 'Gi1/0/1'), link)).toEqual({
			aToB: [10, null],
			bToA: [40, null],
			down: [false, true]
		});
	});
});

describe('stepEarlier and stepLater', () => {
	// History runs from 14:02 yesterday to 14:07 today, so its steps run 14:05 to 14:05.
	const span = { since: '2026-10-26T14:02:00.000Z', until: '2026-10-27T14:07:00.000Z' };

	it('step back from now to the latest step, then 5 minutes at a time', () => {
		expect(stepEarlier(null, span)).toBe('2026-10-27T14:05:00.000Z');
		expect(stepEarlier('2026-10-27T14:05:00.000Z', span)).toBe('2026-10-27T14:00:00.000Z');
	});

	it('stop at the start of history', () => {
		expect(stepEarlier('2026-10-26T14:05:00.000Z', span)).toBe('2026-10-26T14:05:00.000Z');
	});

	it('step forward, and back to now after the latest step', () => {
		expect(stepLater('2026-10-27T14:00:00.000Z', span)).toBe('2026-10-27T14:05:00.000Z');
		expect(stepLater('2026-10-27T14:05:00.000Z', span)).toBeNull();
	});

	it('go from the nearest step when a link gives a moment between steps', () => {
		expect(stepEarlier('2026-10-27T13:51:00.000Z', span)).toBe('2026-10-27T13:45:00.000Z');
		expect(stepLater('2026-10-27T13:51:00.000Z', span)).toBe('2026-10-27T13:55:00.000Z');
	});
});
