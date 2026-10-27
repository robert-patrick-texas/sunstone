/**
 * Problems and "what if" answers, worked out on the server: the problems in
 * one moment's live state from `GET /api/problems`, shared by every viewer,
 * and what failing some devices, sites, or links would do from
 * `POST /api/impact`.
 *
 * The API sends impacts as lists; the views want sets to look things up in,
 * so they are converted on arrival.
 */
import type { Impact } from '../impact.ts';
import type { Selection } from '../state.svelte.ts';
import type { components } from './schema.d.ts';

type Schemas = components['schemas'];
type ApiImpact = Schemas['Impact'];
export type ProblemKind = Schemas['RoutedProblem']['kind'];
/** A problem, with the team that owns it and where its page stands. */
export type Problem = Omit<Schemas['RoutedProblem'], 'impact'> & { impact: Impact | null };

export interface WhatIf {
	impact: Impact;
	/** Everything named was already down or cut off, so failing it changes nothing. */
	already: boolean;
}

function toImpact(api: ApiImpact): Impact {
	return {
		failed: { devices: new Set(api.failed.devices), links: new Set(api.failed.links) },
		cutOff: new Set(api.cut_off),
		exposed: new Map(Object.entries(api.exposed))
	};
}

/**
 * Fetch the problems in the live state as of a moment.
 *
 * @param at - The `generated_at` of the state being shown, so the two match.
 * @returns The problems, most urgent first.
 * @throws Error when the API answers with anything but 200.
 */
export async function fetchProblems(at: string): Promise<Problem[]> {
	const url = `/api/problems?at=${encodeURIComponent(at)}`;
	const response = await fetch(url);
	if (!response.ok) throw new Error(`GET ${url} answered ${response.status}`);
	const list = (await response.json()) as Schemas['RoutedProblemList'];
	return list.problems.map((p) => ({ ...p, impact: p.impact ? toImpact(p.impact) : null }));
}

/**
 * Ask what failing some items would do.
 *
 * @param failures - Devices, sites (all their devices), and links.
 * @param at - The `generated_at` of the live state to start from, or null
 *   for the healthy network.
 * @returns The impact, and whether everything named was down or cut off already.
 * @throws Error when the API answers with anything but 200.
 */
export async function fetchWhatIf(failures: Selection[], at: string | null): Promise<WhatIf> {
	const response = await fetch('/api/impact', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ failures, at })
	});
	if (!response.ok) throw new Error(`POST /api/impact answered ${response.status}`);
	const answer = (await response.json()) as Schemas['WhatIf'];
	return { impact: toImpact(answer.impact), already: answer.already };
}
