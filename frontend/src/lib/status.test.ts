import { describe, expect, it } from 'vitest';
import type { NetworkStatus, StatusReport } from './api/status.ts';
import { eventRows, tunnelName, tunnelTarget, EVENT_CATEGORIES } from './history.ts';
import { needing, statusOf, statusWord } from './status.ts';
import { layeredIndex } from './test-fixture.ts';

function network(name: string | null, extra: Partial<NetworkStatus> = {}): NetworkStatus {
	return {
		network: name,
		name: name ?? 'Enterprise',
		status: 'operational',
		reasons: [],
		caveats: [],
		groups: [],
		sites: 3,
		reached: 3,
		tunnels_down: [],
		...extra
	};
}

const REPORT: StatusReport = {
	at: '2026-11-07T15:00:00Z',
	whole: network(null, { status: 'degraded', reasons: ['Circuit NO-1 down'] }),
	networks: [
		network('black', { status: 'degraded' }),
		network('blue', { caveats: ['black degraded at D: Circuit NO-1 down'] }),
		network('grey'),
		network('red', { status: 'offline' })
	]
};

describe('network status', () => {
	it('marks a working network over something degraded with an asterisk', () => {
		expect(statusWord(REPORT.networks[1]!)).toBe('Operational*');
		expect(statusWord(REPORT.networks[2]!)).toBe('Operational');
		expect(statusOf(REPORT, 'red')?.status).toBe('offline');
		expect(statusOf(null, 'red')).toBeUndefined();
	});

	it('lists what needs someone, worst first, the whole network first among equals', () => {
		expect(needing(REPORT).map((n) => n.name)).toEqual(['red', 'Enterprise', 'black', 'blue']);
	});
});

describe('tunnel events', () => {
	const index = layeredIndex();

	it('names a fabric tunnel by its fabric and ends, and selects the fabric', () => {
		expect(tunnelName('DMVPN:c-wan-01~a-wan-01')).toBe('DMVPN: c-wan-01 – a-wan-01');
		expect(tunnelName('GREY-A-C')).toBe('GREY-A-C');
		expect(tunnelTarget(index, 'DMVPN:c-wan-01~a-wan-01')).toEqual({ kind: 'fabric', id: 'DMVPN' });
		expect(tunnelTarget(index, 'GREY-A-C')).toEqual({ kind: 'tunnel', id: 'GREY-A-C' });
	});

	it('are rows of their own, in a category of their own', () => {
		const shown = new Set(EVENT_CATEGORIES.map((c) => c.category));
		const at = '2026-11-07T15:00:00Z';
		const rows = eventRows(
			index,
			[
				{ at, kind: 'tunnel-down', tunnel: 'GREY-A-C', planned: false },
				{ at, kind: 'tunnel-up', tunnel: 'DMVPN:c-wan-01~a-wan-01', planned: false }
			],
			shown
		);
		expect(rows.map((r) => r.title).sort()).toEqual([
			'DMVPN: c-wan-01 – a-wan-01 back up',
			'GREY-A-C down'
		]);
		shown.delete('tunnels');
		expect(
			eventRows(index, [{ at, kind: 'tunnel-down', tunnel: 'GREY-A-C', planned: false }], shown)
		).toEqual([]);
	});
});
