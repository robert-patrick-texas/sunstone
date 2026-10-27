/**
 * How each kind of problem is headed and marked, wherever problems are
 * listed: the side panel and the wall display.
 */
import type { Problem, ProblemKind } from './api/analysis.ts';
import { CRITICAL_PCT, HIGH_PCT } from './live.ts';
import { HEALTH_COLOR } from './theme.ts';

/** Kinds in the order the server ranks them, with a heading and a short name for each. */
export const KINDS: { kind: ProblemKind; label: string; short: string }[] = [
	{ kind: 'outage', label: 'Unreachable', short: 'unreachable' },
	{ kind: 'link-down', label: 'Links down', short: 'links down' },
	{ kind: 'congested', label: `Congested, ${CRITICAL_PCT}% or more`, short: 'congested' },
	{ kind: 'loss', label: 'Packet loss', short: 'packet loss' },
	{ kind: 'busy', label: `Busy, ${HIGH_PCT}% or more`, short: 'busy' },
	{ kind: 'nodata', label: 'No recent data', short: 'no data' }
];

// Status colors, each with its own mark, so color is never the only cue.
export const MARK: Record<ProblemKind, { color: string; glyph: string }> = {
	outage: { color: HEALTH_COLOR.down, glyph: '×' },
	'link-down': { color: HEALTH_COLOR.down, glyph: '×' },
	congested: { color: HEALTH_COLOR.down, glyph: '%' },
	loss: { color: HEALTH_COLOR.degraded, glyph: '!' },
	busy: { color: HEALTH_COLOR.degraded, glyph: '%' },
	nodata: { color: HEALTH_COLOR.nodata, glyph: '?' }
};

/** 0 for a problem no one is on, 1 acknowledged, 2 accounted for by planned work. */
export function handling(p: Problem): number {
	return p.planned.length ? 2 : p.ack ? 1 : 0;
}

/**
 * Problems as the side panel lists them: by kind, most urgent first, and
 * within each kind, problems someone is on and then planned ones after the rest.
 *
 * @param problems - Problems, most urgent first, as the server ranks them.
 * @returns The kinds with any problems, each with its problems in order.
 */
export function grouped(
	problems: Problem[]
): { kind: ProblemKind; label: string; short: string; items: Problem[] }[] {
	return KINDS.map((k) => ({
		...k,
		// Sorting is stable, so the server's order holds within each.
		items: problems.filter((p) => p.kind === k.kind).sort((x, y) => handling(x) - handling(y))
	})).filter((g) => g.items.length > 0);
}

/**
 * The problem after (or before) one, in the order the side panel lists them,
 * going round at the ends.
 *
 * @param problems - Problems, most urgent first, as the server ranks them.
 * @param current - The problem shown, by id, or null.
 * @param step - 1 for the next problem, -1 for the one before.
 * @returns The problem, or null if there are none.
 */
export function stepProblem(
	problems: Problem[],
	current: string | null,
	step: 1 | -1
): Problem | null {
	const order = grouped(problems).flatMap((g) => g.items);
	if (order.length === 0) return null;
	const at = order.findIndex((p) => p.id === current);
	const next =
		at < 0 ? (step > 0 ? 0 : order.length - 1) : (at + step + order.length) % order.length;
	return order[next] ?? null;
}
