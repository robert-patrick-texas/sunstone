/**
 * Overrides as every view uses them: the list fetched from `/api/overrides`,
 * kept here for any component to read, and what each kind does to what is
 * shown.
 *
 * The server applies what it works out from: locks, a site's new name, and
 * hiding from status come in the topology served, and aliases, new names,
 * and the two kinds on a port in discovery. The views apply the rest: a
 * device's or external node's new name wherever it is shown (its name in
 * the topology stays its key everywhere), tags and labels, and hiding from
 * the map. Only overrides that apply now (`active`) do anything; expired and
 * not-applied ones are listed so they can be renewed or withdrawn.
 *
 * Rules are overrides on everything that matches. The server works out
 * what each applies on (`matches`), after the overrides on single objects
 * and newer rules win where an object has one of a kind at a time, and
 * without its exceptions; the views apply a rule's tags, labels, hiding,
 * and locks there as if each were an override on that object (`Effect`).
 * Rules on ports tell discovery only, on the server. `on` and `onPorts`
 * list the overrides on single objects; `rulesOn` lists the rules on one.
 *
 * Mirrors `APPLIES_TO`, `LOCKABLE`, `SHOWN_ONLY`, `SINGLE`, `TESTS`, and
 * `RULE_APPLIES` in the backend's `overrides.py`.
 */
import type { Finding } from './api/discovery.ts';
import type {
	Excepted,
	Match,
	Override,
	OverrideKind,
	OverrideNow,
	Rule,
	RuleIn,
	RuleKind,
	RuleMatch,
	RuleNow,
	Target,
	TargetKind
} from './api/overrides.ts';
import type { Topology } from './api/topology.ts';
import { lagMembers, linkRoles } from './connections.ts';
import type { AnySelection } from './state.svelte.ts';
import { isDeviceEnd, shortInterface, type TopologyIndex } from './topology.ts';

/** Every override and rule not withdrawn, newest first, and whether hidden ones are drawn. */
export const overrides = $state({
	list: [] as OverrideNow[],
	rules: [] as RuleNow[],
	/** Draw what is hidden from the map anyway, for now (the legend's switch). */
	showHidden: false
});

const OBJECTS: readonly TargetKind[] = [
	'site',
	'device',
	'link',
	'lag',
	'external',
	'transport',
	'tunnel',
	'fabric',
	'resource',
	'network'
];

/** What each kind of override can be made on. */
export const APPLIES_TO: Record<OverrideKind, readonly TargetKind[]> = {
	rename: ['site', 'device', 'external'],
	alias: ['site', 'device', 'external'],
	tag: OBJECTS,
	label: OBJECTS,
	'hide-map': OBJECTS.filter((k) => k !== 'network'),
	'hide-status': ['site', 'device', 'link', 'lag', 'external'],
	lock: OBJECTS,
	'one-device': ['port'],
	'ignore-neighbor': ['port']
};

/** The fields a lock can keep, on each kind of object. */
export const LOCKABLE: Record<Exclude<TargetKind, 'port'>, readonly string[]> = {
	site: ['region', 'lat', 'lon'],
	device: ['site', 'role', 'platform', 'mgmt_ip', 'location', 'priority'],
	link: ['speed_mbps', 'kind', 'medium', 'priority', 'enterprise_cid'],
	lag: ['enterprise_cid'],
	external: ['kind', 'tenant', 'network', 'platform', 'description', 'priority'],
	transport: ['kind', 'provider', 'technology', 'description'],
	tunnel: ['technology', 'enterprise_cid'],
	fabric: ['technology', 'enterprise_cid'],
	resource: ['description'],
	network: ['tenant', 'description']
};

/** A lockable field, as people say it. */
export const FIELD_LABEL: Record<string, string> = {
	region: 'Region',
	lat: 'Latitude',
	lon: 'Longitude',
	site: 'Site',
	role: 'Role',
	platform: 'Platform',
	mgmt_ip: 'Management IP',
	location: 'Location',
	priority: 'Priority',
	speed_mbps: 'Speed (Mb/s)',
	kind: 'Kind',
	medium: 'Medium',
	enterprise_cid: 'Enterprise CID',
	tenant: 'Tenant',
	network: 'Network',
	description: 'Description',
	provider: 'Provider',
	technology: 'Technology'
};

/** Each kind, as a menu offers it. */
export const KIND_LABEL: Record<OverrideKind, string> = {
	rename: 'Rename',
	alias: 'Alias',
	tag: 'Tag',
	label: 'Label',
	'hide-map': 'Hide from the map',
	'hide-status': 'Hide from status',
	lock: 'Lock a field',
	'one-device': 'One device on this port',
	'ignore-neighbor': 'Ignore a neighbor'
};

