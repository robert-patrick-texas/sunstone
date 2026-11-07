/**
 * How network status is shown: a label, a color, and a mark for each state,
 * so color is never the only cue, and the caveat a working network can carry.
 */
import type { NetworkStatus, Status, StatusReport } from './api/status.ts';
import { HEALTH_COLOR } from './theme.ts';

export const STATUS_LABEL: Record<Status, string> = {
	operational: 'Operational',
	degraded: 'Degraded',
	offline: 'Offline'
};

export const STATUS_COLOR: Record<Status, string> = {
	operational: HEALTH_COLOR.up,
	degraded: HEALTH_COLOR.degraded,
	offline: HEALTH_COLOR.down
};

export const STATUS_GLYPH: Record<Status, string> = {
	operational: '',
	degraded: '!',
	offline: '×'
};

/**
 * A network's status as one word: operational with an asterisk when what it
 * rides is degraded at its sites.
 *
 * @param network - The network's status.
 * @returns For example `Degraded`, or `Operational*`.
 */
export function statusWord(network: NetworkStatus): string {
	const caveat = network.status === 'operational' && network.caveats.length > 0;
	return `${STATUS_LABEL[network.status]}${caveat ? '*' : ''}`;
}

/**
 * A named network's status in a report.
 *
 * @param report - The report, or null without live state.
 * @param name - The network.
 * @returns Its status, or undefined.
 */
export function statusOf(report: StatusReport | null, name: string): NetworkStatus | undefined {
	return report?.networks.find((n) => n.network === name);
}

/**
 * The networks that need someone: not operational, or working over
 * something degraded; the whole network first.
 *
 * @param report - The report.
 * @returns Those networks, worst first.
 */
export function needing(report: StatusReport): NetworkStatus[] {
	const rank: Record<Status, number> = { offline: 0, degraded: 1, operational: 2 };
	return [report.whole, ...report.networks]
		.filter((n) => n.status !== 'operational' || n.caveats.length > 0)
		.sort((x, y) => rank[x.status] - rank[y.status] || (x.network === null ? -1 : 0));
}
