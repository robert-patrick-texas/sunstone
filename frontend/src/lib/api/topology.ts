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
export type Role = Device['role'];

/**
 * Fetch the whole topology.
 *
 * @returns The topology.
 * @throws Error when the API answers with anything but 200.
 */
export async function fetchTopology(): Promise<Topology> {
	const response = await fetch('/api/topology');
	if (!response.ok) throw new Error(`GET /api/topology answered ${response.status}`);
	return (await response.json()) as Topology;
}
