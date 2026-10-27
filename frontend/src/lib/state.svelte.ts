/**
 * UI state shared by every view, so switching views keeps the user's context.
 */
import { SvelteSet } from 'svelte/reactivity';

export type View = 'geo' | 'hierarchy';

export type Selection =
	{ kind: 'device'; id: string } | { kind: 'site'; id: string } | { kind: 'links'; ids: string[] };

export const ui = $state({
	view: 'geo' as View,
	selection: null as Selection | null,
	/** Incremented to ask the current view to bring the selection into sight. */
	focusRequest: 0
});

/** Sites the hierarchy view shows device by device instead of as one box. */
export const expandedSites = new SvelteSet<string>();

/**
 * Change the selection.
 *
 * @param selection - What to select, or null to clear.
 * @param focus - Also move the current view to it (search results, links in the details panel).
 */
export function select(selection: Selection | null, focus = false): void {
	ui.selection = selection;
	if (focus) ui.focusRequest++;
}
