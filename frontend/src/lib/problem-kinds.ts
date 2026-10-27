/**
 * How each kind of problem is headed and marked, wherever problems are
 * listed: the side panel and the wall display.
 */
import type { ProblemKind } from './api/analysis.ts';
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
