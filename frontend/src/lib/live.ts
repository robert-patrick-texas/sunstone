/**
 * What live state means for each device, link, and site on the map.
 *
 * Sources report devices and interfaces; links get their state from the
 * interfaces at their two ends, so a link has data if either end is
 * monitored. Missing data is never zero: a device or link the source does not
 * watch is "not monitored", and one it watches without a fresh reading has
 * "no data". Both are drawn differently from any measured value.
 */
import type { Link } from './api/topology.ts';
import type { DeviceState, InterfaceState, NetworkState } from './api/state.ts';

/** Loss at or above this, from any position, marks a device degraded. */
export const DEGRADED_LOSS_PCT = 1;
/** Utilization at or above these is high, then critical. */
export const HIGH_PCT = 80;
export const CRITICAL_PCT = 95;

export type DeviceHealth = 'up' | 'degraded' | 'down' | 'nodata' | 'unmonitored';

export const HEALTH_LABEL: Record<DeviceHealth, string> = {
	up: 'Up',
	degraded: 'Packet loss',
	down: 'Down',
	nodata: 'No recent data',
	unmonitored: 'Not monitored'
};
export type LinkHealth = 'ok' | 'down' | 'nodata' | 'unmonitored';
/** For several links drawn as one: `partial` when some, but not all, are down. */
export type BundleHealth = LinkHealth | 'partial';

export interface LiveIndex {
	state: NetworkState;
	devices: Map<string, DeviceState>;
	interfaces: Map<string, InterfaceState>;
}

export interface LinkLive {
	health: LinkHealth;
	/** Percent load from the link's A end toward B, and back; null when unknown. */
	aToB: number | null;
	bToA: number | null;
	/** The busier direction. */
	utilPct: number | null;
}

const key = (device: string, ifname: string) => `${device}\u0000${ifname}`;

/**
 * Build lookups for a snapshot.
 *
 * @param state - Snapshot from the API.
 * @returns The index.
 */
export function indexState(state: NetworkState): LiveIndex {
	return {
		state,
		devices: new Map(state.devices.map((d) => [d.device, d])),
		interfaces: new Map(state.interfaces.map((i) => [key(i.device, i.interface), i]))
	};
}

/**
 * A device's health.
 *
 * @param live - Live index.
 * @param device - Device name.
 * @returns `nodata` for a stale reading, whatever it said; else down, degraded
 *   (loss from some position), or up; `unmonitored` if the source has no record.
 */
export function deviceHealth(live: LiveIndex, device: string): DeviceHealth {
	const d = live.devices.get(device);
	if (!d) return 'unmonitored';
	if (d.stale) return 'nodata';
	if (d.status === 'down') return 'down';
	const lossy = d.reachability.some((r) => (r.loss_pct ?? 0) >= DEGRADED_LOSS_PCT);
	return lossy ? 'degraded' : 'up';
}

/**
 * A link's state, from whichever of its ends report it.
 *
 * @param live - Live index.
 * @param link - The link.
 * @returns Health and load in each direction.
 */
export function linkLive(live: LiveIndex, link: Link): LinkLive {
	const ends = [link.a, link.b].map((e) => ({
		device: live.devices.get(e.device),
		reading: live.interfaces.get(key(e.device, e.interface))
	}));
	const [a, b] = ends as [(typeof ends)[0], (typeof ends)[0]];
	const unknown = { aToB: null, bToA: null, utilPct: null };
	if (!a.device && !b.device) return { health: 'unmonitored', ...unknown };
	const fresh = (r: InterfaceState | undefined) => (r && !r.stale ? r : undefined);
	const ra = fresh(a.reading);
	const rb = fresh(b.reading);
	const deviceDown = ends.some((e) => e.device && !e.device.stale && e.device.status === 'down');
	if (deviceDown || ra?.oper === 'down' || rb?.oper === 'down') {
		return { health: 'down', ...unknown };
	}
	const aToB = ra?.out_pct ?? rb?.in_pct ?? null;
	const bToA = ra?.in_pct ?? rb?.out_pct ?? null;
	if (aToB === null && bToA === null) return { health: 'nodata', ...unknown };
	return { health: 'ok', aToB, bToA, utilPct: Math.max(aToB ?? 0, bToA ?? 0) };
}

/**
 * The state of several links drawn as one line (a LAG, or a site pair).
 *
 * @param links - Each link's state.
 * @returns Partial when only some are down; the highest known load.
 */
export function bundleLive(links: LinkLive[]): { health: BundleHealth; utilPct: number | null } {
	const known = links.filter((l) => l.utilPct !== null).map((l) => l.utilPct ?? 0);
	const utilPct = known.length ? Math.max(...known) : null;
	const down = links.filter((l) => l.health === 'down').length;
	if (down && down === links.length) return { health: 'down', utilPct: null };
	if (down) return { health: 'partial', utilPct };
	if (known.length) return { health: 'ok', utilPct };
	const health = links.some((l) => l.health === 'nodata') ? 'nodata' : 'unmonitored';
	return { health, utilPct: null };
}

const SEVERITY: DeviceHealth[] = ['unmonitored', 'up', 'nodata', 'degraded', 'down'];

/**
 * How a group of devices (a site) is doing: its worst health and the counts.
 *
 * @param live - Live index.
 * @param devices - Device names.
 * @returns The worst health and how many devices have each.
 */
export function groupHealth(
	live: LiveIndex,
	devices: string[]
): { health: DeviceHealth; counts: Record<DeviceHealth, number> } {
	const counts: Record<DeviceHealth, number> = {
		up: 0,
		degraded: 0,
		down: 0,
		nodata: 0,
		unmonitored: 0
	};
	for (const device of devices) counts[deviceHealth(live, device)]++;
	const health = [...SEVERITY].reverse().find((h) => counts[h] > 0) ?? 'unmonitored';
	return { health, counts };
}
