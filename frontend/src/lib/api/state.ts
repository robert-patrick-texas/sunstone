/**
 * Live state from `GET /api/state` (simulated until real sources are connected).
 *
 * The types are aliases of `schema.d.ts`, generated from the backend's
 * OpenAPI description.
 */
import type { components } from './schema.d.ts';

type Schemas = components['schemas'];
export type NetworkState = Schemas['NetworkState'];
export type DeviceState = Schemas['DeviceState'];
export type InterfaceState = Schemas['InterfaceState'];

/**
 * Fetch the current live state.
 *
 * @returns The snapshot.
 * @throws Error when the API answers with anything but 200.
 */
export async function fetchState(): Promise<NetworkState> {
	const response = await fetch('/api/state');
	if (!response.ok) throw new Error(`GET /api/state answered ${response.status}`);
	return (await response.json()) as NetworkState;
}
