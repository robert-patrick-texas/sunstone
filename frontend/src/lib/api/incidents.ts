/**
 * Incidents (`/api/incidents`): problems someone treats as one, each with a
 * timeline worked out from what Sunstone records, people's notes, and once
 * it clears, a postmortem.
 *
 * The types are aliases of `schema.d.ts`, generated from the backend's
 * OpenAPI description.
 */
import { send } from './http.ts';
import type { components } from './schema.d.ts';

type Schemas = components['schemas'];
export type IncidentReport = Schemas['IncidentReport'];
export type IncidentSummary = Schemas['IncidentSummary'];
export type IncidentList = Schemas['IncidentList'];
export type IncidentNote = Schemas['IncidentNote'];
export type Entry = Schemas['Entry'];
export type Member = Schemas['Member'];

/**
 * Fetch every incident, in a line each.
 *
 * @returns Them, newest first.
 * @throws Error when the API refuses.
 */
export function fetchIncidents(): Promise<IncidentList> {
	return send('GET', '/api/incidents');
}

/**
 * Fetch an incident with its timeline and postmortem.
 *
 * @param number - The incident's number.
 * @returns The incident.
 * @throws Error when there is no such incident.
 */
export function fetchIncident(number: number): Promise<IncidentReport> {
	return send('GET', `/api/incidents/${number}`);
}

/**
 * Open an incident from a problem there is now.
 *
 * @param problem - The problem's id.
 * @param title - What to call the incident.
 * @param by - Who opens it.
 * @param note - A first note, or nothing.
 * @returns The incident.
 * @throws Error with the API's reason when it refuses (the problem is gone,
 *   or in an incident already).
 */
export function openIncident(
	problem: string,
	title: string,
	by: string,
	note = ''
): Promise<IncidentReport> {
	return send('POST', '/api/incidents', { problem, title, by, note });
}

/**
 * Add a problem there is now to an incident not yet closed.
 *
 * @param number - The incident.
 * @param problem - The problem's id.
 * @param by - Who adds it.
 * @returns The incident.
 * @throws Error with the API's reason when it refuses.
 */
export function joinIncident(number: number, problem: string, by: string): Promise<IncidentReport> {
	return send('POST', `/api/incidents/${number}/problems`, { problem, by });
}

/**
 * Write a note on an incident not yet closed.
 *
 * @param number - The incident.
 * @param text - The note.
 * @param by - Who writes it.
 * @returns The note.
 * @throws Error with the API's reason when it refuses (closed).
 */
export function noteIncident(number: number, text: string, by: string): Promise<IncidentNote> {
	return send('POST', `/api/incidents/${number}/notes`, { text, by });
}

/**
 * Close an incident with its postmortem summary.
 *
 * @param number - The incident.
 * @param summary - What happened, and what is to be done about it.
 * @param by - Who writes it.
 * @returns The incident, closed.
 * @throws Error with the API's reason when it refuses (closed already).
 */
export function closeIncident(
	number: number,
	summary: string,
	by: string
): Promise<IncidentReport> {
	return send('POST', `/api/incidents/${number}/close`, { summary, by });
}
