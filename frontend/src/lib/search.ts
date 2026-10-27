/**
 * One search over everything Sunstone knows by name: sites, devices, links
 * (by circuit, carrier, or the device and interface at either end),
 * problems, maintenance windows, on-call teams and people, and commands.
 *
 * Every word typed must match something about an entry. A match counts for
 * more when it is a whole name than when it starts one, when it starts a
 * name than when it starts a word inside it, and when it is in a name than
 * in, say, the region a site is in. Interfaces match in full or IOS short
 * form (`TenGigabitEthernet1/0/1` or `Te1/0/1`), and an address range
 * (`10.1.0.0/16`) finds the devices whose management address is in it.
 * Results come grouped by kind, the group with the best match first, and
 * problems first among equals, since a problem is likely why someone is looking.
 */
import type { Problem } from './api/analysis.ts';
import type { OnCall } from './api/oncall.ts';
import type { Window } from './api/operations.ts';
import type { Command, CommandId } from './commands.ts';
import { span, targetName } from './maintenance.ts';
import { KINDS } from './problem-kinds.ts';
import type { Selection } from './state.svelte.ts';
import {
	compareNatural,
	formatSpeed,
	ROLE_LABEL,
	shortInterface,
	siteOf,
	type TopologyIndex
} from './topology.ts';
import { readItem, writeItem } from './url.ts';

export type EntryKind =
	'problem' | 'site' | 'device' | 'link' | 'window' | 'team' | 'person' | 'command';

/** What choosing an entry goes to. */
export type Target =
	| { kind: 'item'; item: Selection }
	| { kind: 'problem'; problem: Problem }
	| { kind: 'window'; window: Window }
	| { kind: 'team'; team: string }
	| { kind: 'command'; command: CommandId };

/**
 * Where a word may match in a field: anywhere (names, where `core` inside
 * `dalcore01` should still match), only at the start of a word (prose, where
 * `hou` should not match "without"), or only at the start of the field
 * (addresses, where `0.3` inside every address would match everything).
 */
type Mode = 'anywhere' | 'words' | 'start';

interface Field {
	/** Lower case. */
	text: string;
	weight: number;
	mode: Mode;
}

export interface Entry {
	kind: EntryKind;
	/** Unique among entries of its kind. */
	key: string;
	label: string;
	detail: string;
	target: Target;
	fields: Field[];
	/** Every field's text, to rule most entries out at once. */
	haystack: string;
	/** A device's management address, as a number, for address ranges. */
	address?: number;
}

export interface Group {
	kind: EntryKind;
	label: string;
	entries: Entry[];
	/** How many more matched than are listed. */
	more: number;
}

// How much a match in each field counts.
const NAME = 3;
const ALIAS = 2;
const PART = 1.5;
const CONTEXT = 1;

const GROUPS: { kind: EntryKind; label: string; limit: number }[] = [
	{ kind: 'problem', label: 'Problems', limit: 5 },
	{ kind: 'site', label: 'Sites', limit: 5 },
	{ kind: 'device', label: 'Devices', limit: 8 },
	{ kind: 'link', label: 'Links', limit: 6 },
	{ kind: 'window', label: 'Maintenance', limit: 4 },
	{ kind: 'team', label: 'Teams', limit: 4 },
	{ kind: 'person', label: 'People', limit: 5 },
	{ kind: 'command', label: 'Commands', limit: 4 }
];

const field = (text: string | null | undefined, weight: number, mode: Mode = 'anywhere') =>
	text ? [{ text: text.toLowerCase(), weight, mode }] : [];

/** An interface by its full name and its short form. */
const interfaceFields = (name: string | null | undefined, weight: number): Field[] =>
	name ? [...new Set([name, shortInterface(name)])].flatMap((n) => field(n, weight)) : [];

function entry(
	head: { kind: EntryKind; key: string; label: string; detail: string },
	target: Target,
	fields: Field[],
	address?: number
): Entry {
	const haystack = fields.map((f) => f.text).join('\n');
	return { ...head, target, fields, haystack, ...(address === undefined ? {} : { address }) };
}

/**
 * An IPv4 address as a number.
 *
 * @param text - For example `10.1.0.3`.
 * @returns The address, or null if it is not one.
 */
