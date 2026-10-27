/**
 * Who is on call (`/api/oncall`), who owns what (`/api/ownership`), pages
 * (`/api/pages`), and covered shifts (`/api/covers`). Pages are recorded
 * and escalated on the server; nothing is sent to anyone.
 *
 * The types are aliases of `schema.d.ts`, generated from the backend's
 * OpenAPI description.
 */
import { send } from './http.ts';
import type { components } from './schema.d.ts';

type Schemas = components['schemas'];
export type OnCall = Schemas['OnCall'];
export type TeamNow = Schemas['TeamNow'];
export type Shift = Schemas['Shift'];
export type Person = Schemas['Person'];
export type Carrier = Schemas['Carrier'];
export type Cover = Schemas['Cover'];
export type CoverIn = Schemas['CoverIn'];
export type Page = Schemas['Page'];
export type Paging = Schemas['Paging'];
export type Notice = Schemas['Notice'];
export type Ownership = Schemas['Ownership'];
export type Duty = Notice['to'];

/** The API's answer when there is no on-call directory. */
export class NoDirectory extends Error {}

async function get<T>(url: string): Promise<T> {
	const response = await fetch(url);
	if (response.status === 404) {
		const body = (await response.json()) as { detail?: string };
		throw new NoDirectory(body.detail ?? 'No on-call directory');
	}
	if (!response.ok) throw new Error(`GET ${url} answered ${response.status}`);
	return (await response.json()) as T;
}

/**
 * Fetch who is on call for every team.
 *
 * @param at - The moment (ISO time), or undefined for now.
 * @returns Teams with their shifts, people, carriers, and covers.
 * @throws NoDirectory when the server has no on-call directory.
 * @throws Error when the API answers with anything else but 200.
 */
export function fetchOnCall(at?: string): Promise<OnCall> {
	return get(at ? `/api/oncall?at=${encodeURIComponent(at)}` : '/api/oncall');
}

/**
 * Fetch which team owns each site, device, and link.
 *
 * @returns Team ids by site code, device name, and link id.
 * @throws NoDirectory when the server has no on-call directory.
 * @throws Error when the API answers with anything else but 200.
 */
export function fetchOwnership(): Promise<Ownership> {
	return get('/api/ownership');
}

/**
 * Page the team that owns a problem. Nothing is sent.
 *
 * @param problem - The problem's id.
 * @param by - Who is paging.
 * @param link - Where in Sunstone to look, sent with the page.
 * @returns The page as recorded.
 * @throws Error with the API's reason when it refuses.
 */
export function sendPage(problem: string, by: string, link: string): Promise<Page> {
	return send('POST', '/api/pages', { problem, by, link });
}

/**
 * Withdraw a problem's page.
 *
 * @param problem - The problem's id.
 * @throws Error when the API refuses.
 */
export function withdrawPage(problem: string): Promise<void> {
	return send('DELETE', `/api/pages?problem=${encodeURIComponent(problem)}`);
}

/**
 * Put someone on call in place of a team's primary.
 *
 * @param cover - Who, for which team, when, and who says so.
 * @returns The saved cover.
 * @throws Error with the API's reason when it refuses.
 */
export function saveCover(cover: CoverIn): Promise<Cover> {
	return send('POST', '/api/covers', cover);
}

/**
 * Delete a cover.
 *
 * @param id - The cover.
 * @throws Error when the API refuses.
 */
export function deleteCover(id: string): Promise<void> {
	return send('DELETE', `/api/covers/${encodeURIComponent(id)}`);
}
