/**
 * Discovery findings as the UI shows them: how each kind is headed, what to
 * select for one, and what discovery says about a device or a link; and the
 * fixes they offer: what a review of one says, and the change set's lines.
 */
import type { Change, PortNow, Review } from './api/changes.ts';
import type { Comparison, Finding, FindingKind, LinkCheck } from './api/discovery.ts';
import type { Link } from './api/topology.ts';
import { clock } from './history.ts';
import type { Selection } from './state.svelte.ts';
import { shortInterface, type TopologyIndex } from './topology.ts';

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
	expected: 'Not seen, expected',
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

/**
 * Kinds that can be marked expected: what discovery cannot see, or what is
 * not meant to be documented (the server's `EXPECTABLE`). A link on another
 * port or device is fixed instead.
 */
export const EXPECTABLE: ReadonlySet<FindingKind> = new Set([
	'not-seen',
	'unknown-device',
	'no-neighbors'
]);

/** Why discovery offers no fix, for the kinds it never offers one for. */
export const NO_FIX: Partial<Record<FindingKind, string>> = {
	'unknown-device': 'Document the device first, or unplug it.',
	'no-neighbors': 'Turn LLDP or CDP on, and its links can be checked.'
};

/**
 * A link by its two ends.
 *
 * @param link - The link.
 * @returns For example "d-dist-02 Te1/0/48 – d-acc-05 Te1/0/1".
 */
export function linkEnds(link: Link): string {
	return (
		`${link.a.device} ${shortInterface(link.a.interface)} – ` +
		`${link.b.device} ${shortInterface(link.b.interface)}`
	);
}

const DONE: Record<Change['fix']['kind'], string> = {
	move: 'Moved to',
	add: 'Added',
	retire: 'Retired',
	expect: 'Expected:'
};

/**
 * What a change did, for its line in the change set.
 *
 * @param change - The change.
 * @returns For example "Moved to d-dist-02 Te1/0/48 – d-acc-05 Te1/0/1".
 */
export function changeLine(change: Change): string {
	const link = change.fix.after ?? change.fix.before;
	return link
		? `${DONE[change.fix.kind]} ${linkEnds(link)}`
		: `${DONE[change.fix.kind]} ${change.title}`;
}

/**
 * The expected finding that explains a link discovery does not see, and
 * the change that marked it, if any.
 *
 * @param comparison - The comparison.
 * @param changes - Changes accepted, newest first.
 * @param link - The link.
 * @returns The finding about the link, or about a device at either end
 *   expected to report no neighbors, with the change that marked it or
 *   the finding that covers it.
 */
export function expectationOf(
	comparison: Comparison,
	changes: Change[],
	link: Link
): { finding: Finding; change: Change | undefined } | null {
	const ends = [link.a.device, link.b.device];
	const finding = comparison.expected.find(
		(f) => f.link === link.id || (f.kind === 'no-neighbors' && ends.includes(f.devices[0] ?? ''))
	);
	if (!finding) return null;
	return {
		finding,
		change: changes.find(
			(c) => c.fix.kind === 'expect' && c.finding === (finding.covered_by ?? finding.id)
		)
	};
}

/**
 * What to select once a fix is in the documentation, or out of it again.
 *
 * @param now - The link as now documented, if there is one.
 * @param then - The link as it was.
 * @returns The link now, or else a device at the end of the one that was.
 */
export function changedTarget(
	now: Link | null | undefined,
	then: Link | null | undefined
): Selection | null {
	if (now) return { kind: 'links', ids: [now.id] };
	return then ? { kind: 'device', id: then.a.device } : null;
}

/**
 * The change that put a link in the documentation as it now is, if any.
 *
 * @param changes - Changes accepted, newest first.
 * @param link - The link's id.
 * @returns The latest change that moved or added it.
 */
export function changeOf(changes: Change[], link: string): Change | undefined {
	return changes.find((c) => c.fix.after?.id === link);
}

/**
 * A port as Live reads it now, for a review.
 *
 * @param port - The port and its reading.
 * @returns For example "dal-dist-02 Te1/0/48: up · 8% in, 14% out", or
 *   "…: not monitored" when nothing reads it.
 */
export function portNow(port: PortNow): string {
	const name = `${port.device} ${shortInterface(port.interface)}`;
	const r = port.reading;
	if (!r) return `${name}: not monitored`;
	if (r.stale) return `${name}: no recent reading`;
	if (r.oper === 'down') return `${name}: down`;
	return `${name}: up · ${Math.round(r.in_pct ?? 0)}% in, ${Math.round(r.out_pct ?? 0)}% out`;
}

/**
 * What Live says against accepting a fix: a port it takes out of the
 * documentation that still reads up.
 *
 * @param review - The review.
 * @returns A warning, or null if Live has nothing against it.
 */
export function reviewWarning(review: Review): string | null {
	const up = review.removes.filter((p) => p.reading?.oper === 'up' && !p.reading.stale);
	if (up.length === 0) return null;
	if (review.finding.fix?.kind === 'retire') {
		const where = up.length === 2 ? 'both ends' : 'one end';
		return (
			`Live shows it up and carrying traffic at ${where}: the link is likely there, ` +
			'hidden from LLDP and CDP (by a media converter, say). Retire it only if you know the cable is gone.'
		);
	}
	const [port] = up;
	return port
		? `Live shows ${port.device} ${shortInterface(port.interface)} up: something is still plugged into it.`
		: null;
}

/**
 * What accepting a fix would do, a line each.
 *
 * @param review - The review.
 * @returns Lines on redundancy, then on problems; empty if it changes neither.
 */
export function reviewEffects(review: Review): string[] {
	const lines = Object.entries(review.exposed).map(
		([device, via]) =>
			`${device} would depend on ${via.join(' and ')}${via.length === 1 ? ' alone' : ''}`
	);
	lines.push(...review.restored.map((d) => `${d} would have a second way to the core again`));
	lines.push(...review.cut_off.map((d) => `${d} would have no documented way to the core`));
	lines.push(...review.cleared.map((t) => `Clears “${t}”`));
	lines.push(...review.raised.map((t) => `Raises “${t}”`));
	return lines;
}
