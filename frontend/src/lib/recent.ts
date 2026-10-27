/**
 * The devices, sites, and links this browser looked at last, newest first,
 * for search to offer before anything is typed. They are written as links
 * write them (`device:dal-core-01`), so anything since gone from the network
 * is skipped when read back.
 */
import type { Selection } from './state.svelte.ts';
import { writeItem } from './url.ts';

export const MAX_RECENT = 8;
const KEY = 'sunstone.recent';

/**
 * Put an item at the front of the list.
 *
 * @param recent - The list, newest first.
 * @param item - What was just looked at.
 * @returns A new list, newest first, without repeats, at most {@link MAX_RECENT} long.
 */
export function withRecent(recent: string[], item: Selection): string[] {
	const written = writeItem(item);
	return [written, ...recent.filter((r) => r !== written)].slice(0, MAX_RECENT);
}

/**
 * The list as this browser last kept it.
 *
 * @returns The list, or an empty one if there is none or storage is off.
 */
export function loadRecent(): string[] {
	let stored: string | null;
	try {
		stored = localStorage.getItem(KEY);
	} catch {
		// Storage can be off (private windows, blocked site data); start afresh.
		return [];
	}
	try {
		const list: unknown = JSON.parse(stored ?? '[]');
		return Array.isArray(list) ? list.filter((r) => typeof r === 'string') : [];
	} catch {
		// Not JSON: written by something else, or damaged. Start afresh.
		return [];
	}
}

/**
 * Keep the list for next time.
 *
 * @param recent - The list, newest first.
 */
export function saveRecent(recent: string[]): void {
	try {
		localStorage.setItem(KEY, JSON.stringify(recent));
	} catch {
		// Kept for this visit only.
	}
}