/** Kinds only the views use: making one changes nothing the server works out. */
export const SHOWN_ONLY: readonly OverrideKind[] = ['tag', 'label', 'hide-map'];

/** Kinds an object has one of at a time (a lock and a label, one per key). */
export const SINGLE: readonly OverrideKind[] = [
	'rename',
	'label',
	'hide-map',
	'hide-status',
	'lock',
	'one-device'
];

let reloader: () => Promise<void> = async () => {};

/**
 * Say how to fetch the overrides again (the page does, at mount), so a form
 * anywhere can show what it made at once.
 *
 * @param reload - Fetches the list, and the topology too when the server applies a change.
 */
export function onReload(reload: () => Promise<void>): void {
	reloader = reload;
}

/**
 * Fetch the overrides again, after making, withdrawing, or renewing one.
 *
 * @returns Once the list, and anything that follows it, is fetched.
 */
export function reloadOverrides(): Promise<void> {
	return reloader();
}

/** The values a lock offers for fields with a fixed set, by field. */
export const CHOICES: Record<string, readonly string[]> = {
	role: ['wan-edge', 'core', 'distribution', 'access'],
	priority: ['ignored', 'low', 'medium', 'high'],
	medium: ['fiber', 'copper', 'twinax', 'radio', 'microwave', 'cellular', 'satellite']
};

/** The values a lock offers for a kind, by what has it. */
export const KIND_CHOICES: Partial<Record<TargetKind, readonly string[]>> = {
	link: ['lan', 'wan'],
	external: ['application', 'partner', 'tenant'],
	transport: ['internet', 'private-wan', 'research']
};

/**
 * A field's value on an object now, as a lock takes it.
 *
 * @param index - The topology.
 * @param of - The object.
 * @param field - The field.
 * @returns The value as text (a CID by its A side), or empty for none.
 */
export function fieldValue(index: TopologyIndex, of: Target, field: string): string {
	const found = objectOf(index, of) as Record<string, unknown> | undefined;
	const value = found?.[field];
	if (value === undefined || value === null) return '';
	if (typeof value === 'object' && 'a' in value) return String((value as { a: string }).a);
	return String(value);
}

/**
 * The object a target is on.
 *
 * @param index - The topology.
 * @param of - The target.
 * @returns The site, device, link, port channel, or other; a port's device;
 *   undefined when it is not in the topology.
 */
export function objectOf(index: TopologyIndex, of: Target): object | undefined {
	switch (of.kind) {
		case 'site':
			return index.sites.get(of.id);
		case 'device':
		case 'port':
			return index.devices.get(of.id);
		case 'link':
			return index.links.get(of.id);
		case 'lag':
			return index.topology.lags.find((g) => lagId(g) === of.id);
		case 'external':
			return index.externals.get(of.id);
		case 'transport':
			return index.transports.get(of.id);
		case 'tunnel':
			return index.tunnels.get(of.id);
		case 'fabric':
			return index.fabrics.get(of.id);
		case 'resource':
			return index.resources.get(of.id);
		case 'network':
			return index.networks.get(of.id);
	}
}

/** What an override is on, as a key: `device:dal-acc-01`, `port:dal-acc-01:Gi1/0/1`. */
export function targetKey(target: Target): string {
	return target.kind === 'port'
		? `port:${target.id}:${target.interface ?? ''}`
		: `${target.kind}:${target.id}`;
}

/** A target, from its kind and key; a port with its interface. */
export function target(kind: TargetKind, id: string, iface?: string): Target {
	return kind === 'port' ? { kind, id, interface: iface ?? null } : { kind, id, interface: null };
}

/**
 * What an override, or a rule on one object it applies on, does there: an
 * override as it is, or one made from the rule (`rule` set), active.
 */
export type Effect = OverrideNow & { rule?: RuleNow };

/** How a rule stands on one object. */
export interface RuleOn {
	rule: RuleNow;
	/** It applies there; an override on the object, or a newer rule, wins; or it is taken out. */
	how: 'applies' | 'overridden' | 'excepted';
	/** For a lock that applies, what the topology says where it differs. */
	topologyValue: string | null;
	/** Who took it out, and when. */
	excepted: Excepted | null;
}

/** A rule's effect on one object it applies on, as an override there. */
function fromRule(r: RuleNow, m: RuleMatch): Effect {
	return {
		id: `${r.id}:${targetKey(m.target)}`,
		target: m.target,
		kind: r.kind,
		key: r.key ?? null,
		value: r.value ?? null,
		note: r.note,
		by: r.by,
		at: r.at,
		expires: r.expires ?? null,
		renewed: r.renewed ?? null,
		withdrawn: null,
		state: 'active',
		reason: null,
		topology_value: m.topology_value ?? null,
		rule: r
	};
}