export function ipv4(text: string): number | null {
	const parts = text.split('.');
	if (parts.length !== 4 || !parts.every((p) => /^\d{1,3}$/.test(p) && Number(p) <= 255)) {
		return null;
	}
	return parts.reduce((n, p) => n * 256 + Number(p), 0);
}

/** An address range such as `10.1.0.0/16`, as its first and last addresses. */
function range(text: string): [number, number] | null {
	const [address, bits, extra] = text.split('/');
	const start = ipv4(address ?? '');
	const length = Number(bits);
	if (start === null || extra !== undefined || !/^\d{1,2}$/.test(bits ?? '') || length > 32) {
		return null;
	}
	const size = 2 ** (32 - length);
	const first = Math.floor(start / size) * size;
	return [first, first + size - 1];
}

/**
 * The entry for a device, site, or links.
 *
 * @param index - Topology index.
 * @param item - The device, site, or links.
 * @returns The entry, or null if it is not in the network.
 */
export function itemEntry(index: TopologyIndex, item: Selection): Entry | null {
	const target: Target = { kind: 'item', item };
	const key = writeItem(item);
	if (item.kind === 'site') {
		const site = index.sites.get(item.id);
		if (!site) return null;
		const devices = index.devicesBySite.get(site.code)?.length ?? 0;
		return entry(
			{
				kind: 'site',
				key,
				label: `${site.code} · ${site.name}`,
				detail: [site.region, `${devices} devices`].filter(Boolean).join(' · ')
			},
			target,
			[
				...field(site.code, NAME),
				...field(site.name, NAME),
				...field(site.region, CONTEXT, 'words')
			]
		);
	}
	if (item.kind === 'device') {
		const device = index.devices.get(item.id);
		if (!device) return null;
		const site = index.sites.get(device.site);
		return entry(
			{
				kind: 'device',
				key,
				label: device.name,
				detail: [ROLE_LABEL[device.role], device.site, device.mgmt_ip].filter(Boolean).join(' · ')
			},
			target,
			[
				...field(device.name, NAME),
				...field(device.mgmt_ip, NAME, 'start'),
				...field(device.platform, PART),
				...field(ROLE_LABEL[device.role], CONTEXT, 'words'),
				...field(device.site, CONTEXT),
				...field(site?.name, CONTEXT)
			],
			ipv4(device.mgmt_ip ?? '') ?? undefined
		);
	}
	const links = item.ids.flatMap((id) => index.links.get(id) ?? []);
	const [link] = links;
	if (!link) return null;
	if (links.length > 1) {
		// Only ever recent: a bundle selected on the map, not something search finds.
		const sites = new Set(
			links.flatMap((l) => [l.a.device, l.b.device].map((d) => siteOf(index, d)))
		);
		return entry(
			{ kind: 'link', key, label: targetName(index, item), detail: [...sites].join(' – ') },
			target,
			[]
		);
	}
	const ends = `${link.a.device} ${shortInterface(link.a.interface)} – ${link.b.device} ${shortInterface(link.b.interface)}`;
	const speed = formatSpeed(link.speed_mbps);
	const lag = link.a.lag ?? link.b.lag;
	return entry(
		{
			kind: 'link',
			key,
			label: link.circuit ? `Circuit ${link.circuit.circuit_id}` : ends,
			detail: link.circuit
				? `${link.circuit.provider} · ${link.a.device} – ${link.b.device} · ${speed}`
				: [speed, lag].filter(Boolean).join(' · ')
		},
		target,
		[
			...field(link.circuit?.circuit_id, NAME),
			...field(link.circuit?.provider, ALIAS),
			...field(link.a.device, PART),
			...field(link.b.device, PART),
			...interfaceFields(link.a.interface, PART),
			...interfaceFields(link.b.interface, PART),
			...interfaceFields(link.a.lag, CONTEXT),
			...interfaceFields(link.b.lag, CONTEXT)
		]
	);
}

/**
 * Entries for every site, device, and link, built once per topology.
 *
 * @param index - Topology index.
 * @returns The entries.
 */
