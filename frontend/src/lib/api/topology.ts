/**
 * Topology types and loader for `GET /api/topology`.
 *
 * The types are aliases of `schema.d.ts`, which `npm run gen:api` generates
 * from the backend's OpenAPI description, so they follow the Python model.
 */
import type { components } from './schema.d.ts';

type Schemas = components['schemas'];
export type Topology = Schemas['Topology'];
export type Site = Schemas['Site'];
export type Device = Schemas['Device'];
export type Link = Schemas['Link'];
export type Endpoint = Schemas['Endpoint'];
export type FarEnd = Link['b'];
export type Role = Device['role'];
export type NamedNetwork = Schemas['NamedNetwork'];
export type Transport = Schemas['Transport'];
export type External = Schemas['External'];
export type Tenant = Schemas['Tenant'];
export type Tunnel = Schemas['Tunnel'];
export type Fabric = Schemas['Fabric'];
export type FabricMember = Schemas['FabricMember'];
export type Lag = Schemas['Lag'];
export type Resource = Schemas['Resource'];
export type Priority = NonNullable<Link['priority']>;
/** Sunstone's words an organization can give its own for, as `terms` keys. */
export type Term =
	'network' | 'transport' | 'external' | 'application' | 'partner' | 'tenant' | 'tunnel' | 'fabric';

/**
 * Fetch the whole topology.
 *
 * @returns The topology.
 * @throws Error when the API answers with anything but 200.
 */
export async function fetchTopology(): Promise<Topology> {
	const response = await fetch('api/topology');
	if (!response.ok) throw new Error(`GET /api/topology answered ${response.status}`);
	return (await response.json()) as Topology;
}
