/**
 * Lookups over a loaded topology, and the formatting every view shares.
 */
import type {
	Device,
	Endpoint,
	External,
	Fabric,
	FarEnd,
	Link,
	NamedNetwork,
	Role,
	Site,
	Tenant,
	Topology,
	Transport,
	Tunnel
} from './api/topology.ts';

/** Roles from the top of the hierarchy down. */
export const ROLES: readonly Role[] = ['wan-edge', 'core', 'distribution', 'access'];

export const ROLE_LABEL: Record<Role, string> = {
	'wan-edge': 'WAN edge',
	core: 'Core',
	distribution: 'Distribution',
	access: 'Access'
};

export interface TopologyIndex {
	topology: Topology;
	sites: Map<string, Site>;
	devices: Map<string, Device>;
	links: Map<string, Link>;
	linksByDevice: Map<string, Link[]>;
	/** Links into each transport and to each external node, by {@link nodeKey}. */
	linksByNode: Map<string, Link[]>;
	/** Devices of each site, top tier first, then in natural name order. */
	devicesBySite: Map<string, Device[]>;
	networks: Map<string, NamedNetwork>;
	transports: Map<string, Transport>;
	externals: Map<string, External>;
	tenants: Map<string, Tenant>;
	tunnels: Map<string, Tunnel>;
	fabrics: Map<string, Fabric>;
}

/** One link seen from one of its devices. */
export interface Neighbor {
	link: Link;
	local: Endpoint;
	remote: FarEnd;
}

/**
 * Whether a link end is one of the network's own devices.
 *
 * @param end - A link end.
 * @returns True for a device's interface; false for a transport or external node.
 */
export function isDeviceEnd(end: FarEnd): end is Endpoint {
	return 'device' in end;
}

/**
 * The ends of a link that are devices.
 *
 * @param link - A link.
 * @returns Both ends, or the A end alone for a link into a transport or to an
 *   external node (the A end is always a device).
 */
export function deviceEnds(link: Link): Endpoint[] {
	return isDeviceEnd(link.b) ? [link.a, link.b] : [link.a];
}

/**
 * The device at a link's B end.
 *
 * @param link - A link.
 * @returns Its name, or null when the B end is a transport or external node.
 */
export function farDevice(link: Link): string | null {
	return isDeviceEnd(link.b) ? link.b.device : null;
}

/**
 * The key a transport or external node goes by, as link ids write it.
 *
 * @param end - A link end that is not a device.
 * @returns `transport:NAME` or `external:NAME`.
 */
export function nodeKey(end: Exclude<FarEnd, Endpoint>): string {
	return 'transport' in end ? `transport:${end.transport}` : `external:${end.external}`;
}

/**
 * What a link end is called.
 *
 * @param end - A link end.
 * @returns Its device, transport, or external node.
 */
export function endName(end: FarEnd): string {
	if (isDeviceEnd(end)) return end.device;
	return 'transport' in end ? end.transport : end.external;
}

/**
 * A link end as people say it.
 *
 * @param end - A link end.
 * @returns A device and its short port name (`dal-wan-01 Gi0/0/0`), or the
 *   transport or external node, with its port when known.
 */
export function portName(end: FarEnd): string {
	if (isDeviceEnd(end)) return `${end.device} ${shortInterface(end.interface)}`;
	if ('transport' in end) return end.transport;
	return end.interface ? `${end.external} ${end.interface}` : end.external;
}

/** Compares strings with embedded numbers naturally: `Te1/0/2` before `Te1/0/10`. */
export const compareNatural = new Intl.Collator('en', { numeric: true }).compare;

/**
 * Build the lookups the views need.
 *
 * @param topology - Topology from the API.
 * @returns The index.
 */
