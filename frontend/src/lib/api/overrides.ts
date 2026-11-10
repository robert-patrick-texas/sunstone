/**
 * Overrides (`/api/overrides`): Sunstone's own exceptions to what the
 * topology says, shared by everyone using Sunstone and kept apart from
 * fixes.
 *
 * The types are aliases of `schema.d.ts`, generated from the backend's
 * OpenAPI description.
 */
import { send } from './http.ts';
import type { components } from './schema.d.ts';

type Schemas = components['schemas'];
export type Override = Schemas['Override'];
export type OverrideNow = Schemas['OverrideNow'];
export type OverrideIn = Schemas['OverrideIn'];
export type OverrideLine = Schemas['OverrideLine'];
export type Target = Schemas['Target'];
export type TargetKind = Target['kind'];
export type OverrideKind = Override['kind'];
export type OverrideState = OverrideNow['state'];
export type OverrideList = Schemas['OverrideList'];
export type Rule = Schemas['Rule'];
export type RuleNow = Schemas['RuleNow'];
export type RuleIn = Schemas['RuleIn'];
export type RuleKind = Rule['kind'];
export type RuleLine = Schemas['RuleLine'];
export type RuleMatch = Schemas['RuleMatch'];
export type RulePreview = Schemas['RulePreview'];
export type Match = Schemas['Match'];
export type Excepted = Schemas['Excepted'];

/**
 * Fetch every override and rule not withdrawn.
 *
 * @returns The overrides and the rules, each newest first, with how each stands now.
 * @throws Error when the API refuses.
 */
export async function fetchOverrides(): Promise<{ overrides: OverrideNow[]; rules: RuleNow[] }> {
	const found = await send<OverrideList>('GET', 'api/overrides');
	return { overrides: found.overrides, rules: found.rules ?? [] };
}

/**
 * Make an override. One of a kind an object has one of at a time (a
 * rename, a lock of the field, a label of the key, hiding, one device on a
 * port) takes the place of the one there.
 *
 * @param made - What it is on, its kind, key and value, a note, who, and when it expires.
 * @returns The override.
 * @throws Error with the API's reason when it refuses: its target is not
 *   there, the topology will not take it, it repeats one there, or it would
 *   have expired already.
 */
export function makeOverride(made: OverrideIn): Promise<Override> {
	return send('POST', 'api/overrides', made);
}

/**
 * Withdraw an override: it stops applying, and is kept for the handover.
 *
 * @param id - The override's id.
 * @param by - Who withdraws it.
 * @throws Error with the API's reason when it refuses (none with that id).
 */
export function withdrawOverride(id: string, by: string): Promise<void> {
	return send('POST', `api/overrides/${encodeURIComponent(id)}/withdraw`, { by });
}

/**
 * Give an override a new expiry, or none: an expired one applies again.
 *
 * @param id - The override's id.
 * @param by - Who renews it.
 * @param expires - When it expires now, as an ISO time, or null for never.
 * @returns The override.
 * @throws Error with the API's reason when it refuses.
 */
export function renewOverride(id: string, by: string, expires: string | null): Promise<Override> {
	return send('POST', `api/overrides/${encodeURIComponent(id)}/renew`, { by, expires });
}

/**
 * What a rule would do, made now: what it would apply on, what wins over it
 * there, and for a rule on ports, the discovery findings it would set aside
 * and raise in the latest run. Nothing is made.
 *
 * @param made - The rule.
 * @returns The preview; `reason` says why the topology would not take it.
 * @throws Error with the API's reason when it refuses the rule as written.
 */
export function previewRule(made: RuleIn): Promise<RulePreview> {
	return send('POST', 'api/rules/preview', made);
}

/**
 * Make a rule: an override on everything that matches.
 *
 * @param made - Its name, what it matches, its kind, key and value, a note, who, and when it expires.
 * @returns The rule.
 * @throws Error with the API's reason when it refuses: a rule with that
 *   name, one doing the same, one the topology will not take, or one that
 *   would have expired already.
 */
export function makeRule(made: RuleIn): Promise<Rule> {
	return send('POST', 'api/rules', made);
}

/**
 * Withdraw a rule: it stops applying, and is kept for the handover.
 *
 * @param id - The rule's id.
 * @param by - Who withdraws it.
 * @throws Error with the API's reason when it refuses (none with that id).
 */
export function withdrawRule(id: string, by: string): Promise<void> {
	return send('POST', `api/rules/${encodeURIComponent(id)}/withdraw`, { by });
}

/**
 * Give a rule a new expiry, or none: an expired one applies again.
 *
 * @param id - The rule's id.
 * @param by - Who renews it.
 * @param expires - When it expires now, as an ISO time, or null for never.
 * @returns The rule.
 * @throws Error with the API's reason when it refuses.
 */
export function renewRule(id: string, by: string, expires: string | null): Promise<Rule> {
	return send('POST', `api/rules/${encodeURIComponent(id)}/renew`, { by, expires });
}

/**
 * Take an object out of a rule ("Not here"): it stops applying there.
 *
 * @param id - The rule's id.
 * @param target - The object; for a rule on ports, their device.
 * @param by - Who takes it out.
 * @returns The rule, with the exception.
 * @throws Error with the API's reason when it refuses: the rule is not on it, or it is out already.
 */
export function exceptFromRule(id: string, target: Target, by: string): Promise<Rule> {
	return send('POST', `api/rules/${encodeURIComponent(id)}/except`, { target, by });
}

/**
 * Put an object taken out of a rule back ("Apply here again").
 *
 * @param id - The rule's id.
 * @param target - The object.
 * @param by - Who puts it back.
 * @returns The rule, without the exception.
 * @throws Error with the API's reason when it refuses: it is not out of the rule.
 */
export function includeInRule(id: string, target: Target, by: string): Promise<Rule> {
	return send('POST', `api/rules/${encodeURIComponent(id)}/include`, { target, by });
}