export function topologyEntries(index: TopologyIndex): Entry[] {
	const items: Selection[] = [
		...index.topology.sites.map((s) => ({ kind: 'site' as const, id: s.code })),
		...index.topology.devices.map((d) => ({ kind: 'device' as const, id: d.name })),
		...index.topology.links.map((l) => ({ kind: 'links' as const, ids: [l.id] }))
	];
	return items.flatMap((item) => itemEntry(index, item) ?? []);
}

/** Names something goes by: a device's, a site's code and name, a link's circuit and devices. */
function namesOf(index: TopologyIndex, item: Selection): string[] {
	if (item.kind === 'device') return [item.id];
	if (item.kind === 'site') return [item.id, index.sites.get(item.id)?.name ?? ''];
	return item.ids.flatMap((id) => {
		const link = index.links.get(id);
		return link ? [link.circuit?.circuit_id ?? '', link.a.device, link.b.device] : [];
	});
}

/**
 * Entries for the problems shown.
 *
 * @param index - Topology index.
 * @param problems - Problems.
 * @returns The entries, found by title, what they are about, and who is on them.
 */
export function problemEntries(index: TopologyIndex, problems: Problem[]): Entry[] {
	return problems.map((problem) =>
		entry(
			{
				kind: 'problem',
				key: problem.id,
				label: problem.title,
				detail: problem.detail || (KINDS.find((k) => k.kind === problem.kind)?.label ?? '')
			},
			{ kind: 'problem', problem },
			[
				...field(problem.title, NAME),
				...field(problem.detail, CONTEXT, 'words'),
				...field(KINDS.find((k) => k.kind === problem.kind)?.short, CONTEXT, 'words'),
				...namesOf(index, problem.target).flatMap((n) => field(n, ALIAS)),
				...field(problem.ack?.note, CONTEXT, 'words'),
				...field(problem.ack?.by, CONTEXT)
			]
		)
	);
}

/**
 * Entries for maintenance windows.
 *
 * @param index - Topology index.
 * @param windows - Maintenance windows.
 * @returns The entries, found by title, note, who planned them, and what they work on.
 */
export function windowEntries(index: TopologyIndex, windows: Window[]): Entry[] {
	return windows.map((window) =>
		entry(
			{
				kind: 'window',
				key: window.id,
				label: window.title,
				detail: `${span(window)} · ${window.targets.map((t) => targetName(index, t)).join(', ')}`
			},
			{ kind: 'window', window },
			[
				...field(window.title, NAME),
				...field(window.note, CONTEXT, 'words'),
				...field(window.by, CONTEXT),
				...window.targets.flatMap((t) => namesOf(index, t).flatMap((n) => field(n, ALIAS)))
			]
		)
	);
}

/**
 * Entries for on-call teams and the people on them.
 *
 * @param oncall - Who is on call.
 * @returns A team is found by name or what it owns; a person by name or
 *   phone number, and leads to their team.
 */
export function oncallEntries(oncall: OnCall): Entry[] {
	const teams = oncall.teams.map((team) =>
		entry(
			{ kind: 'team', key: team.id, label: team.name, detail: team.owns.join('; ') },
			{ kind: 'team', team: team.id },
			[...field(team.name, NAME), ...team.owns.flatMap((o) => field(o, CONTEXT, 'words'))]
		)
	);
	const people = oncall.people.flatMap((person) => {
		const theirs = oncall.teams.filter(
			(t) => t.rotation.includes(person.id) || t.manager === person.id
		);
		const [first] = theirs;
		if (!first) return [];
		const now = theirs.find((t) => t.now.primary === person.id);
		return [
			entry(
				{
					kind: 'person',
					key: person.id,
					label: person.name,
					detail: [
						now ? `On call for ${now.name}` : theirs.map((t) => t.name).join(', '),
						person.phone
					]
						.filter(Boolean)
						.join(' · ')
				},
				{ kind: 'team', team: (now ?? first).id },
				[...field(person.name, NAME), ...field(person.phone, CONTEXT)]
			)
		];
	});
	return [...teams, ...people];
}

/**
 * Entries for commands, found by the start of any word in them.
 *
 * @param commands - The commands that can run now.
 * @returns The entries; the detail is the keys that also run each one.
 */
