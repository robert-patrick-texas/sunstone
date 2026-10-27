/**
 * Lookups over a loaded topology, and the formatting every view shares.
 */
import type { Device, Endpoint, Link, Role, Site, Topology } from './api/topology.ts';

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
	/** Devices of each site, top tier first, then in natural name order. */
	devicesBySite: Map<string, Device[]>;
}

/** One link seen from one of its devices. */
export interface Neighbor {
	link: Link;
	local: Endpoint;
	remote: Endpoint;
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
	for (const link of topology.links) {
		for (const end of [link.a, link.b]) {
			const list = linksByDevice.get(end.device) ?? [];
			list.push(link);
			linksByDevice.set(end.device, list);
		}
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
		devicesBySite
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
			link.a.device === device
				? { link, local: link.a, remote: link.b }
				: { link, local: link.b, remote: link.a }
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

const INTERFACE_ABBREVIATIONS: [RegExp, string][] = [
	[/^HundredGigE/, 'Hu'],
	[/^FortyGigabitEthernet/, 'Fo'],
	[/^TwentyFiveGigE/, 'Twe'],
	[/^TenGigabitEthernet/, 'Te'],
	[/^GigabitEthernet/, 'Gi'],
	[/^FastEthernet/, 'Fa'],
	[/^Port-channel/, 'Po'],
	[/^Ethernet/, 'Eth']
];

/**
 * Abbreviate an interface name the way IOS does: `TenGigabitEthernet1/0/1` → `Te1/0/1`.
 *
 * @param name - Full interface name.
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
