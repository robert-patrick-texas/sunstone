/**
 * What carries each connection, what it is for at the edge of the
 * enterprise, and the IDs operations staff quote, as the UI shows them.
 *
 * Roles follow the server's rules (`link_roles` in `model.py`): as
 * documented, else implied by the far end where it leaves no doubt, else
 * TBD, since only routing policy at the site can say what a circuit into a
 * transport is for.
 */
import type { Fabric, Link, Topology, Tunnel } from './api/topology.ts';

export type Edge = Link['edges'][number];
export type Medium = NonNullable<Link['medium']>;
export type Neighbors = NonNullable<Link['neighbors']>;
/** An ID as each side of a connection knows it. */
export type Sides = NonNullable<Link['enterprise_cid']>;

/** Each role, in the order the server lists them, with what it does to the boundary. */
export const EDGES: { edge: Edge; label: string; boundary: string }[] = [
	{
		edge: 'access',
		label: 'Access',
		boundary: 'Lets one endpoint in: the port is the boundary, and nothing behind it may pass'
	},
	{
		edge: 'transit',
		label: 'Transit',
		boundary:
			'Does not cross the boundary: both ends are ours, and what crosses a provider between them is protected'
	},
	{
		edge: 'interconnect',
		label: 'Interconnect',
		boundary: 'Crosses it both ways with one known network, as agreed'
	},
	{
		edge: 'ingress',
		label: 'Ingress',
		boundary: 'Crosses it inward, to the services we publish only'
	},
	{
		edge: 'egress',
		label: 'Egress',
		boundary: 'Crosses it outward; inbound only as replies'
	},
	{
		edge: 'peering',
		label: 'Peering',
		boundary: 'Crosses it both ways with a known community, routes exchanged'
	},
	{
		edge: 'open',
		label: 'Open',
		boundary: 'Crosses it both ways with the world: our routes out, a default or more in'
	}
];

const EDGE = new Map(EDGES.map((e) => [e.edge, e]));

/**
 * A role's name.
 *
 * @param edge - The role.
 * @returns For example "Egress".
 */
export function edgeLabel(edge: Edge): string {
	return EDGE.get(edge)?.label ?? edge;
}

/**
 * What a role does to the security boundary.
 *
 * @param edge - The role.
 * @returns A sentence.
 */
export function edgeBoundary(edge: Edge): string {
	return EDGE.get(edge)?.boundary ?? '';
}

/** What each kind of transport is called. */
export const TRANSPORT_KIND: Record<Topology['transports'][number]['kind'], string> = {
	internet: 'Internet',
	'private-wan': 'Private WAN',
	research: 'Research network'
};

export const MEDIUM_LABEL: Record<Medium, string> = {
	fiber: 'Fiber',
	copper: 'Copper',
	twinax: 'Twinax',
	radio: 'Radio',
	microwave: 'Microwave',
	cellular: 'Cellular',
	satellite: 'Satellite'
};

export const SHOWS_LABEL: Record<Neighbors, string> = {
	'far-end': 'The far end',
	provider: "The provider's equipment",
	nothing: 'Nothing'
};

/** A connection's roles, and where they come from. */
export interface Roles {
	edges: Edge[];
	/** `implied` with no roles: an internal link between two of our devices. */
	source: 'declared' | 'implied' | 'tbd';
}

const BY_KIND: Record<Topology['externals'][number]['kind'], Edge> = {
	tenant: 'access',
	partner: 'interconnect',
	application: 'egress'
};

/**
 * A link's roles at the edge: as documented, or implied by its far end.
 *
 * @param topology - The topology, for what kind each external node is.
 * @param link - The link.
 * @returns Transit across a provider between two of our devices, none for
 *   our own cable between them; by its kind for an external node's; TBD into
 *   a transport.
 */
export function linkRoles(topology: Topology, link: Link): Roles {
	if (link.edges.length) return { edges: link.edges, source: 'declared' };
	const b = link.b;
	if ('device' in b) return { edges: link.circuit ? ['transit'] : [], source: 'implied' };
	if ('external' in b) {
		const kind = topology.externals.find((e) => e.name === b.external)?.kind;
		if (kind) return { edges: [BY_KIND[kind]], source: 'implied' };
	}
	return { edges: [], source: 'tbd' };
}