export function commandEntries(commands: Command[]): Entry[] {
	return commands.map((command) =>
		entry(
			{ kind: 'command', key: command.id, label: command.label, detail: command.keys.join(' or ') },
			{ kind: 'command', command: command.id },
			[
				...field(command.label, NAME, 'words'),
				...(command.also ?? []).flatMap((a) => field(a, ALIAS, 'words'))
			]
		)
	);
}

/**
 * Entries for what was looked at recently.
 *
 * @param index - Topology index.
 * @param recent - Items as links write them, newest first.
 * @returns The entries, skipping anything no longer in the network.
 */
export function recentEntries(index: TopologyIndex, recent: string[]): Entry[] {
	return recent.flatMap((r) => {
		const item = readItem(r, index);
		return (item && itemEntry(index, item)) ?? [];
	});
}

interface Word {
	/** As typed, and in short form if it is an interface name. */
	forms: string[];
	range: [number, number] | null;
}

/**
 * How well a word matches a field.
 *
 * @returns 1 for the whole field, 0.8 for its start, 0.6 for the start of a
 *   word in it, 0.3 for anywhere else, 0 for no match.
 */
function quality(text: string, word: string, mode: Mode): number {
	if (text === word) return 1;
	if (text.startsWith(word)) return 0.8;
	if (mode === 'start') return 0;
	let inside = false;
	for (let at = text.indexOf(word, 1); at > 0; at = text.indexOf(word, at + 1)) {
		if (!/[a-z0-9]/.test(text.charAt(at - 1))) return 0.6;
		inside = true;
	}
	// One letter inside a name matches nearly everything, so it has to start a word.
	return inside && mode === 'anywhere' && word.length > 1 ? 0.3 : 0;
}

function score(entry: Entry, words: Word[]): number {
	let total = 0;
	for (const word of words) {
		if (word.range) {
			const inRange =
				entry.address !== undefined &&
				entry.address >= word.range[0] &&
				entry.address <= word.range[1];
			if (!inRange) return 0;
			total += NAME;
			continue;
		}
		if (!word.forms.some((f) => entry.haystack.includes(f))) return 0;
		let best = 0;
		for (const f of entry.fields) {
			for (const form of word.forms)
				best = Math.max(best, quality(f.text, form, f.mode) * f.weight);
		}
		if (best === 0) return 0;
		total += best;
	}
	return total;
}

/**
 * Search entries.
 *
 * @param query - What was typed.
 * @param lists - Entries to search, in lists of any kinds.
 * @returns Groups with any matches, the one with the best match first (problems
 *   first among equals); within each, best match first. Empty for an empty query.
 */
export function search(query: string, lists: Entry[][]): Group[] {
	const words: Word[] = query
		.toLowerCase()
		.split(/[\s,]+/)
		.filter(Boolean)
		.map((w) => ({ forms: [...new Set([w, shortInterface(w).toLowerCase()])], range: range(w) }));
	if (words.length === 0) return [];
	const found = new Map<EntryKind, { entry: Entry; score: number }[]>(
		GROUPS.map((g) => [g.kind, []])
	);
	for (const list of lists) {
		for (const e of list) {
			const s = score(e, words);
			if (s > 0) found.get(e.kind)?.push({ entry: e, score: s });
		}
	}
	// Devices in an address range are listed in address order.
	const byAddress = words.some((w) => w.range);
	const ranked = GROUPS.flatMap(({ kind, label, limit }) => {
		const matches = (found.get(kind) ?? []).sort(
			(x, y) =>
				y.score - x.score ||
				(byAddress ? (x.entry.address ?? 0) - (y.entry.address ?? 0) : 0) ||
				compareNatural(x.entry.label, y.entry.label)
		);
		const entries = matches.slice(0, limit).map((m) => m.entry);
		const group: Group = { kind, label, entries, more: matches.length - entries.length };
		return entries.length ? [{ group, best: matches[0]?.score ?? 0 }] : [];
	});
	// Stable, so equally good groups keep the order of GROUPS, problems first.
	ranked.sort((x, y) => y.best - x.best);
	return ranked.map((r) => r.group);
}
