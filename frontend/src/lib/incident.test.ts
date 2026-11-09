import { afterEach, describe, expect, it } from 'vitest';
import type { IncidentSummary } from './api/incidents.ts';
import type { OverrideNow } from './api/overrides.ts';
import { first, incidentLabel, into, lasted, postmortemText } from './incident.ts';
import { overrides } from './overrides.svelte.ts';

afterEach(() => {
	overrides.list = [];
});

/** bravo-iad-1, a tenant's inline encryptor, renamed. */
const RENAMED: OverrideNow = {
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
	state: 'active',
	reason: null,
	topology_value: null
};

function incident(extra: Partial<IncidentSummary>): IncidentSummary {
	return {
		number: 1,
		title: 'HOU cut off',
		status: 'open',
		began: '2026-10-27T15:00:00Z',
		opened_at: '2026-10-27T15:07:00Z',
		opened_by: 'Pat',
		cleared_at: null,
		closed_at: null,
		problems: ['outage:hou-wan-01'],
		...extra
	};
}

describe('incidents', () => {
	it('are listed by number, title, and where they stand', () => {
		expect(incidentLabel(incident({ number: 12 }))).toBe('12 · HOU cut off · open');
	});

	it('last from when they began until they clear', () => {
		const now = Date.parse('2026-10-27T15:35:00Z');
		expect(lasted(incident({}), now)).toBe('35 min so far');
		expect(lasted(incident({ cleared_at: '2026-10-27T16:05:00Z' }), now)).toBe('1 h 05 min');
		expect(lasted(incident({ began: null }), now)).toBeNull();
		expect(into(incident({}), '2026-10-27T15:07:00Z')).toBe('7 min in');
		expect(into(incident({ began: null }), '2026-10-27T15:07:00Z')).toBeNull();
	});

	it('open on the newest not yet closed, else the newest', () => {
		const closed = incident({ number: 3, status: 'closed' });
		expect(first([closed, incident({ number: 2, status: 'cleared' }), incident({})])).toBe(2);
		expect(first([closed])).toBe(3);
		expect(first([])).toBeNull();
	});

	it('are copied as a postmortem with a link to open them', () => {
		const message = { subject: 'Incident 1: HOU cut off', text: 'Problems (1)' };
		expect(postmortemText({ message }, 'http://noc/?incident=1')).toBe(
			'Incident 1: HOU cut off\n\nProblems (1)\n\nIn Sunstone: http://noc/?incident=1'
		);
	});

	it('are listed and copied with devices and external nodes by their new names', () => {
		overrides.list = [RENAMED];
		const title = 'dal-gsw-01 – bravo-iad-1 down';
		expect(incidentLabel(incident({ number: 4, title }))).toBe(
			'4 · dal-gsw-01 – BRV-IAD-ENC01 down · open'
		);
		const message = { subject: `Incident 4: ${title}`, text: `- ${title}, cleared 15:20` };
		expect(postmortemText({ message }, 'http://noc/?incident=4')).toBe(
			'Incident 4: dal-gsw-01 – BRV-IAD-ENC01 down\n\n- dal-gsw-01 – BRV-IAD-ENC01 down, cleared 15:20' +
				'\n\nIn Sunstone: http://noc/?incident=4'
		);
	});
});
