/**
 * What the NOC wall display shows in turn: an overview of each view, then
 * each problem no one is on yet, most urgent first.
 */
import type { Problem, ProblemKind } from './api/analysis.ts';
import { KINDS } from './problem-kinds.ts';
import type { View } from './state.svelte.ts';

export type Slide =
	| { kind: 'overview'; view: View; label: string }
	| { kind: 'problem'; problem: Problem; number: number; of: number };

export const OVERVIEWS: { view: View; label: string }[] = [
	{ view: 'geo', label: 'Network map' },
	{ view: 'hierarchy', label: 'Sites and tiers' }
];

/** Most problems shown one by one; the bar counts them all. */
export const MAX_PROBLEM_SLIDES = 10;

/**
 * Whether a problem still needs someone.
 *
 * @param p - The problem.
 * @returns False once acknowledged or accounted for by planned work.
 */
export function unhandled(p: Problem): boolean {
	return !p.ack && p.planned.length === 0;
}

/**
 * The slides to show in turn.
 *
 * @param problems - Problems, most urgent first, as the server ranks them.
 * @returns Overviews, then up to {@link MAX_PROBLEM_SLIDES} problems no one is on.
 */
export function slidesFor(problems: Problem[]): Slide[] {
	const open = problems.filter(unhandled).slice(0, MAX_PROBLEM_SLIDES);
	return [
		...OVERVIEWS.map((o) => ({ kind: 'overview' as const, ...o })),
		...open.map((problem, i) => ({
			kind: 'problem' as const,
			problem,
			number: i + 1,
			of: open.length
		}))
	];
}

/**
 * How many problems no one is on, by kind, for the wall's bar.
 *
 * @param problems - Problems.
 * @returns Kinds with any such problems, most urgent first, and how many are handled.
 */
export function tally(problems: Problem[]): {
	kinds: { kind: ProblemKind; short: string; count: number }[];
	handled: number;
} {
	const open = problems.filter(unhandled);
	return {
		kinds: KINDS.map((k) => ({
			kind: k.kind,
			short: k.short,
			count: open.filter((p) => p.kind === k.kind).length
		})).filter((k) => k.count > 0),
		handled: problems.length - open.length
	};
}
