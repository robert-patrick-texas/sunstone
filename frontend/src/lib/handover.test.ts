import { describe, expect, it } from 'vitest';
import type { Problem } from './api/analysis.ts';
import type { HandoverSummary, Outage } from './api/handover.ts';
import { duration, lasted, messageText, outageSections, savedLabel, standing } from './handover.ts';

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
		paging: null
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
		notes: 1
	};

	it('are listed by when they were handed over, how much was open, and their notes', () => {
		expect(savedLabel(saved)).toMatch(/^Handed over .+:00.* · 6 open, 1 note$/);
		expect(savedLabel({ ...saved, notes: 2 })).toMatch(/6 open, 2 notes$/);
		expect(savedLabel({ ...saved, notes: 0 })).toMatch(/6 open$/);
	});

	it('are copied as a message with a link to open them', () => {
		const message = { subject: 'Shift handover 07:00', text: 'Open now (6)' };
		expect(messageText({ message }, 'http://noc/?handover=20261027T1200Z')).toBe(
			'Shift handover 07:00\n\nOpen now (6)\n\nIn Sunstone: http://noc/?handover=20261027T1200Z'
		);
	});
});
