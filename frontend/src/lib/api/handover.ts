/**
 * What the incoming shift needs to know (`/api/handover`): what is wrong
 * now and who is on it, outages, pages and acknowledgements, maintenance,
 * fixes, discovery findings, who is on call, and the outgoing shift's notes,
 * over the last hours. And the handovers saved at each shift change
 * (`/api/handovers`), and notes for the next one (`/api/shift-notes`).
 *
 * The types are aliases of `schema.d.ts`, generated from the backend's
 * OpenAPI description.
 */
import { send } from './http.ts';
import type { components } from './schema.d.ts';

type Schemas = components['schemas'];
export type Handover = Schemas['Handover'];
export type HandoverList = Schemas['HandoverList'];
export type HandoverSummary = Schemas['HandoverSummary'];
export type Outage = Schemas['Outage'];
export type ShiftNote = Schemas['ShiftNote'];

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

/**
 * Fetch the handovers saved at shift changes.
 *
 * @returns Them, latest first, and when the shift changes next.
 * @throws Error when the API refuses.
 */
export function fetchHandovers(): Promise<HandoverList> {
	return send('GET', '/api/handovers');
}

/**
 * Fetch a handover saved at a shift change, as it was then.
 *
 * @param id - Its id, such as `20261027T1200Z`.
 * @returns The handover.
 * @throws Error when there is no such handover.
 */
export function fetchSavedHandover(id: string): Promise<Handover> {
	return send('GET', `/api/handovers/${encodeURIComponent(id)}`);
}

/**
 * Write a note for the next shift; it goes with the next handover.
 *
 * @param text - The note.
 * @param by - Who writes it.
 * @returns The note.
 * @throws Error with the API's reason when it refuses.
 */
export function addShiftNote(text: string, by: string): Promise<ShiftNote> {
	return send('POST', '/api/shift-notes', { text, by });
}

/**
 * Withdraw a note that has not been handed over yet.
 *
 * @param id - The note's id.
 * @throws Error with the API's reason when it refuses (handed over already).
 */
export function withdrawShiftNote(id: string): Promise<void> {
	return send('DELETE', `/api/shift-notes/${encodeURIComponent(id)}`);
}
