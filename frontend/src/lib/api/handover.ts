/**
 * What the incoming shift needs to know (`/api/handover`): what is wrong
 * now and who is on it, outages, pages and acknowledgements, maintenance,
 * fixes, discovery findings, and who is on call, over the last hours.
 *
 * The types are aliases of `schema.d.ts`, generated from the backend's
 * OpenAPI description.
 */
import { send } from './http.ts';
import type { components } from './schema.d.ts';

type Schemas = components['schemas'];
export type Handover = Schemas['Handover'];
export type Outage = Schemas['Outage'];

/**
 * Fetch the handover for a span ending now.
 *
 * @param hours - How far back it goes.
 * @returns The handover.
 * @throws Error when the API refuses.
 */
export function fetchHandover(hours: number): Promise<Handover> {
	return send('GET', `/api/handover?hours=${hours}`);
}
