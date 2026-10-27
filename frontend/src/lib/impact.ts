/**
 * What failures do to the network, as the views draw it: which devices
 * failed, which they cut off from the core, and which they leave hanging on
 * a single device. The server works impacts out (`backend/src/sunstone/
 * impact.py`), for problems and for "what if" questions alike.
 */
import type { Link } from './api/topology.ts';

export interface Failures {
	devices: Set<string>;
	links: Set<string>;
}

export interface Impact {
	failed: Failures;
	/** Devices, not failed themselves, left with no path to the core. */
	cutOff: Set<string>;
	/** Devices that had a second path to the core and now have one, with the devices it runs through. */
	exposed: Map<string, string[]>;
}

/** How one device or link is affected, for drawing. */
export type DeviceImpact = 'failed' | 'cutoff' | 'exposed';
export type LinkImpact = 'lost' | 'partial';

export const IMPACT_LABEL: Record<DeviceImpact, string> = {
	failed: 'Failed',
	cutoff: 'Cut off',
	exposed: 'No redundancy left'
};

const SEVERITY: DeviceImpact[] = ['exposed', 'cutoff', 'failed'];

/**
 * How a device is affected.
 *
 * @param impact - The impact being shown.
 * @param device - Device name.
 * @returns Failed, cut off, left exposed, or null if untouched.
 */
export function deviceImpact(impact: Impact, device: string): DeviceImpact | null {
	if (impact.failed.devices.has(device)) return 'failed';
	if (impact.cutOff.has(device)) return 'cutoff';
	if (impact.exposed.has(device)) return 'exposed';
	return null;
}

/**
 * The worst way any of a group of devices (a site) is affected.
 *
 * @param impact - The impact being shown.
 * @param devices - Device names.
 * @returns The most severe device impact among them, or null.
 */
export function worstImpact(impact: Impact, devices: string[]): DeviceImpact | null {
	let worst = -1;
	for (const d of devices) {
		const found = deviceImpact(impact, d);
		if (found) worst = Math.max(worst, SEVERITY.indexOf(found));
	}
	return SEVERITY[worst] ?? null;
}

/**
 * Whether links carry traffic any more: lost when failed or ending at a
 * failed or cut-off device.
 *
 * @param impact - The impact being shown.
 * @param links - Links drawn as one (a LAG, or a site pair).
 * @returns Lost when all are, partial when some are, null when none.
 */
export function linksImpact(impact: Impact, links: Link[]): LinkImpact | null {
	const gone = (d: string) => impact.failed.devices.has(d) || impact.cutOff.has(d);
	const lost = links.filter(
		(l) => impact.failed.links.has(l.id) || gone(l.a.device) || gone(l.b.device)
	).length;
	if (lost === 0) return null;
	return lost === links.length ? 'lost' : 'partial';
}
