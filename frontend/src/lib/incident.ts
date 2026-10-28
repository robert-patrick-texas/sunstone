/**
 * Incidents as the report shows them: where each stands, how long it has
 * lasted, which to open first, and the postmortem to post.
 */
import type { IncidentReport, IncidentSummary } from './api/incidents.ts';
import { duration } from './handover.ts';

/** What each status reads as. */
export const STATUS = { open: 'Open', cleared: 'Cleared', closed: 'Closed' } as const;

/**
 * An incident, to choose it from a list.
 *
 * @param incident - The incident.
 * @returns For example "12 · HOU cut off · open".
 */
export function incidentLabel(
	incident: Pick<IncidentSummary, 'number' | 'title' | 'status'>
): string {
	return `${incident.number} · ${incident.title} · ${incident.status}`;
}

/**
 * How long an incident lasted, or has lasted so far, from when it began.
 *
 * @param incident - The incident.
 * @param now - The time now, in milliseconds.
 * @returns For example "1 h 05 min", "35 min so far", or null if it began
 *   before history does.
 */
export function lasted(
	incident: Pick<IncidentSummary, 'began' | 'cleared_at'>,
	now: number
): string | null {
	if (!incident.began) return null;
	const start = Date.parse(incident.began);
	if (!incident.cleared_at) return `${duration(now - start)} so far`;
	return duration(Date.parse(incident.cleared_at) - start);
}

/**
 * How long after an incident began something happened.
 *
 * @param incident - The incident.
 * @param at - When it happened.
 * @returns For example "7 min in", or null if it began before history.
 */
export function into(incident: Pick<IncidentSummary, 'began'>, at: string): string | null {
	return incident.began ? `${duration(Date.parse(at) - Date.parse(incident.began))} in` : null;
}

/**
 * The incident to show first: the newest not yet closed, else the newest.
 *
 * @param incidents - Every incident, newest first.
 * @returns Its number, or null if there are none.
 */
export function first(incidents: IncidentSummary[]): number | null {
	return (incidents.find((i) => i.status !== 'closed') ?? incidents[0])?.number ?? null;
}

/**
 * An incident's postmortem as it is copied, to post in chat or send by email.
 *
 * @param incident - The incident.
 * @param link - Where to open it in Sunstone.
 * @returns The subject, the text, and the link.
 */
export function postmortemText(incident: Pick<IncidentReport, 'message'>, link: string): string {
	return `${incident.message.subject}\n\n${incident.message.text}\n\nIn Sunstone: ${link}`;
}
