/**
 * A discovery run compared with the documented topology (`/api/discovery`):
 * each documented link's check, every place the documentation and the
 * network disagree with when it was seen, and what was seen earlier.
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
 * Fetch the comparison in effect at a moment.
 *
 * @param at - The moment (ISO time), or undefined for now.
 * @returns Link checks and findings, as of the latest discovery run then,
 *   with when each finding was seen, and the findings gone by then.
 * @throws Error when the API answers with anything but 200.
 */
export async function fetchDiscovery(at?: string): Promise<Comparison> {
	const url = at ? `/api/discovery?at=${encodeURIComponent(at)}` : '/api/discovery';
	const response = await fetch(url);
	if (!response.ok) throw new Error(`GET ${url} answered ${response.status}`);
	return (await response.json()) as Comparison;
}
