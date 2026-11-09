import { afterEach, describe, expect, it } from 'vitest';
import type { Problem } from './api/analysis.ts';
import type { HandoverSummary, Outage } from './api/handover.ts';
import type { Override, OverrideLine, OverrideNow } from './api/overrides.ts';
import {
	duration,
	lasted,
	messageText,
	outageSections,
	overrideRow,
	savedLabel,
	selectionOf,
	signedLine,
	standing,
	toSign
} from './handover.ts';
import { overrides } from './overrides.svelte.ts';
import { fixture, fixtureIndex } from './test-fixture.ts';
import { indexTopology } from './topology.ts';

afterEach(() => {
	overrides.list = [];
});

function override(extra: Partial<Override>): Override {
	return {
		id: 'o1',
		target: { kind: 'external', id: 'bravo-iad-1', interface: null },
		kind: 'rename',
		key: null,
		value: 'BRV-IAD-ENC01',
		note: '',
		by: 'Pat',
		at: '2026-10-27T14:00:00Z',
		expires: null,
		renewed: null,
		withdrawn: null,
		...extra
	};
}

/** The rename of bravo-iad-1, a tenant's inline encryptor, applying now. */
const RENAMED: OverrideNow = {
	...override({}),
	state: 'active',
	reason: null,
	topology_value: null
};

function outage(extra: Partial<Outage>): Outage {
	return {
		title: 'x down',
		target: { kind: 'device', id: 'x' },
		devices: ['x'],
		links: [],
		start: '2026-10-27T14:00:00Z',
		end: '2026-10-27T14:35:00Z',
		planned: false,
		...extra
	};
}

describe('duration and lasted', () => {
	it('say how long, in minutes and hours', () => {
		expect(duration(35 * 60_000)).toBe('35 min');
		expect(duration(65 * 60_000)).toBe('1 h 05 min');
		expect(duration(3 * 3_600_000)).toBe('3 h');
	});

	it('say how long an outage lasted, or has so far', () => {
		const now = Date.parse('2026-10-27T15:00:00Z');
		expect(lasted(outage({}), now)).toBe('35 min');
		expect(lasted(outage({ end: null }), now)).toBe('1 h so far');
		expect(lasted(outage({ start: null }), now)).toBe('since before history');
	});
});

describe('outageSections', () => {
	it('sorts outages into sites, links, and single devices', () => {
		const site = outage({ target: { kind: 'site', id: 'HOU' } });
		const link = outage({ target: { kind: 'links', ids: ['l'] } });
		const device = outage({});
		expect(outageSections([device, link, site])).toEqual({
			sites: [site],
			links: [link],
			devices: [device]
		});
	});
});

describe('standing', () => {
	const problem = {
		id: 'p',
		kind: 'outage',
		title: 'HOU cut off',
		detail: '',
		target: { kind: 'site', id: 'HOU' },
		impact: null,
		lost: 0,
		exposed: 0,
		planned: [],
		ack: null,
		team: null,
		urgency: 'high',
		priority: 'medium',
		paging: null,
		networks: []
	} as Problem;

	it('says who is on a problem, or that no one is', () => {
		expect(standing(problem)).toBe('No one on it');
		expect(standing({ ...problem, planned: ['w'] })).toBe('Planned');
		const ack = { problem: 'p', by: 'Pat', note: 'ticket 4411', at: '2026-10-27T15:00:00Z' };
		expect(standing({ ...problem, ack })).toBe('On it: Pat · ticket 4411');
	});
});

