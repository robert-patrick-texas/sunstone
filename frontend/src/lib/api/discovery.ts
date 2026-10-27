/**
 * The latest discovery run compared with the documented topology
 * (`/api/discovery`): each documented link's check, and every place the
 * documentation and the network disagree.
 *
 * The types are aliases of `schema.d.ts`, generated from the backend's
 * OpenAPI description.
 */
import type { components } from './schema.d.ts';

type Schemas = components['schemas'];
export type Comparison = Schemas['Comparison'];
export type Finding = Schemas['Finding'];
export type SeenLink = Schemas['SeenLink'];
export type FindingKind = Finding['kind'];
export type LinkCheck = NonNullable<Comparison['links'][string]>;

/**
 * Fetch the latest comparison.
 *
 * @returns Link checks and findings, as of the latest discovery run.
 * @throws Error when the API answers with anything but 200.
 */
export async function fetchDiscovery(): Promise<Comparison> {
	const response = await fetch('/api/discovery');
	if (!response.ok) throw new Error(`GET /api/discovery answered ${response.status}`);
	return (await response.json()) as Comparison;
}