interface Derived {
	list: OverrideNow[];
	rules: RuleNow[];
	/** Overrides on single objects, whatever their state, by target. */
	byTarget: Map<string, OverrideNow[]>;
	/** What applies on each target: its own overrides that apply, then rules, newest first. */
	effects: Map<string, Effect[]>;
	/** Every effect, for what looks at them all (the map's hiding). */
	all: Effect[];
	/** The rules on each target: those applying, those overridden, those it is out of. */
	ruled: Map<string, RuleOn[]>;
	/** New names of devices and external nodes, by their name in the topology. */
	names: Map<string, string>;
	/** Whole words to replace in text, longest first; null for none. */
	pattern: RegExp | null;
}

let memo: Derived | null = null;

/** What the overrides that apply now say, worked out once per list. */
function derived(): Derived {
	const list = overrides.list;
	const rules = overrides.rules;
	if (memo && memo.list === list && memo.rules === rules) return memo;
	const byTarget = new Map<string, OverrideNow[]>();
	const effects = new Map<string, Effect[]>();
	const all: Effect[] = [];
	const ruled = new Map<string, RuleOn[]>();
	const add = <T>(map: Map<string, T[]>, key: string, item: T) => {
		const found = map.get(key);
		if (found) found.push(item);
		else map.set(key, [item]);
	};
	for (const o of list) {
		const key = targetKey(o.target);
		add(byTarget, key, o);
		if (o.state === 'active') {
			add(effects, key, o);
			all.push(o);
		}
	}
	for (const r of rules) {
		const onPorts = r.match.of === 'port';
		for (const m of r.matches) {
			const key = targetKey(m.target);
			const how = 'applies';
			add(ruled, key, { rule: r, how, topologyValue: m.topology_value ?? null, excepted: null });
			if (onPorts) continue;
			const effect = fromRule(r, m);
			add(effects, key, effect);
			all.push(effect);
		}
		for (const t of r.overridden) {
			add(ruled, targetKey(t), { rule: r, how: 'overridden', topologyValue: null, excepted: null });
		}
		for (const e of r.excepted) {
			add(ruled, targetKey(e.target), {
				rule: r,
				how: 'excepted',
				topologyValue: null,
				excepted: e
			});
		}
	}
	const names = new Map<string, string>();
	for (const o of list) {
		const kind = o.target.kind;
		if (o.state === 'active' && o.kind === 'rename' && o.value && kind !== 'site') {
			names.set(o.target.id, o.value);
		}
	}
	const keys = [...names.keys()].sort((a, b) => b.length - a.length).map(escape);
	const pattern = keys.length ? new RegExp(`(?<![\\w-])(${keys.join('|')})(?![\\w-])`, 'g') : null;
	memo = { list, rules, byTarget, effects, all, ruled, names, pattern };
	return memo;
}

