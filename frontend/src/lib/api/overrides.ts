/**
 * Overrides (`/api/overrides`): Sunstone's own exceptions to what the
 * topology says, shared by everyone using Sunstone and kept apart from
 * fixes.
 *
 * The types are aliases of `schema.d.ts`, generated from the backend's
 * OpenAPI description.
 */
import { send } from './http.ts';
import type { components } from './schema.d.ts';

type Schemas = components['schemas'];
export type Override = Schemas['Override'];
export type OverrideNow = Schemas['OverrideNow'];
export type OverrideIn = Schemas['OverrideIn'];
export type OverrideLine = Schemas['OverrideLine'];
export type Target = Schemas['Target'];
export type TargetKind = Target['kind'];
export type OverrideKind = Override['kind'];
export type OverrideState = OverrideNow['state'];

/**
 * Fetch every override not withdrawn.
 *
 * @returns The overrides, newest first, each with how it stands now.
 * @throws Error when the API refuses.
 */
export async function fetchOverrides(): Promise<OverrideNow[]> {
	const found = await send<Schemas['OverrideList']>('GET', 'api/overrides');
	return found.overrides;
}

/**
 * Make an override. One of a kind an object has one of at a time (a
 * rename, a lock of the field, a label of the key, hiding, one device on a
 * port) takes the place of the one there.
 *
 * @param made - What it is on, its kind, key and value, a note, who, and when it expires.
 * @returns The override.
 * @throws Error with the API's reason when it refuses: its target is not
 *   there, the topology will not take it, it repeats one there, or it would
 *   have expired already.
 */
export function makeOverride(made: OverrideIn): Promise<Override> {
	return send('POST', 'api/overrides', made);
}

/**
 * Withdraw an override: it stops applying, and is kept for the handover.
 *
 * @param id - The override's id.
 * @param by - Who withdraws it.
 * @throws Error with the API's reason when it refuses (none with that id).
 */
export function withdrawOverride(id: string, by: string): Promise<void> {
	return send('POST', `api/overrides/${encodeURIComponent(id)}/withdraw`, { by });
}

/**
 * Give an override a new expiry, or none: an expired one applies again.
 *
 * @param id - The override's id.
 * @param by - Who renews it.
 * @param expires - When it expires now, as an ISO time, or null for never.
 * @returns The override.
 * @throws Error with the API's reason when it refuses.
 */
export function renewOverride(id: string, by: string, expires: string | null): Promise<Override> {
	return send('POST', `api/overrides/${encodeURIComponent(id)}/renew`, { by, expires });
}