/**
 * A tunnel's roles at the edge.
 *
 * @param topology - The topology.
 * @param tunnel - The tunnel.
 * @returns As documented; else transit between two of our devices, or by
 *   the far end's kind.
 */
export function tunnelRoles(topology: Topology, tunnel: Tunnel): Roles {
	if (tunnel.edges.length) return { edges: tunnel.edges, source: 'declared' };
	const b = tunnel.b;
	if ('device' in b) return { edges: ['transit'], source: 'implied' };
	const kind = topology.externals.find((e) => e.name === b.external)?.kind;
	return kind ? { edges: [BY_KIND[kind]], source: 'implied' } : { edges: [], source: 'tbd' };
}

/**
 * A fabric's roles at the edge.
 *
 * @param fabric - The fabric.
 * @returns As documented, else transit: its members are all ours.
 */
export function fabricRoles(fabric: Fabric): Roles {
	return fabric.edges.length
		? { edges: fabric.edges, source: 'declared' }
		: { edges: ['transit'], source: 'implied' };
}

/**
 * Roles in a few words.
 *
 * @param roles - The roles.
 * @returns For example "Transit, Egress", "Transit (implied)", "Internal",
 *   or "TBD".
 */
export function rolesText(roles: Roles): string {
	if (roles.source === 'tbd') return 'TBD';
	if (roles.edges.length === 0) return 'Internal';
	const names = roles.edges.map(edgeLabel).join(', ');
	return roles.source === 'implied' ? `${names} (implied)` : names;
}

/**
 * Who provides the path between a link's ends.
 *
 * @param link - The link.
 * @returns For example "Carrier circuit · Mesa Carrier", "Cross-connect ·
 *   Granite Colo", or "Our own cable".
 */
export function pathText(link: Link): string {
	const c = link.circuit;
	if (!c) return 'Our own cable';
	return `${c.type === 'cross-connect' ? 'Cross-connect' : 'Carrier circuit'} · ${c.provider}`;
}

/**
 * An ID's sides in a line.
 *
 * @param sides - The ID.
 * @returns The value once when both sides have it; else each side's, or
 *   the A side's alone when the Z side has none (as into a shared transport).
 */
export function sidesText(sides: Sides): string {
	if (sides.z === sides.a) return sides.a;
	return sides.z ? `${sides.a} (A) · ${sides.z} (Z)` : `${sides.a} (A)`;
}

/**
 * The ID a connection is named by: the enterprise's CID, else the carrier's.
 *
 * @param link - The link.
 * @returns Its A side's, or null if it has neither.
 */
export function cidOf(link: Link): string | null {
	return link.enterprise_cid?.a ?? link.circuit?.circuit_id.a ?? null;
}

/**
 * Whether a link joins its far end to the rest of the network, for paths
 * (the server's `joins`).
 *
 * @param link - The link.
 * @returns False for a circuit into a transport whose documented roles
 *   leave out transit: routing policy keeps our own traffic off it.
 */
export function joins(link: Link): boolean {
	return !('transport' in link.b && link.edges.length > 0 && !link.edges.includes('transit'));
}

/**
 * What LLDP and CDP should show on a link's port at our end.
 *
 * @param link - The link.
 * @returns As documented; else the far end between two of our devices;
 *   else null, not said.
 */
export function showsOf(link: Link): Neighbors | null {
	if (link.neighbors) return link.neighbors;
	return 'device' in link.b ? 'far-end' : null;
}

/**
 * Every value an ID holds, for search: each side's, and each part of a
 * carrier's free-form CID ("ME-1 / LEC 12/KXFU/204411" holds both).
 *
 * @param sides - The ID, if any.
 * @returns The values, without repeats.
 */
export function idWords(sides: Sides | null | undefined): string[] {
	if (!sides) return [];
	const whole = [sides.a, sides.z ?? ''].filter(Boolean);
	const parts = whole.flatMap((s) => s.split(/\s*[;,]\s*|\s+\/\s+/));
	return [...new Set([...whole, ...parts].filter(Boolean))];
}
