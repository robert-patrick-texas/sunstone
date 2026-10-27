/**
 * Live state from `GET /api/state` (simulated until real sources are
 * connected), the state as of an earlier moment, the changes seen over the
 * last day from `GET /api/events`, and one device's readings over the day
 * from `GET /api/history/{device}`.
 *
 * The types are aliases of `schema.d.ts`, generated from the backend's
 * OpenAPI description.
 */
import type { components } from './schema.d.ts';

type Schemas = components['schemas'];
export type NetworkState = Schemas['NetworkState'];
export type DeviceState = Schemas['DeviceState'];
export type InterfaceState = Schemas['InterfaceState'];
export type EventLog = Schemas['EventLog'];
export type StateEvent = Schemas['StateEvent'];
export type DeviceHistory = Schemas['DeviceHistory'];
export type InterfaceHistory = Schemas['InterfaceHistory'];

async function get<T>(url: string): Promise<T> {
	const response = await fetch(url);
	if (!response.ok) throw new Error(`GET ${url} answered ${response.status}`);
	return (await response.json()) as T;
}

/**
 * Fetch the live state, now or as of an earlier moment.
 *
 * @param at - ISO time within the source's history, or undefined for now.
 * @returns The snapshot.
 * @throws Error when the API answers with anything but 200.
 */
export function fetchState(at?: string): Promise<NetworkState> {
	return get(at ? `/api/state?at=${encodeURIComponent(at)}` : '/api/state');
}

/**
 * Fetch the changes seen over the source's history.
 *
 * @returns The events, oldest first, and the span they cover.
 * @throws Error when the API answers with anything but 200.
 */
export function fetchEvents(): Promise<EventLog> {
	return get('/api/events');
}

/**
 * Fetch one device's readings over the source's history.
 *
 * @param device - Device name.
 * @returns The readings, or null if the source does not monitor the device.
 * @throws Error when the API answers with anything but 200 or 404.
 */
export async function fetchHistory(device: string): Promise<DeviceHistory | null> {
	const url = `/api/history/${encodeURIComponent(device)}`;
	const response = await fetch(url);
	if (response.status === 404) return null;
	if (!response.ok) throw new Error(`GET ${url} answered ${response.status}`);
	return (await response.json()) as DeviceHistory;
}
