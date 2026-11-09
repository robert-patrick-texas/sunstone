/**
 * Whether the whole network and each named network, and their regions,
 * sites, and locations, are operational, degraded, or offline, from
 * `GET /api/status`, worked out on the server for every viewer.
 */
import type { components } from './schema.d.ts';

type Schemas = components['schemas'];
export type StatusReport = Schemas['StatusReport'];
export type NetworkStatus = Schemas['NetworkStatus'];
export type GroupStatus = Schemas['GroupStatus'];
export type Status = NetworkStatus['status'];
export type ResourceStatus = Schemas['ResourceStatus'];
export type MemberStatus = Schemas['MemberStatus'];

/**
 * Fetch every network's status as of a moment.
 *
 * @param at - The `generated_at` of the state being shown, so the two match.
 * @returns The whole network's status, and each named network's.
 * @throws Error when the API answers with anything but 200.
 */
export async function fetchStatus(at: string): Promise<StatusReport> {
	const url = `api/status?at=${encodeURIComponent(at)}`;
	const response = await fetch(url);
	if (!response.ok) throw new Error(`GET ${url} answered ${response.status}`);
	return (await response.json()) as StatusReport;
}
