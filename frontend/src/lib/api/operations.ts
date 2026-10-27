/**
 * Maintenance windows (`/api/maintenance`) and acknowledged problems
 * (`/api/acks`), shared by everyone using Sunstone.
 *
 * The types are aliases of `schema.d.ts`, generated from the backend's
 * OpenAPI description.
 */
import { send } from './http.ts';
import type { components } from './schema.d.ts';

type Schemas = components['schemas'];
export type Window = Schemas['Window'];
export type WindowIn = Schemas['WindowIn'];
export type Ack = Schemas['Ack'];

/**
 * Fetch every maintenance window.
 *
 * @returns The windows, earliest first.
 * @throws Error when the API refuses.
 */
export function fetchWindows(): Promise<Window[]> {
	return send('GET', '/api/maintenance');
}

/**
 * Plan a maintenance window, or change one.
 *
 * @param window - What to save.
 * @param id - The window to change, or undefined for a new one.
 * @returns The saved window.
 * @throws Error with the API's reason when it refuses.
 */
export function saveWindow(window: WindowIn, id?: string): Promise<Window> {
	return id
		? send('PUT', `/api/maintenance/${encodeURIComponent(id)}`, window)
		: send('POST', '/api/maintenance', window);
}

/**
 * Delete a maintenance window.
 *
 * @param id - The window.
 * @throws Error when the API refuses.
 */
export function deleteWindow(id: string): Promise<void> {
	return send('DELETE', `/api/maintenance/${encodeURIComponent(id)}`);
}

/**
 * Acknowledge a problem.
 *
 * @param problem - The problem's id.
 * @param note - What is being done.
 * @param by - Who.
 * @returns The acknowledgement.
 * @throws Error with the API's reason when it refuses.
 */
export function acknowledge(problem: string, note: string, by: string): Promise<Ack> {
	return send('POST', '/api/acks', { problem, note, by });
}

/**
 * Withdraw a problem's acknowledgement.
 *
 * @param problem - The problem's id.
 * @throws Error when the API refuses.
 */
export function unacknowledge(problem: string): Promise<void> {
	return send('DELETE', `/api/acks?problem=${encodeURIComponent(problem)}`);
}
