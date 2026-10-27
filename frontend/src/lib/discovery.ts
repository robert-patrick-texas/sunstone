/**
 * Discovery findings as the UI shows them: how each kind is headed, what to
 * select for one, and what discovery says about a device or a link.
 */
import type { Comparison, Finding, FindingKind, LinkCheck } from './api/discovery.ts';
import { clock } from './history.ts';
import type { Selection } from './state.svelte.ts';
import type { TopologyIndex } from './topology.ts';

/** Kinds in the order the server ranks them, most misleading first. */
export const FINDING_KINDS: { kind: FindingKind; label: string }[] = [
	{ kind: 'wrong-neighbor', label: 'Another device on the port' },
	{ kind: 'wrong-port', label: 'On another port' },
	{ kind: 'not-seen', label: 'Documented, not seen' },
	{ kind: 'undocumented', label: 'Seen, not documented' },
	{ kind: 'unknown-device', label: 'Neighbors not in the topology' },
	{ kind: 'no-neighbors', label: 'Reporting no neighbors' }
];

export const CHECK_LABEL: Record<LinkCheck, string> = {
	confirmed: 'Confirmed',
	mismatch: 'Seen elsewhere',
	'not-seen': 'Not seen',
	down: 'Down, so not seen',
	unchecked: 'Not checked'
};

/**
 * Findings grouped by kind.
 *
 * @param findings - Findings, as the server ranks them.
 * @returns The kinds with any, in order, each with its findings.
 */
export function groupFindings(
	findings: Finding[]
): { kind: FindingKind; label: string; items: Finding[] }[] {
	return FINDING_KINDS.map((k) => ({
		...k,
		items: findings.filter((f) => f.kind === k.kind)
	})).filter((g) => g.items.length > 0);
}

/**
 * What to select to look at a finding.
 *
 * @param finding - The finding.
 * @returns The documented link it is about, or else the first device it involves.
 */
export function findingTarget(finding: Finding): Selection | null {
	if (finding.link) return { kind: 'links', ids: [finding.link] };
	const [device] = finding.devices;
	return device ? { kind: 'device', id: device } : null;
}

/**
 * A documented link's check.
 *
 * @param comparison - The comparison.
 * @param link - The link's id.
 * @returns Its check; links the server leaves out are confirmed.
 */
export function linkCheck(comparison: Comparison, link: string): LinkCheck {
	return comparison.links[link] ?? 'confirmed';
}

/**
 * When a finding was seen, for its line in a list.
 *
 * @param finding - The finding.
 * @param historyFrom - The earliest run history has, if any.
 * @returns For example "since 14:15", "since before Mon 15:00" (as far
 *   back as history goes), "10:00 – 12:45", or "" if nothing is known.
 */
export function seenWhen(finding: Finding, historyFrom: string | null | undefined): string {
	const from = finding.first_seen
		? clock(finding.first_seen)
		: historyFrom
			? `before ${clock(historyFrom)}`
			: null;
	if (finding.last_seen) {
		return from ? `${from} – ${clock(finding.last_seen)}` : `until ${clock(finding.last_seen)}`;
	}
	return from ? `since ${from}` : '';
}

/** What discovery says about one device. */
export interface DeviceCheck {
	/** It answered the latest run. */
	polled: boolean;
	/** Its documented links, and how many of them are confirmed. */
	links: number;
	confirmed: number;
	findings: Finding[];
}

/**
 * What discovery says about a device.
 *
 * @param comparison - The comparison.
 * @param index - Topology index.
 * @param device - The device's name.
 * @returns Whether it answered, its links confirmed, and the findings that involve it.
 */
export function deviceCheck(
	comparison: Comparison,
	index: TopologyIndex,
	device: string
): DeviceCheck {
	const links = index.linksByDevice.get(device) ?? [];
	return {
		polled: comparison.polled.includes(device),
		links: links.length,
		confirmed: links.filter((l) => linkCheck(comparison, l.id) === 'confirmed').length,
		findings: comparison.findings.filter((f) => f.devices.includes(device))
	};
}
