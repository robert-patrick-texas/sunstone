/**
 * Fixes accepted into the documentation (`/api/changes`), and what
 * accepting one would do (`/api/review`), shared by everyone using Sunstone.
 *
 * The types are aliases of `schema.d.ts`, generated from the backend's
 * OpenAPI description.
 */
import { send } from './http.ts';
import type { components } from './schema.d.ts';

type Schemas = components['schemas'];
export type Change = Schemas['Change'];
export type Fix = Schemas['Fix'];
export type Review = Schemas['Review'];
export type PortNow = Schemas['PortNow'];

/**
 * Fetch every change accepted into the documentation.
 *
 * @returns The changes, newest first.
 * @throws Error when the API refuses.
 */
export async function fetchChanges(): Promise<Change[]> {
	const found = await send<Schemas['ChangeSet']>('GET', '/api/changes');
	return found.changes;
}

/**
 * Work out what accepting a finding's fix would do now, or what Live reads
 * on the ports it is about, to mark it expected.
 *
 * @param finding - The finding's id, from the latest discovery run.
 * @param expect - Review marking it expected rather than fixing it.
 * @returns What it would do to the ports involved, redundancy, and problems.
 * @throws Error with the API's reason when it refuses (no such finding now, or no fix).
 */
export function fetchReview(finding: string, expect = false): Promise<Review> {
	const query = `finding=${encodeURIComponent(finding)}${expect ? '&expect=true' : ''}`;
	return send('GET', `/api/review?${query}`);
}

/**
 * Accept a finding's fix into the documentation, or mark the finding expected.
 *
 * @param finding - The finding's id, from the latest discovery run.
 * @param note - Why, or how it was checked; may be empty, except to mark it expected.
 * @param by - Who accepts it.
 * @param expect - Mark it expected rather than fix it.
 * @returns The change.
 * @throws Error with the API's reason when it refuses.
 */
export function acceptFix(
	finding: string,
	note: string,
	by: string,
	expect = false
): Promise<Change> {
	return send('POST', '/api/changes', { finding, note, by, expect });
}

/**
 * Take a change back out of the documentation, or withdraw an expectation.
 *
 * @param id - The change's id.
 * @throws Error with the API's reason when it refuses (a later change depends on it).
 */
export function revertChange(id: string): Promise<void> {
	return send('DELETE', `/api/changes/${encodeURIComponent(id)}`);
}
