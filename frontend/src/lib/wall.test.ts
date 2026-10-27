import { describe, expect, it } from 'vitest';
import type { Problem } from './api/analysis.ts';
import { MAX_PROBLEM_SLIDES, slidesFor, tally } from './wall.ts';

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

describe('slidesFor', () => {
	it('shows the overviews, then problems no one is on, in the order given', () => {
		const slides = slidesFor([
			problem('a', 'outage'),
			problem('b', 'outage', { ack: ACK }),
			problem('c', 'link-down', { planned: ['w1'] }),
			problem('d', 'loss')
		]);
		expect(slides.map((s) => (s.kind === 'overview' ? s.view : s.problem.id))).toEqual([
			'geo',
			'hierarchy',
			'a',
			'd'
		]);
		const last = slides.at(-1);
		expect(last?.kind === 'problem' && [last.number, last.of]).toEqual([2, 2]);
	});

	it('shows at most so many problems one by one', () => {
		const many = Array.from({ length: 30 }, (_, i) => problem(`p${i}`, 'nodata'));
		expect(slidesFor(many).filter((s) => s.kind === 'problem')).toHaveLength(MAX_PROBLEM_SLIDES);
	});
});

describe('tally', () => {
	it('counts problems no one is on by kind, and the handled ones apart', () => {
		const counts = tally([
			problem('a', 'outage'),
			problem('b', 'outage'),
			problem('c', 'busy', { ack: ACK }),
			problem('d', 'nodata')
		]);
		expect(counts).toEqual({
			kinds: [
				{ kind: 'outage', short: 'unreachable', count: 2 },
				{ kind: 'nodata', short: 'no data', count: 1 }
			],
			handled: 1
		});
	});
});