describe('saved handovers', () => {
	const saved: HandoverSummary = {
		id: '20261027T1200Z',
		since: '2026-10-27T00:00:00Z',
		until: '2026-10-27T12:00:00Z',
		problems: 6,
		unhandled: 4,
		outages: 34,
		still_down: 2,
		notes: 1,
		signed: null
	};
	const signed = { by: 'Sam', note: '', at: '2026-10-27T12:12:00Z' };

	it('are listed by when they were handed over, how much was open, their notes, and who took over', () => {
		expect(savedLabel(saved)).toMatch(/^Handed over .+:00.* · 6 open, 1 note · not signed for$/);
		expect(savedLabel({ ...saved, notes: 2 })).toMatch(/6 open, 2 notes · /);
		expect(savedLabel({ ...saved, notes: 0 })).toMatch(/6 open · /);
		expect(savedLabel({ ...saved, signed })).toMatch(/1 note · Sam took over$/);
	});

	it('are to sign for while the shift on now has not signed for its own', () => {
		const older = { ...saved, id: '20261027T0000Z' };
		const list = { next: null, timezone: null, current: saved.id, handovers: [saved, older] };
		expect(toSign(list)).toBe(saved);
		expect(toSign({ ...list, handovers: [{ ...saved, signed }, older] })).toBeNull();
		// Only the shift on now signs; an older one no one signed for stays so.
		expect(toSign({ ...list, current: null })).toBeNull();
		expect(toSign(null)).toBeNull();
	});

	it('say who took over, when, and what they said back', () => {
		expect(signedLine(signed)).toMatch(/^Taken over by Sam at .+:12[^·]*$/);
		expect(signedLine({ ...signed, note: 'asked Pat about HOU' })).toMatch(
			/ at .+:12.* · asked Pat about HOU$/
		);
	});

	it('are copied as a message with a link to open them', () => {
		const message = { subject: 'Shift handover 07:00', text: 'Open now (6)' };
		expect(messageText({ message }, 'http://noc/?handover=20261027T1200Z')).toBe(
			'Shift handover 07:00\n\nOpen now (6)\n\nIn Sunstone: http://noc/?handover=20261027T1200Z'
		);
	});

	it('are copied with devices and external nodes by their new names', () => {
		overrides.list = [RENAMED];
		const message = { subject: 'Shift handover 07:00', text: '- dal-gsw-01 – bravo-iad-1 down' };
		expect(messageText({ message }, 'http://noc/?handover=1')).toBe(
			'Shift handover 07:00\n\n- dal-gsw-01 – BRV-IAD-ENC01 down\n\nIn Sunstone: http://noc/?handover=1'
		);
	});
});

describe('overrides in a handover', () => {
	const index = fixtureIndex();
	const LINK = 'c-acc-01:Te1/0/49--c-wan-01:Te1/0/1';

	it('say what happened, by whom, to what, and why', () => {
		const hidden = override({
			target: { kind: 'device', id: 'c-acc-01', interface: null },
			kind: 'hide-status',
			value: null,
			note: 'lab switch',
			withdrawn: { by: 'Sam', at: '2026-10-27T15:00:00Z' }
		});
		const at = '2026-10-27T15:00:00Z';
		const rows = (['made', 'withdrawn', 'expired'] as const).map((event) =>
			overrideRow({ event, at, override: hidden }, index)
		);
		expect(rows.map((r) => [r.event, r.what])).toEqual([
			['Made by Pat', 'c-acc-01 · Hidden from status · lab switch'],
			['Withdrawn by Sam', 'c-acc-01 · Hidden from status · lab switch'],
			['Expired', 'c-acc-01 · Hidden from status · lab switch']
		]);
		expect(rows[0]?.target).toEqual({ kind: 'device', id: 'c-acc-01' });
	});

	it('name their targets as shown, and a link by its ends', () => {
		overrides.list = [
			{
				...RENAMED,
				target: { kind: 'device', id: 'c-acc-01', interface: null },
				value: 'C ACC One'
			}
		];
		const line: OverrideLine = {
			event: 'made',
			at: '2026-10-27T14:00:00Z',
			override: override({
				target: { kind: 'link', id: LINK, interface: null },
				kind: 'tag',
				value: 'lab'
			})
		};
		expect(overrideRow(line, index).what).toBe('c-wan-01 – C ACC One · Tag lab');
		expect(overrideRow(line, null).what).toBe(`${LINK} · Tag lab`);
	});

	it('select what they are on: a port by its device, a port channel by its members', () => {
		const topology = structuredClone(fixture);
		const id = 'a-acc-01:Port-channel10--a-core-01:Port-channel1';
		topology.lags = [
			{
				a: { device: 'a-core-01', interface: 'Port-channel1' },
				b: { device: 'a-acc-01', interface: 'Port-channel10' },
				id
			}
		];
		const layered = indexTopology(topology);
		const of = (kind: Override['target']['kind'], id: string, iface: string | null = null) =>
			selectionOf({ kind, id, interface: iface }, layered);
		expect(of('device', 'c-acc-01')).toEqual({ kind: 'device', id: 'c-acc-01' });
		expect(of('port', 'c-acc-01', 'Te1/0/49')).toEqual({ kind: 'device', id: 'c-acc-01' });
		expect(of('link', LINK)).toEqual({ kind: 'links', ids: [LINK] });
		expect(of('external', 'r1-c')).toEqual({ kind: 'external', id: 'r1-c' });
		expect(of('lag', id)).toEqual({
			kind: 'links',
			ids: [
				'a-acc-01:TenGigabitEthernet1/0/49--a-core-01:TenGigabitEthernet1/0/1',
				'a-acc-01:TenGigabitEthernet1/0/50--a-core-01:TenGigabitEthernet1/0/2'
			]
		});
		expect(of('lag', 'gone')).toBeNull();
	});
});
