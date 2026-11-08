import { describe, expect, it } from 'vitest';
import type { NetworkImpact, Problem } from './api/analysis.ts';
import { grouped, inScope, problemSite, stepProblem, type ProblemView } from './problem-kinds.ts';
import { scopeOf } from './scope.ts';
import { layeredIndex } from './test-fixture.ts';

function problem(id: string, kind: Problem['kind'], extra: Partial<Problem> = {}): Problem {
	return {
		id,
		kind,
		title: id,
		detail: '',
		target: { kind: 'device', id },
		impact: null,
		lost: 0,
		exposed: 0,
		planned: [],
		ack: null,
		team: null,
		urgency: 'high',
		paging: null,
		networks: [],
		...extra
	};
}

const ACK = { problem: 'x', note: '', by: 'Pat', at: '2026-10-27T15:00:00Z', cleared_at: null };
// As the server ranks them; the list puts handled ones after the rest of their kind.
const PROBLEMS = [
	problem('a', 'outage', { ack: ACK }),
	problem('b', 'outage'),
	problem('c', 'busy'),
	problem('d', 'link-down', { planned: ['w1'] })
];

describe('grouped', () => {
	it('lists by kind, handled problems after the rest of their kind', () => {
		expect(grouped(PROBLEMS).map((g) => [g.key, g.items.map((p) => p.id)])).toEqual([
			['outage', ['b', 'a']],
			['link-down', ['d']],
			['busy', ['c']]
		]);
	});
});

describe('stepProblem', () => {
	it('goes through problems in the order the list has them, round at the ends', () => {
		expect(stepProblem(PROBLEMS, null, 1)?.id).toBe('b');
		expect(stepProblem(PROBLEMS, 'b', 1)?.id).toBe('a');
		expect(stepProblem(PROBLEMS, 'a', 1)?.id).toBe('d');
		expect(stepProblem(PROBLEMS, 'c', 1)?.id).toBe('b');
		expect(stepProblem(PROBLEMS, 'b', -1)?.id).toBe('c');
		expect(stepProblem(PROBLEMS, null, -1)?.id).toBe('c');
	});

	it('starts again from the first when the one shown has cleared', () => {
		expect(stepProblem(PROBLEMS, 'gone', 1)?.id).toBe('b');
		expect(stepProblem([], null, 1)).toBeNull();
	});
});

const index = layeredIndex();
const view = (networks: string[], by: ProblemView['by']): ProblemView => ({
	index,
	scope: scopeOf(index, networks),
	by
});
const across = (network: string) => ({ network }) as NetworkImpact;
// At B, which is in East; at C and A, in South.
const PLACED = [
	problem('b-wan-01', 'outage'),
	problem('C', 'outage', { target: { kind: 'site', id: 'C' } }),
	problem('circuit', 'link-down', {
		target: { kind: 'links', ids: ['a-wan-01:Hu1/0/2--b-wan-01:Hu1/0/2'] }
	}),
	problem('b-core-01', 'busy', { networks: [across('grey')] })
];

describe('problems for the networks chosen', () => {
	it('places a problem at its device, its site, or its first link', () => {
		expect(PLACED.map((p) => problemSite(index, p))).toEqual(['B', 'C', 'A', 'B']);
	});

	it('keeps those that are part of the networks, or take something from one', () => {
		const grey = scopeOf(index, ['grey']);
		expect(PLACED.filter((p) => inScope(index, grey, p)).map((p) => p.id)).toEqual([
			'C',
			'b-core-01'
		]);
	});

	it('counts what a problem fails or cuts off', () => {
		const cut = problem('b-wan-01', 'outage', {
			impact: {
				failed: { devices: new Set(['b-wan-01']), links: new Set() },
				cutOff: new Set(['c-acc-02']),
				exposed: new Map(),
				tunnels: new Set()
			}
		});
		expect(inScope(index, scopeOf(index, ['grey']), cut)).toBe(true);
	});
});

describe('grouped by region', () => {
	it('lists the regions in order, each with its problems in order', () => {
		expect(
			grouped(PLACED, view([], 'region')).map((g) => [g.key, g.items.map((p) => p.id)])
		).toEqual([
			['South', ['C', 'circuit']],
			['East', ['b-wan-01', 'b-core-01']]
		]);
	});

	it('steps through them in the order listed, only those of the networks chosen', () => {
		const byRegion = view([], 'region');
		expect(stepProblem(PLACED, null, 1, byRegion)?.id).toBe('C');
		expect(stepProblem(PLACED, 'circuit', 1, byRegion)?.id).toBe('b-wan-01');
		const grey = view(['grey'], 'kind');
		expect(stepProblem(PLACED, 'C', 1, grey)?.id).toBe('b-core-01');
		expect(stepProblem(PLACED, 'b-core-01', 1, grey)?.id).toBe('C');
	});
});
