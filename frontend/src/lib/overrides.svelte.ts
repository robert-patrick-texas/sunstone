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
 * Mirrors `APPLIES_TO`, `LOCKABLE`, `SHOWN_ONLY`, and `SINGLE` in the
 * backend's `overrides.py`.
 */
import type { Override, OverrideKind, OverrideNow, Target, TargetKind } from './api/overrides.ts';
import type { Topology } from './api/topology.ts';
import { lagMembers } from './connections.ts';
import type { AnySelection } from './state.svelte.ts';
import { isDeviceEnd, shortInterface, type TopologyIndex } from './topology.ts';

/** Every override not withdrawn, newest first, and whether hidden ones are drawn. */
export const overrides = $state({
	list: [] as OverrideNow[],
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

interface Derived {
	list: OverrideNow[];
	byTarget: Map<string, OverrideNow[]>;
	/** New names of devices and external nodes, by their name in the topology. */
	names: Map<string, string>;
	/** Whole words to replace in text, longest first; null for none. */
	pattern: RegExp | null;
}

let memo: Derived | null = null;

/** What the overrides that apply now say, worked out once per list. */
function derived(): Derived {
	const list = overrides.list;
	if (memo && memo.list === list) return memo;
	const byTarget = new Map<string, OverrideNow[]>();
	for (const o of list) {
		const key = targetKey(o.target);
		byTarget.set(key, [...(byTarget.get(key) ?? []), o]);
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
	memo = { list, byTarget, names, pattern };
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

/** The overrides of one kind that apply now on a target. */
function applying(of: Target, kind: OverrideKind): OverrideNow[] {
	return on(of).filter((o) => o.kind === kind && o.state === 'active');
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
 * The tags added here.
 *
 * @param of - The target.
 * @returns The tags, oldest first.
 */
export function tags(of: Target): string[] {
	return applying(of, 'tag')
		.flatMap((o) => (o.value ? [o.value] : []))
		.reverse();
}

/**
 * The labels given here.
 *
 * @param of - The target.
 * @returns Each label's key and value, by key.
 */
export function labels(of: Target): { key: string; value: string }[] {
	return applying(of, 'label')
		.flatMap((o) => (o.key && o.value ? [{ key: o.key, value: o.value }] : []))
		.sort((a, b) => a.key.localeCompare(b.key));
}

/**
 * The lock on one field of a target, whatever its state.
 *
 * @param of - The target.
 * @param field - The field.
 * @returns The lock, or undefined.
 */
export function lockOf(of: Target, field: string): OverrideNow | undefined {
	return on(of).find((o) => o.kind === 'lock' && o.key === field);
}

/**
 * Whether a target is hidden from status here.
 *
 * @param of - The target.
 * @returns The override that hides it, or undefined.
 */
export function hiddenFromStatus(of: Target): OverrideNow | undefined {
	return applying(of, 'hide-status')[0];
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
	/** How many overrides hide something, for the legend. */
	count: number;
}

let hiddenMemo: { list: OverrideNow[]; topology: Topology; show: boolean; found: Hidden } | null =
	null;

/**
 * What is hidden from the map now: nothing while the legend's switch shows
 * hidden things anyway.
 *
 * @param index - The topology, for what goes with a site, device, or port channel.
 * @returns What to leave out of every drawing; `count` is how many are hidden
 *   whether they are drawn or not.
 */
export function hiddenOnMap(index: TopologyIndex): Hidden {
	const list = overrides.list;
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
export function signature(list: OverrideNow[]): string {
	return list
		.filter((o) => o.state === 'active' && !SHOWN_ONLY.includes(o.kind))
		.map((o) => o.id)
		.sort()
		.join();
}
