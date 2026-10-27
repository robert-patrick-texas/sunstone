/**
 * Saved layouts of the topology view (`/api/layouts`).
 *
 * The types are aliases of `schema.d.ts`, generated from the backend's
 * OpenAPI description.
 */
import type { components } from './schema.d.ts';

type Schemas = components['schemas'];
export type LayoutIn = Schemas['LayoutIn'];
export type SavedLayout = Schemas['SavedLayout'];
export type LayoutSummary = Schemas['LayoutSummary'];

const url = (name: string) => `/api/layouts/${encodeURIComponent(name)}`;

/** Await a response; a failure becomes an Error saying what failed and why. */
async function call<T>(request: Promise<Response>, what: string): Promise<T> {
	const response = await request;
	if (!response.ok) {
		const body: unknown = await response.json().catch(() => null);
		const detail =
			body && typeof body === 'object' && 'detail' in body && typeof body.detail === 'string'
				? `: ${body.detail}`
				: '';
		throw new Error(`${what} failed (${response.status})${detail}`);
	}
	return (response.status === 204 ? undefined : await response.json()) as T;
}

/**
 * List saved layouts, most recently saved first.
 *
 * @returns Summaries without positions.
 * @throws Error when the request fails.
 */
export function listLayouts(): Promise<LayoutSummary[]> {
	return call(fetch('/api/layouts'), 'Listing saved layouts');
}

/**
 * Fetch one saved layout.
 *
 * @param name - Its name.
 * @returns The layout.
 * @throws Error when there is none by that name or the request fails.
 */
export function getLayout(name: string): Promise<SavedLayout> {
	return call(fetch(url(name)), `Opening "${name}"`);
}

/**
 * Save a layout, replacing any with the same name.
 *
 * @param name - Its name.
 * @param layout - Settings and positions.
 * @returns The stored layout.
 * @throws Error when the request fails.
 */
export function saveLayout(name: string, layout: LayoutIn): Promise<SavedLayout> {
	const init = {
		method: 'PUT',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify(layout)
	};
	return call(fetch(url(name), init), `Saving "${name}"`);
}

/**
 * Delete a saved layout.
 *
 * @param name - Its name.
 * @throws Error when there is none by that name or the request fails.
 */
export function deleteLayout(name: string): Promise<void> {
	return call(fetch(url(name), { method: 'DELETE' }), `Deleting "${name}"`);
}
