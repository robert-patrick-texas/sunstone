/**
 * How each kind of problem is headed and marked, wherever problems are
 * listed: the side panel and the wall display; and the order the side panel
 * lists them in, high priority first, then by kind or by region, for the
 * networks chosen.
 */
import type { Problem, ProblemKind } from './api/analysis.ts';
import { CRITICAL_PCT, HIGH_PCT } from './live.ts';
import { NO_REGION, type Scope } from './scope.ts';
import { HEALTH_COLOR } from './theme.ts';
import { siteOf, type TopologyIndex } from './topology.ts';

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

/** How the side panel groups problems. */
export type ProblemsBy = 'kind' | 'region';

/** One heading of the side panel's list, with its problems in order. */
export interface ProblemGroup {
	key: string;
	label: string;
	items: Problem[];
}

/** Which problems the side panel lists, and how it groups them. */
export interface ProblemView {
	index: TopologyIndex;
	scope: Scope;
	by: ProblemsBy;
}

/**
 * The site a problem is at, for grouping by region.
 *
 * @param index - Topology index.
 * @param problem - The problem.
 * @returns Its device's site, its site, or its first link's A end's site.
 */
export function problemSite(index: TopologyIndex, problem: Problem): string {
	const { target } = problem;
	if (target.kind === 'site') return target.id;
	if (target.kind === 'device') return siteOf(index, target.id);
	const link = index.links.get(target.ids[0] ?? '');
	return link ? siteOf(index, link.a.device) : '';
}

/**
 * Whether a problem belongs to the networks chosen: it takes something from
 * one, or what it is or what it fails or cuts off belongs to them.
 *
 * @param index - Topology index.
 * @param scope - The networks chosen.
 * @param problem - The problem.
 * @returns True if it belongs, and always with no network chosen.
 */
export function inScope(index: TopologyIndex, scope: Scope, problem: Problem): boolean {
	if (scope.networks.length === 0) return true;
	if (problem.networks.some((n) => n.network !== null && scope.networks.includes(n.network))) {
		return true;
	}
	const { target, impact } = problem;
	const devices = new Set([...(impact?.failed.devices ?? []), ...(impact?.cutOff ?? [])]);
	const links = new Set(impact?.failed.links ?? []);
	if (target.kind === 'device') devices.add(target.id);
	if (target.kind === 'site') {
		for (const d of index.devicesBySite.get(target.id) ?? []) devices.add(d.name);
	}
	if (target.kind === 'links') for (const id of target.ids) links.add(id);
	return scope.has(devices, links);
}

/**
 * Problems as the side panel lists them: high priority first, on their own;
 * then the rest by kind, most urgent first, or by region in the order the
 * regions are listed; within each, problems someone is on and then planned
 * ones after the rest.
 *
 * @param problems - Problems, most urgent first, as the server ranks them.
 * @param view - Which to keep and how to group them; without it, every
 *   problem, by kind.
 * @returns The groups with any problems, each with its problems in order.
 */
export function grouped(problems: Problem[], view?: ProblemView): ProblemGroup[] {
	const kept = view ? problems.filter((p) => inScope(view.index, view.scope, p)) : problems;
	// Sorting is stable, so the server's order holds within each.
	const sorted = (items: Problem[]) => items.sort((x, y) => handling(x) - handling(y));
	const high: ProblemGroup = {
		key: 'high-priority',
		label: 'High priority',
		items: sorted(kept.filter((p) => p.priority === 'high'))
	};
	const rest = kept.filter((p) => p.priority !== 'high');
	if (view?.by === 'region') {
		const { index, scope } = view;
		const regionOf = new Map(rest.map((p) => [p.id, scope.regionOf(problemSite(index, p))]));
		const names = scope.regions.map((r) => r.name);
		if (!names.includes(NO_REGION)) names.push(NO_REGION);
		return [
			high,
			...names.map((name) => ({
				key: name,
				label: name,
				items: sorted(rest.filter((p) => regionOf.get(p.id) === name))
			}))
		].filter((g) => g.items.length > 0);
	}
	return [
		high,
		...KINDS.map((k) => ({
			key: k.kind,
			label: k.label,
			items: sorted(rest.filter((p) => p.kind === k.kind))
		}))
	].filter((g) => g.items.length > 0);
}

/**
 * The problem after (or before) one, in the order the side panel lists them,
 * going round at the ends.
 *
 * @param problems - Problems, most urgent first, as the server ranks them.
 * @param current - The problem shown, by id, or null.
 * @param step - 1 for the next problem, -1 for the one before.
 * @param view - Which the side panel lists, and how it groups them.
 * @returns The problem, or null if there are none.
 */
export function stepProblem(
	problems: Problem[],
	current: string | null,
	step: 1 | -1,
	view?: ProblemView
): Problem | null {
	const order = grouped(problems, view).flatMap((g) => g.items);
	if (order.length === 0) return null;
	const at = order.findIndex((p) => p.id === current);
	const next =
		at < 0 ? (step > 0 ? 0 : order.length - 1) : (at + step + order.length) % order.length;
	return order[next] ?? null;
}