export function indexTopology(topology: Topology): TopologyIndex {
	const linksByDevice = new Map<string, Link[]>();
	const linksByNode = new Map<string, Link[]>();
	const add = (map: Map<string, Link[]>, key: string, link: Link) => {
		const list = map.get(key) ?? [];
		list.push(link);
		map.set(key, list);
	};
	for (const link of topology.links) {
		for (const end of deviceEnds(link)) add(linksByDevice, end.device, link);
		if (!isDeviceEnd(link.b)) add(linksByNode, nodeKey(link.b), link);
	}
	const devicesBySite = new Map<string, Device[]>(topology.sites.map((s) => [s.code, []]));
	const ordered = [...topology.devices].sort(
		(x, y) => ROLES.indexOf(x.role) - ROLES.indexOf(y.role) || compareNatural(x.name, y.name)
	);
	for (const device of ordered) devicesBySite.get(device.site)?.push(device);
	return {
		topology,
		sites: new Map(topology.sites.map((s) => [s.code, s])),
		devices: new Map(topology.devices.map((d) => [d.name, d])),
		links: new Map(topology.links.map((l) => [l.id, l])),
		linksByDevice,
		linksByNode,
		devicesBySite,
		networks: new Map(topology.networks.map((n) => [n.name, n])),
		transports: new Map(topology.transports.map((t) => [t.name, t])),
		externals: new Map(topology.externals.map((e) => [e.name, e])),
		tenants: new Map(topology.tenants.map((t) => [t.name, t])),
		tunnels: new Map(topology.tunnels.map((t) => [t.name, t])),
		fabrics: new Map(topology.fabrics.map((f) => [f.name, f]))
	};
}

/**
 * A device's links, each oriented with the device's own end first.
 *
 * @param index - Topology index.
 * @param device - Device name.
 * @returns Neighbors in natural order of the local interface.
 */
export function neighborsOf(index: TopologyIndex, device: string): Neighbor[] {
	return (index.linksByDevice.get(device) ?? [])
		.map((link) =>
			isDeviceEnd(link.b) && link.b.device === device && link.a.device !== device
				? { link, local: link.b, remote: link.a }
				: { link, local: link.a, remote: link.b }
		)
		.sort((x, y) => compareNatural(x.local.interface, y.local.interface));
}

/**
 * The site a device is at.
 *
 * @param index - Topology index.
 * @param device - Device name.
 * @returns The site code; the backend guarantees every device has one.
 */
export function siteOf(index: TopologyIndex, device: string): string {
	return index.devices.get(device)?.site ?? '';
}

/**
 * The letters the ends of links shown together go by, as carriers and NetBox
 * name them: a circuit has an A side and a Z side, the far side being the
 * other end of the circuit order (or the transport, for a circuit into one);
 * a cable has an A end and a B end.
 *
 * @param links - The links.
 * @returns `A` and `Z` with `side` when every one is a circuit; else `A` and
 *   `B` with `end`.
 */
export function endLetters(links: Link[]): { a: string; b: string; word: string } {
	return links.length > 0 && links.every((l) => l.circuit)
		? { a: 'A', b: 'Z', word: 'side' }
		: { a: 'A', b: 'B', word: 'end' };
}

/**
 * A short name for a link.
 *
 * @param link - The link.
 * @returns A circuit by its ID, any other link by its two devices.
 */
export function linkName(link: Link): string {
	return link.circuit
		? `Circuit ${link.circuit.circuit_id}`
		: `${link.a.device} – ${endName(link.b)}`;
}

// Case does not matter, so names typed into search abbreviate too.
const INTERFACE_ABBREVIATIONS: [RegExp, string][] = [
	[/^HundredGigE/i, 'Hu'],
	[/^FortyGigabitEthernet/i, 'Fo'],
	[/^TwentyFiveGigE/i, 'Twe'],
	[/^TenGigabitEthernet/i, 'Te'],
	[/^GigabitEthernet/i, 'Gi'],
	[/^FastEthernet/i, 'Fa'],
	[/^Port-channel/i, 'Po'],
	[/^Ethernet/i, 'Eth']
];

/**
 * Abbreviate an interface name the way IOS does: `TenGigabitEthernet1/0/1` → `Te1/0/1`.
 *
 * @param name - Full interface name, in any case.
 * @returns The short form, or the name unchanged if it has no known prefix.
 */
export function shortInterface(name: string): string {
	for (const [pattern, short] of INTERFACE_ABBREVIATIONS) {
		if (pattern.test(name)) return name.replace(pattern, short);
	}
	return name;
}

/**
 * Format a speed or capacity.
 *
 * @param mbps - Megabits per second.
 * @returns For example `100M`, `1G`, `2.5G`, `220G`, `1.2T`.
 */
export function formatSpeed(mbps: number): string {
	if (mbps >= 1_000_000) return `${+(mbps / 1_000_000).toFixed(1)}T`;
	if (mbps >= 1_000) return `${+(mbps / 1_000).toFixed(1)}G`;
	return `${mbps}M`;
}
