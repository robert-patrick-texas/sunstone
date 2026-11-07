import { describe, expect, it } from 'vitest';
import {
	acrossSentence,
	andList,
	lineDetail,
	circuitsOf,
	networkLine,
	riskFailure,
	riskItemName,
	riskSummary,
	siteList
} from './across.ts';
import type { NetworkImpact } from './api/analysis.ts';
import type { NetworkStatus } from './api/status.ts';
import { layeredIndex } from './test-fixture.ts';

const index = layeredIndex();
const circuitC = 'c-wan-01:GigabitEthernet0/0/0--transport:INET';

function status(network: string | null, over: Partial<NetworkStatus> = {}): NetworkStatus {
	return {
		network,
		name: network ?? 'Enterprise',
		status: 'operational',
		reasons: [],
		caveats: [],
		groups: [],
		sites: 2,
		reached: 2,
		tunnels_down: [],
		...over
	};
}

function impact(network: string | null, over: Partial<NetworkImpact> = {}): NetworkImpact {
	return {
		network,
		before: 'operational',
		after: status(network),
		tunnels: 0,
		tunnels_lost: [],
		links_lost: [],
		sites_lost: [],
		...over
	};
}

describe('lists', () => {
	it('joins words and names the first few sites', () => {
		expect([andList(['a']), andList(['a', 'b']), andList(['a', 'b', 'c'])]).toEqual([
			'a',
			'a and b',
			'a, b, and c'
		]);
		expect(siteList(['RDU', 'ATL', 'CLT'])).toBe('ATL, CLT, and RDU');
		expect(siteList(['F', 'E', 'D', 'C', 'B', 'A'])).toBe('A, B, C, D, and 2 more');
	});
});

describe('networkLine', () => {
	it('counts circuits lost against those the network has at the site', () => {
		const line = networkLine(
			index,
			impact('black', {
				links_lost: [circuitC],
				after: status('black', { status: 'degraded', reasons: ['Circuit NO-2 down'] })
			})
		);
		expect(line.losses).toEqual(['1 of 1 circuit at C']);
		expect([line.status, line.worse]).toEqual(['Operational → Degraded', true]);
	});

	it('counts tunnels, and names sites cut off', () => {
		const line = networkLine(
			index,
			impact('grey', {
				tunnels: 1,
				tunnels_lost: ['GREY-A-C'],
				sites_lost: ['C'],
				after: status('grey', { status: 'offline' })
			})
		);
		expect(line.losses).toEqual(['1 of 1 tunnel']);
		expect(line.sitesLost).toEqual(['C']);
		expect(line.note).toBeNull();
		expect(lineDetail(line)).toBe('1 of 1 tunnel · C cut off');
	});

	it('says what a network that loses nothing stays up over', () => {
		const line = networkLine(
			index,
			impact('blue', {
				tunnels: 1,
				after: status('blue', { caveats: ['black degraded at C: c-wan-01 down'] })
			})
		);
		expect([line.status, line.losses, line.note]).toEqual([
			'Operational*',
			[],
			'over black degraded at C'
		]);
		expect(line.worse).toBe(false);
		expect(lineDetail(line)).toBe('Stays up, over black degraded at C');
	});
});

describe('acrossSentence', () => {
	it('says what each network would lose, and which stay up', () => {
		const sentence = acrossSentence(index, [
			impact(null, { after: status(null, { status: 'degraded' }) }),
			impact('black', { links_lost: [circuitC] }),
			impact('blue', { tunnels: 1, tunnels_lost: ['BLUE-A-C'], sites_lost: ['C'] }),
			impact('grey', { after: status('grey', { caveats: ['blue degraded at C: x'] }) }),
			impact('red', { after: status('red', { caveats: ['blue degraded at C: x'] }) })
		]);
		expect(sentence).toBe(
			'black would lose 1 of 1 circuit at C; blue would lose 1 of 1 tunnel, cutting off C; grey and red stay up.'
		);
		expect(acrossSentence(index, [impact(null)])).toBeNull();
	});

	it('names the networks beyond the first three that would lose something', () => {
		const sentence = acrossSentence(index, [
			impact('black', { links_lost: [circuitC] }),
			impact('blue', { tunnels: 1, tunnels_lost: ['BLUE-A-C'] }),
			impact('grey', { sites_lost: ['C'] }),
			impact('red', { sites_lost: ['C'] }),
			impact('corp', { sites_lost: ['C'] })
		]);
		expect(sentence).toBe(
			'black would lose 1 of 1 circuit at C; blue would lose 1 of 1 tunnel; grey would lose C; red and corp would lose some too.'
		);
	});
});

describe('shared risk', () => {
	it('names what fails together, and what failing it would be', () => {
		const risk = {
			items: [
				{ kind: 'provider' as const, id: 'Northwind Fiber' },
				{ kind: 'link' as const, id: circuitC }
			],
			tunnels: ['BLUE-A-C', 'GREY-A-C'],
			sites: ['C']
		};
		expect(riskSummary(index, risk, 2)).toBe('2 of 2 tunnels · cuts off C');
		expect(risk.items.map((i) => riskItemName(index, i))).toEqual([
			'Northwind Fiber',
			'Circuit NO-2'
		]);
		expect(risk.items.map(riskFailure)).toEqual([
			{ kind: 'provider', id: 'Northwind Fiber' },
			{ kind: 'links', ids: [circuitC] }
		]);
		expect(circuitsOf(index, 'Northwind Fiber')).toHaveLength(2);
	});
});
