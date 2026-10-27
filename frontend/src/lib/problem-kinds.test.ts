import { describe, expect, it } from 'vitest';
import type { Problem } from './api/analysis.ts';
import { grouped, stepProblem } from './problem-kinds.ts';

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
		expect(grouped(PROBLEMS).map((g) => [g.kind, g.items.map((p) => p.id)])).toEqual([
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