function escape(text: string): string {
	return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * Every override on a target, whatever its state, newest first.
 *
 * @param of - The target.
 * @returns Them; none if there are none.
 */
export function on(of: Target): OverrideNow[] {
	return derived().byTarget.get(targetKey(of)) ?? [];
}

/** What applies now on a target of one kind: its own overrides, then rules'. */
function applying(of: Target, kind: OverrideKind): Effect[] {
	return (derived().effects.get(targetKey(of)) ?? []).filter((o) => o.kind === kind);
}

/**
 * Everything that applies now, overrides on single objects and rules on
 * each object they apply on alike.
 *
 * @returns The effects: overrides newest first, then rules newest first.
 */
export function effects(): Effect[] {
	return derived().all;
}

/**
 * The rules on a target: those that apply there, those an override on it
 * or a newer rule wins over, and those it is taken out of. A device has
 * the rules on its ports among them.
 *
 * @param of - The target; for rules on ports, a device.
 * @returns How each rule stands there, newest rule first.
 */
export function rulesOn(of: Target): RuleOn[] {
	return derived().ruled.get(targetKey(of)) ?? [];
}

/**
 * The name a device or external node is shown by.
 *
 * @param name - Its name in the topology, the key everything uses.
 * @returns Its new name, if renamed here; else the name itself.
 */
export function shown(name: string): string {
	return derived().names.get(name) ?? name;
}

/**
 * Text, as the server or a view wrote it with names from the topology,
 * with every device and external node renamed here given its new name.
 *
 * @param text - The text: a problem's title, a finding's detail.
 * @returns The text with whole names replaced.
 */
export function named(text: string): string {
	const { pattern, names } = derived();
	if (!pattern) return text;
	return text.replace(pattern, (key) => names.get(key) ?? key);
}

/**
 * The other names discovery and search match a site, device, or external
 * node by, here: its aliases, and its new name.
 *
 * @param of - The target.
 * @returns The names, aliases first.
 */
export function aliases(of: Target): string[] {
	return [...applying(of, 'alias'), ...applying(of, 'rename')].flatMap((o) =>
		o.value ? [o.value] : []
	);
}

/**
 * The tags added here, each with the rule it comes from, if it does.
 *
 * @param of - The target.
 * @returns The tags, its own oldest first, then rules', each once.
 */
export function tagged(of: Target): { value: string; rule: RuleNow | null }[] {
	const found = applying(of, 'tag');
	const own = found.filter((o) => !o.rule).reverse();
	const seen = new Set<string>();
	return [...own, ...found.filter((o) => o.rule)].flatMap((o) => {
		const value = o.value ?? '';
		if (!value || seen.has(value.toLowerCase())) return [];
		seen.add(value.toLowerCase());
		return [{ value, rule: o.rule ?? null }];
	});
}

/**
 * The tags added here.
 *
 * @param of - The target.
 * @returns The tags, its own oldest first, then rules', each once.
 */
export function tags(of: Target): string[] {
	return tagged(of).map((t) => t.value);
}

/**
 * The labels given here, each with the rule it comes from, if it does.
 *
 * @param of - The target.
 * @returns Each label's key and value, by key.
 */
export function labelled(of: Target): { key: string; value: string; rule: RuleNow | null }[] {
	const keys = new Set<string>();
	return applying(of, 'label')
		.flatMap((o) => {
			if (!o.key || !o.value || keys.has(o.key)) return [];
			keys.add(o.key);
			return [{ key: o.key, value: o.value, rule: o.rule ?? null }];
		})
		.sort((a, b) => a.key.localeCompare(b.key));
}

/**
 * The labels given here.
 *
 * @param of - The target.
 * @returns Each label's key and value, by key.
 */
export function labels(of: Target): { key: string; value: string }[] {
	return labelled(of).map(({ key, value }) => ({ key, value }));
}

/**
 * The lock on one field of a target: its own that applies, else a rule's
 * that applies there (`rule` set), else its own in any state.
 *
 * @param of - The target.
 * @param field - The field.
 * @returns The lock, or undefined.
 */
export function lockOf(of: Target, field: string): Effect | undefined {
	return (
		applying(of, 'lock').find((o) => o.key === field) ??
		on(of).find((o) => o.kind === 'lock' && o.key === field)
	);
}

/**
 * Whether a target is hidden from status here.
 *
 * @param of - The target.
 * @returns The override that hides it, or undefined.
 */
export function hiddenFromStatus(of: Target): Effect | undefined {
	return applying(of, 'hide-status')[0];
}

/**
 * Whether a target is hidden from the map here.
 *
 * @param of - The target.
 * @returns The override, or the rule's effect, that hides it; or undefined.
 */
export function hiddenFromMap(of: Target): Effect | undefined {
	return applying(of, 'hide-map')[0];
}

/**
 * The overrides on a device's ports, whatever their state.
 *
 * @param device - The device.
 * @returns Them, newest first.
 */
export function onPorts(device: string): OverrideNow[] {
	return overrides.list.filter((o) => o.target.kind === 'port' && o.target.id === device);
}

/** What is hidden from the map, each kind by its key, with what goes with it. */
export interface Hidden {
	sites: Set<string>;
	/** Devices hidden, and those at sites hidden. */
	devices: Set<string>;
	/** Links hidden, port channels' members, links of devices hidden, and
	 * links to external nodes and transports hidden. */
	links: Set<string>;
	externals: Set<string>;
	transports: Set<string>;
	tunnels: Set<string>;
	fabrics: Set<string>;
	resources: Set<string>;
	/** How many objects overrides and rules hide, for the legend. */
	count: number;
}

let hiddenMemo: { list: Effect[]; topology: Topology; show: boolean; found: Hidden } | null = null;

/**
 * What is hidden from the map now: nothing while the legend's switch shows
 * hidden things anyway.
 *
 * @param index - The topology, for what goes with a site, device, or port channel.
 * @returns What to leave out of every drawing; `count` is how many are hidden
 *   whether they are drawn or not.
 */
export function hiddenOnMap(index: TopologyIndex): Hidden {
	const list = effects();
	const show = overrides.showHidden;
	const t = index.topology;
	if (hiddenMemo && hiddenMemo.list === list && hiddenMemo.topology === t) {
		if (hiddenMemo.show === show) return hiddenMemo.found;
	}
	const hiding = list.filter((o) => o.kind === 'hide-map' && o.state === 'active');
	const found: Hidden = {
		sites: new Set(),
		devices: new Set(),
		links: new Set(),
		externals: new Set(),
		transports: new Set(),
		tunnels: new Set(),
		fabrics: new Set(),
		resources: new Set(),
		count: hiding.length
	};
	if (!show) {
		for (const { target: of } of hiding) {
			if (of.kind === 'site') {
				found.sites.add(of.id);
				for (const d of index.devicesBySite.get(of.id) ?? []) found.devices.add(d.name);
			} else if (of.kind === 'device') found.devices.add(of.id);
			else if (of.kind === 'link') found.links.add(of.id);
			else if (of.kind === 'lag') {
				const lag = t.lags.find((g) => lagId(g) === of.id);
				for (const l of lag ? lagMembers(t, lag) : []) found.links.add(l.id);
			} else if (of.kind === 'external') found.externals.add(of.id);
			else if (of.kind === 'transport') found.transports.add(of.id);
			else if (of.kind === 'tunnel') found.tunnels.add(of.id);
			else if (of.kind === 'fabric') found.fabrics.add(of.id);
			else if (of.kind === 'resource') found.resources.add(of.id);
		}
		for (const d of found.devices) {
			for (const l of index.linksByDevice.get(d) ?? []) found.links.add(l.id);
		}
		for (const l of t.links) {
			const b = l.b;
			if (isDeviceEnd(b)) continue;
			if ('external' in b ? found.externals.has(b.external) : found.transports.has(b.transport)) {
				found.links.add(l.id);
			}
		}
	}
	hiddenMemo = { list, topology: t, show, found };
	return found;
}

/** A port channel's id, as the backend gives it: both ends' `device:channel`, sorted. */
export function lagId(lag: Topology['lags'][number]): string {
	return [lag.a, lag.b]
		.map((e) => `${e.device}:${e.interface}`)
		.sort()
		.join('--');
}

/**
 * What a selection's overrides are on.
 *
 * @param selection - What is selected.
 * @returns Its target: a link selected alone, not several; none for a tenant.
 */
export function targetOf(selection: AnySelection): Target | null {
	switch (selection.kind) {
		case 'device':
		case 'site':
		case 'transport':
		case 'external':
		case 'network':
		case 'tunnel':
		case 'fabric':
		case 'resource':
			return target(selection.kind, selection.id);
		case 'links': {
			const [only, ...more] = selection.ids;
			return only && more.length === 0 ? target('link', only) : null;
		}
		default:
			return null;
	}
}

/**
 * A target as people say it.
 *
 * @param of - The target.
 * @param index - The topology, for a link's ends and a site's name; none for the key alone.
 * @returns "bhm-acc-01", "Site BHM (Birmingham)", "port bhm-wan-01 Gi0/0/1".
 */
export function targetName(of: Target, index?: TopologyIndex | null): string {
	switch (of.kind) {
		case 'port':
			return `${shown(of.id)} ${shortInterface(of.interface ?? '')}`;
		case 'device':
		case 'external':
			return shown(of.id);
		case 'site': {
			const site = index?.sites.get(of.id);
			return site && site.name !== of.id ? `${of.id} (${site.name})` : of.id;
		}
		case 'link': {
			const link = index?.links.get(of.id);
			if (!link) return of.id;
			const b = link.b;
			const far = isDeviceEnd(b) ? b.device : 'transport' in b ? b.transport : b.external;
			return `${shown(link.a.device)} – ${shown(far)}`;
		}
		case 'lag':
			return of.id
				.split('--')
				.map((end) => {
					const [device = '', channel = ''] = end.split(':');
					return `${shown(device)} ${shortInterface(channel)}`;
				})
				.join(' – ');
		default:
			return of.id;
	}
}

/**
 * An override in a few words, without its target.
 *
 * @param o - The override.
 * @returns "Renamed BRV-IAD-ENC01", "Role locked: distribution", "Ignores iad-wanopt-01".
 */
export function describe(o: Override): string {
	switch (o.kind) {
		case 'rename':
			return `Renamed ${o.value}`;
		case 'alias':
			return `Also known as ${o.value}`;
		case 'tag':
			return `Tag ${o.value}`;
		case 'label':
			return `Label ${o.key}: ${o.value}`;
		case 'hide-map':
			return 'Hidden from the map';
		case 'hide-status':
			return 'Hidden from status';
		case 'lock':
			return `${FIELD_LABEL[o.key ?? ''] ?? o.key} locked: ${o.value}`;
		case 'one-device':
			return `One device on this port: ${shown(o.value ?? '')}`;
		case 'ignore-neighbor':
			return `Ignores ${o.value}`;
	}
}

/**
 * What the server works out from the overrides, to tell when the topology,
 * live state, and discovery must be fetched again.
 *
 * @param list - The overrides.
 * @returns A key that changes when one the server applies starts or stops applying.
 */
export function signature(list: OverrideNow[], rules: RuleNow[] = []): string {
	const own = list
		.filter((o) => o.state === 'active' && !SHOWN_ONLY.includes(o.kind))
		.map((o) => o.id);
	const ruled = rules
		.filter((r) => r.state === 'active' && !SHOWN_ONLY.includes(r.kind))
		.map((r) => `${r.id}-${r.excepted.map((e) => targetKey(e.target)).join('+')}`);
	return [...own, ...ruled].sort().join();
}

/**
 * A key that changes whenever what the views apply changes: an override or
 * rule starting or stopping, or a rule applying on other objects.
 *
 * @returns The key.
 */
export function effectsKey(): string {
	const own = overrides.list.filter((o) => o.state === 'active').map((o) => o.id);
	const ruled = overrides.rules
		.filter((r) => r.state === 'active')
		.map((r) => `${r.id}-${r.matches.length}-${r.excepted.length}`);
	return [...own, ...ruled].join();
}

// Rules.

/** What a rule can test. */
export type TestField =
	| 'name'
	| 'site'
	| 'region'
	| 'role'
	| 'platform'
	| 'priority'
	| 'kind'
	| 'medium'
	| 'tenant'
	| 'tag'
	| 'interface';

/** Every test, in the order a form or a sentence gives them. */
export const TEST_FIELDS: readonly TestField[] = [
	'name',
	'site',
	'region',
	'role',
	'platform',
	'priority',
	'kind',
	'medium',
	'tenant',
	'tag',
	'interface'
];

/**
 * What a rule can test, on each kind of object. On a port, all but the
 * interface are its device's; on a link, the site and region are either
 * end's, the role is at the edge (`internal` between two of our devices,
 * `tbd` until documented), and the priority is its rating.
 */
export const TESTS: Record<TargetKind, readonly TestField[]> = {
	site: ['name', 'region', 'tag'],
	device: ['name', 'site', 'region', 'role', 'platform', 'priority', 'tag'],
	port: ['name', 'site', 'region', 'role', 'platform', 'tag', 'interface'],
	link: ['name', 'site', 'region', 'role', 'kind', 'medium', 'priority', 'tag'],
	lag: ['name', 'site', 'region', 'tag'],
	external: ['name', 'kind', 'tenant', 'platform', 'priority', 'tag'],
	transport: ['name', 'kind', 'tag'],
	tunnel: ['name', 'tag'],
	fabric: ['name', 'tag'],
	resource: ['name', 'tag'],
	network: ['name', 'tag']
};

/** A test, as a form labels it. */
export const TEST_LABEL: Record<TestField, string> = {
	name: 'Name',
	site: 'Site',
	region: 'Region',
	role: 'Role',
	platform: 'Platform',
	priority: 'Priority',
	kind: 'Kind',
	medium: 'Medium',
	tenant: 'Tenant',
	tag: 'Tag',
	interface: 'Interface'
};

/** Every kind of rule, as a menu offers them. */
export const RULE_KINDS: readonly RuleKind[] = [
	'tag',
	'label',
	'hide-map',
	'hide-status',
	'lock',
	'ignore-neighbor',
	'one-device'
];

/** What each kind of rule can be on: as each kind of override. */
export const RULE_APPLIES: Record<RuleKind, readonly TargetKind[]> = {
	tag: APPLIES_TO.tag,
	label: APPLIES_TO.label,
	'hide-map': APPLIES_TO['hide-map'],
	'hide-status': APPLIES_TO['hide-status'],
	lock: APPLIES_TO.lock,
	'ignore-neighbor': APPLIES_TO['ignore-neighbor'],
	'one-device': APPLIES_TO['one-device']
};

/** Each kind of rule, as a menu offers it. */
export const RULE_KIND_LABEL: Record<RuleKind, string> = {
	tag: 'Tag',
	label: 'Label',
	'hide-map': 'Hide from the map',
	'hide-status': 'Hide from status',
	lock: 'Lock a field',
	'ignore-neighbor': 'Ignore neighbors',
	'one-device': 'One device on each port'
};

/** Kinds of rule that take no value: on ports, one device goes by the name its rows give. */
export const RULE_UNVALUED: readonly RuleKind[] = ['hide-map', 'hide-status', 'one-device'];

/** Each kind of object, one and many. */
export const NOUNS: Record<TargetKind, readonly [string, string]> = {
	site: ['site', 'sites'],
	device: ['device', 'devices'],
	link: ['link', 'links'],
	lag: ['port channel', 'port channels'],
	external: ['external node', 'external nodes'],
	transport: ['transport', 'transports'],
	tunnel: ['tunnel', 'tunnels'],
	fabric: ['fabric', 'fabrics'],
	resource: ['resource', 'resources'],
	network: ['network', 'networks'],
	port: ['port', 'ports']
};

/** A rule as a form makes it, before who makes it is added. */
export type RuleDraft = Omit<RuleIn, 'by'>;

/**
 * Tests that match everything of a kind.
 *
 * @param of - The kind of object.
 * @returns The match, every test empty.
 */
export function emptyMatch(of: TargetKind): Match {
	return {
		of,
		name: [],
		site: [],
		region: [],
		role: [],
		platform: [],
		priority: [],
		kind: [],
		medium: [],
		tenant: [],
		tag: [],
		interface: []
	};
}

/** Values as a sentence says them: "a", "a or b", "a, b, or c". */
function or(values: readonly string[]): string {
	if (values.length <= 2) return values.join(' or ');
	return `${values.slice(0, -1).join(', ')}, or ${values.at(-1)}`;
}

/** How a sentence gives each test, before its values. */
const TEST_WORDS: Record<Exclude<TestField, 'interface'>, string> = {
	name: 'named',
	site: 'at',
	region: 'in',
	role: 'with role',
	platform: 'on platform',
	priority: 'rated',
	kind: 'of kind',
	medium: 'over',
	tenant: 'of tenant',
	tag: 'tagged'
};

/**
 * What a rule matches, in a sentence.
 *
 * @param m - The tests.
 * @returns "Every device with role access, on platform ISR4431 or C9200-24T";
 *   "Port Gi1/0/48 on every device with role access".
 */
export function matchText(m: Match): string {
	const of = m.of === 'port' ? 'device' : m.of;
	const head =
		m.of === 'port'
			? `Port ${or(m.interface.map(shortInterface))} on every ${NOUNS.device[0]}`
			: `Every ${NOUNS[of][0]}`;
	const parts = TEST_FIELDS.flatMap((f) => {
		if (f === 'interface' || !m[f].length) return [];
		const words = f === 'role' && m.of === 'link' ? 'with role at the edge' : TEST_WORDS[f];
		return [`${words} ${or(m[f])}`];
	});
	return parts.length ? `${head} ${parts.join(', ')}` : head;
}

/**
 * What a rule does, in a few words, without what it matches.
 *
 * @param r - The rule, or a draft of one.
 * @returns "Tag lab", "Ignores *-acc-*", "Priority locked: low", "One device on each port".
 */
export function describeRule(r: Pick<Rule, 'kind' | 'key' | 'value'>): string {
	switch (r.kind) {
		case 'tag':
			return `Tag ${r.value}`;
		case 'label':
			return `Label ${r.key}: ${r.value}`;
		case 'hide-map':
			return 'Hidden from the map';
		case 'hide-status':
			return 'Hidden from status';
		case 'lock':
			return `${FIELD_LABEL[r.key ?? ''] ?? r.key} locked: ${r.value}`;
		case 'ignore-neighbor':
			return r.value === '*' ? 'Ignores every neighbor' : `Ignores ${r.value}`;
		case 'one-device':
			return 'One device on each port';
	}
}

/**
 * A name for a rule, until someone gives it one.
 *
 * @param r - The draft.
 * @returns "Hidden from status: every device with role access", at most 80 characters.
 */
export function ruleName(r: Pick<RuleDraft, 'kind' | 'key' | 'value' | 'match'>): string {
	const text = `${describeRule(r)}: ${matchText(r.match).replace(/^Every/, 'every')}`;
	return text.length <= 80 ? text : `${text.slice(0, 79)}…`;
}

/**
 * A rule like an override on one object ("Make a rule like this…"): the
 * same kind, key, and value, on every object of its kind with the same
 * role and platform (a device, a port's device), region (a site), roles and
 * kind (a link), or kind and tenant (an external node); anything else, by
 * its name, to widen.
 *
 * @param o - The override; not a rename or an alias, which are about one object.
 * @param index - The topology.
 * @returns The draft, to change before it is made.
 */
export function presetFrom(o: Override, index: TopologyIndex): RuleDraft {
	const t = o.target;
	const match = emptyMatch(t.kind);
	switch (t.kind) {
		case 'device':
		case 'port': {
			const d = index.devices.get(t.id);
			if (d) {
				match.role = [d.role];
				if (d.platform) match.platform = [d.platform];
			}
			if (t.kind === 'port') match.interface = [shortInterface(t.interface ?? '')];
			break;
		}
		case 'site': {
			const region = index.sites.get(t.id)?.region;
			if (region) match.region = [region];
			else match.name = [t.id];
			break;
		}
		case 'link': {
			const link = index.links.get(t.id);
			if (link) {
				const roles = linkRoles(index.topology, link);
				match.role = roles.edges.length
					? [...roles.edges]
					: [roles.source === 'tbd' ? 'tbd' : 'internal'];
				match.kind = [link.kind];
			}
			break;
		}
		case 'external': {
			const e = index.externals.get(t.id);
			if (e) {
				match.kind = [e.kind];
				if (e.tenant) match.tenant = [e.tenant];
			}
			break;
		}
		default:
			match.name = [t.id];
	}
	const kind = o.kind as RuleKind;
	const draft = {
		match,
		kind,
		key: o.key ?? null,
		value: RULE_UNVALUED.includes(kind) ? null : (o.value ?? null),
		note: o.note,
		expires: null
	};
	return { name: ruleName(draft), ...draft };
}

/** A rule a run of discovery findings offers. */
export interface RuleOffer {
	/** "Rule: ignore *-acc-* on Gi1/0/48 of every access device…" */
	label: string;
	draft: RuleDraft;
	/** The findings it is offered for. */
	findings: string[];
}

/** Finding kinds a rule ignoring neighbors on ports is offered for. */
const OFFERED_FOR: readonly Finding['kind'][] = ['undocumented', 'unknown-device'];

/**
 * The rules repeated findings offer: a cable no one documented, or a
 * neighbor not in the topology, seen on the same port of two or more of our
 * devices with one role, as access switches daisy-chained on port 48 are;
 * one offer for each kind of finding, so lab switches plugged in there are
 * not ignored with the chains.
 * Each ignores, on that port of every device with that role, neighbors
 * named like those seen (`namePattern`).
 *
 * @param findings - The latest run's findings.
 * @param index - The topology.
 * @returns The offers, the most findings first.
 */
export function ruleOffers(findings: readonly Finding[], index: TopologyIndex): RuleOffer[] {
	const groups = new Map<
		string,
		{ role: string; port: string; devices: Set<string>; far: Set<string>; ids: Set<string> }
	>();
	for (const f of findings) {
		if (!OFFERED_FOR.includes(f.kind)) continue;
		for (const [i, end] of f.seen.entries()) {
			const device = index.devices.get(end.device);
			const far = f.seen[1 - i];
			if (!device || !far) continue;
			const port = shortInterface(end.interface);
			const key = `${f.kind}|${device.role}|${port.toLowerCase()}`;
			const group = groups.get(key) ?? {
				role: device.role,
				port,
				devices: new Set(),
				far: new Set(),
				ids: new Set()
			};
			group.devices.add(device.name);
			group.far.add(far.device);
			group.ids.add(f.id);
			groups.set(key, group);
		}
	}
	return [...groups.values()]
		.filter((g) => g.devices.size >= 2)
		.sort((a, b) => b.ids.size - a.ids.size)
		.map((g) => {
			const match = { ...emptyMatch('port'), role: [g.role], interface: [g.port] };
			const value = namePattern([...g.far], index);
			const draft = {
				match,
				kind: 'ignore-neighbor' as const,
				key: null,
				value,
				note: '',
				expires: null
			};
			return {
				label: `Rule: ignore ${value} on ${g.port} of every ${g.role} device…`,
				draft: { name: `Port ${g.port} on ${g.role} devices`, ...draft },
				findings: [...g.ids]
			};
		});
}

/**
 * A pattern matching every name given, and others like them: parts
 * (between hyphens) that differ, numbers, and parts that are a device's own
 * site code, as `*`; names without the same parts, by what they start with.
 *
 * @param names - The names.
 * @param index - The topology, for each device's site.
 * @returns "*-acc-*", "SEP0040*", or "*".
 */
export function namePattern(names: readonly string[], index: TopologyIndex): string {
	const split = names.map((n) => n.split('-'));
	const [first] = split;
	if (!first) return '*';
	const sites = names.map((n) => index.devices.get(n)?.site?.toLowerCase());
	if (first.length > 1 && split.every((p) => p.length === first.length)) {
		const parts = first.map((part, i) =>
			/^\d+$/.test(part) || split.some((p, j) => p[i] !== part || p[i]?.toLowerCase() === sites[j])
				? '*'
				: part
		);
		return parts.join('-').replace(/\*(-\*)+/g, '*');
	}
	let start = names[0] ?? '';
	for (const n of names) while (!n.startsWith(start)) start = start.slice(0, -1);
	return `${start}*`;
}
