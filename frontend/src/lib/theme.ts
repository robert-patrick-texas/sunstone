/**
 * Colors the canvas-drawn views use. MapLibre and Cytoscape take colors as
 * values, not CSS variables, so they live here; `app.css` mirrors the UI ones.
 */
import type { Role } from './api/topology.ts';
import type { DeviceImpact } from './impact.ts';
import type { DeviceHealth } from './live.ts';

export const ROLE_COLOR: Record<Role, string> = {
	'wan-edge': '#c792ea',
	core: '#f78c6c',
	distribution: '#82aaff',
	access: '#7fdbca'
};

export const COLOR = {
	background: '#0f1419',
	text: '#d8dee9',
	muted: '#8a96a8',
	site: '#f5a623',
	siteBox: '#1c2632',
	group: '#141c26',
	groupBorder: '#3a4a5e',
	wan: '#f5a623',
	lan: '#5c6b80',
	selected: '#ffe066',
	path: '#4dd0e1'
};

// Live state. Healthy is blue, not green: green and red are hard to tell apart
// with red-green color blindness (ΔE 4 deuteranopic, against 24 for the blue,
// amber, and red used here, validated on this background). Down, degraded, and
// no-data devices also carry a glyph, so color is never the only cue.
export const HEALTH_COLOR: Record<DeviceHealth, string> = {
	up: '#3987e5',
	degraded: '#fab219',
	down: '#d03b3b',
	nodata: '#8a96a8',
	unmonitored: '#5c6b80'
};

export const HEALTH_GLYPH: Record<DeviceHealth, string> = {
	up: '',
	degraded: '!',
	down: '×',
	nodata: '?',
	unmonitored: ''
};

/** Link load bands: from this percent up, this color. One blue ramp, then status amber and red. */
export const UTIL_BANDS: readonly [number, string][] = [
	[0, '#184f95'],
	[20, '#256abf'],
	[40, '#3987e5'],
	[60, '#6da7ec'],
	[80, '#fab219'],
	[95, '#d03b3b']
];

// Impact reuses the status colors: red for lost, amber for one failure away
// from lost. A failed device is filled and marked ×, a cut-off one is a red
// outline, so the cause stands out from what it takes down with it.
export const IMPACT_COLOR: Record<DeviceImpact, string> = {
	failed: HEALTH_COLOR.down,
	cutoff: HEALTH_COLOR.down,
	exposed: HEALTH_COLOR.degraded
};

export const IMPACT_GLYPH: Record<DeviceImpact, string> = { failed: '×', cutoff: '', exposed: '!' };

// Lines in history charts, such as round trip from each monitoring position.
// Violet and aqua stay clear of the status colors and of each other with
// color blindness (validated on the panel background; worst ΔE 17); every
// line is also labeled.
export const SERIES_COLOR = ['#9085e9', '#199e70'] as const;

// Discovery against the documentation: cables seen but not documented
// (dashed) and documented links not seen as documented (dotted). Violet
// stays clear of the status colors, as validated for the history charts,
// and is never shown with a chart; line styles and the legend say which is which.
export const DRIFT_COLOR = SERIES_COLOR[0];

export const LINK_NODATA = '#8a96a8';
export const LINK_UNMONITORED = '#3a4655';

/**
 * Color for a link load.
 *
 * @param pct - Percent of capacity.
 * @returns The color of the band it falls in.
 */
export function utilColor(pct: number): string {
	let color = UTIL_BANDS[0]?.[1] ?? '';
	for (const [from, c] of UTIL_BANDS) if (pct >= from) color = c;
	return color;
}
