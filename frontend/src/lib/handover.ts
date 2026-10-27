/**
 * The shift handover as the report shows it: how long things lasted,
 * outages sorted into whole sites, circuits and other links, and single
 * devices, the handovers saved at shift changes, and the message to post.
 */
import type { Handover, HandoverSummary, Outage } from './api/handover.ts';
import type { Problem } from './api/analysis.ts';
import { clock } from './history.ts';
import { DEFAULT_HANDOVER_H } from './url.ts';

/** Spans a handover can cover, in hours; the first is the default. */
export const SPANS = [DEFAULT_HANDOVER_H, 8] as const;

/**
 * A length of time, readably.
 *
 * @param ms - Milliseconds.
 * @returns For example "35 min", "1 h 05 min", "3 h".
 */
export function duration(ms: number): string {
	const minutes = Math.max(0, Math.round(ms / 60_000));
	if (minutes < 60) return `${minutes} min`;
	const [h, m] = [Math.floor(minutes / 60), minutes % 60];
	return m ? `${h} h ${String(m).padStart(2, '0')} min` : `${h} h`;
}

/**
 * How long an outage lasted, or has lasted so far.
 *
 * @param outage - The outage.
 * @param now - The time now, in milliseconds.
 * @returns For example "35 min", "1 h 05 min so far", or "since before history".
 */
export function lasted(outage: Outage, now: number): string {
	if (!outage.start) return outage.end ? 'since before history' : 'all day';
	const start = Date.parse(outage.start);
	if (!outage.end) return `${duration(now - start)} so far`;
	return duration(Date.parse(outage.end) - start);
}

/** Outages sorted the way a handover reads them. */
export interface OutageSections {
	/** More than one device at a site, with any links there. */
	sites: Outage[];
	/** Circuits and other links down on their own. */
	links: Outage[];
	/** One device on its own. */
	devices: Outage[];
}

/**
 * Sort outages into whole sites, links, and single devices, each latest first.
 *
 * @param outages - Outages, latest first.
 * @returns The three kinds.
 */
export function outageSections(outages: Outage[]): OutageSections {
	return {
		sites: outages.filter((o) => o.target.kind === 'site'),
		links: outages.filter((o) => o.target.kind === 'links'),
		devices: outages.filter((o) => o.target.kind === 'device')
	};
}

/**
 * Who is on a problem now, for its line in a handover.
 *
 * @param problem - The problem.
 * @returns For example "On it: Pat · carrier ticket 4411", "Planned",
 *   "Paged, no one on it yet", or "No one on it".
 */
export function standing(problem: Pick<Problem, 'ack' | 'planned' | 'paging'>): string {
	if (problem.ack)
		return `On it: ${problem.ack.by}${problem.ack.note ? ` · ${problem.ack.note}` : ''}`;
	if (problem.planned.length) return 'Planned';
	if (problem.paging && !problem.paging.stopped) return 'Paged, no one on it yet';
	return 'No one on it';
}

/**
 * A saved handover, to choose it from a list.
 *
 * @param saved - The saved handover.
 * @returns For example "Handed over 07:00 · 6 open, 1 note".
 */
export function savedLabel(saved: HandoverSummary): string {
	const notes = saved.notes ? `, ${saved.notes} ${saved.notes === 1 ? 'note' : 'notes'}` : '';
	return `Handed over ${clock(saved.until)} · ${saved.problems} open${notes}`;
}

/**
 * A handover's message as it is copied, to post in chat or send by email.
 *
 * @param handover - The handover.
 * @param link - Where to open it in Sunstone.
 * @returns The subject, the text, and the link.
 */
export function messageText(handover: Pick<Handover, 'message'>, link: string): string {
	return `${handover.message.subject}\n\n${handover.message.text}\n\nIn Sunstone: ${link}`;
}
