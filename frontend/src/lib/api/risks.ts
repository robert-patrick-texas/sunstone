/**
 * Shared risk, from `GET /api/risks`: for each named network with tunnels,
 * the devices, links, and providers beneath it whose failure alone would take
 * two or more of its tunnels, worked out on the server for the network as
 * documented, or on top of what is down at a moment.
 */
import type { components } from './schema.d.ts';

type Schemas = components['schemas'];
export type RiskReport = Schemas['RiskReport'];
export type NetworkRisks = Schemas['NetworkRisks'];
export type Risk = Schemas['Risk'];
export type RiskItem = Schemas['RiskItem'];

/**
 * Fetch every network's shared risks.
 *
 * @param at - The `generated_at` of the live state shown, for the risks on top
 *   of what is down then; none for the network as documented.
 * @returns Each named network with tunnels, bottom up, with its risks worst first.
 * @throws Error when the API answers with anything but 200.
 */
export async function fetchRisks(at?: string): Promise<RiskReport> {
	const url = at ? `api/risks?at=${encodeURIComponent(at)}` : 'api/risks';
	const response = await fetch(url);
	if (!response.ok) throw new Error(`GET ${url} answered ${response.status}`);
	return (await response.json()) as RiskReport;
}
