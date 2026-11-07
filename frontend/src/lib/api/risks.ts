/**
 * Shared risk, from `GET /api/risks`: for each named network with tunnels,
 * the devices, links, and providers beneath it whose failure alone would take
 * two or more of its tunnels, worked out once on the server for the network
 * as documented.
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
 * @returns Each named network with tunnels, bottom up, with its risks worst first.
 * @throws Error when the API answers with anything but 200.
 */
export async function fetchRisks(): Promise<RiskReport> {
	const response = await fetch('/api/risks');
	if (!response.ok) throw new Error(`GET /api/risks answered ${response.status}`);
	return (await response.json()) as RiskReport;
}
