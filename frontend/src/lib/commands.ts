/**
 * Everything Sunstone can be told to do from the keyboard or the search box,
 * in one list: the keyboard shortcuts, the commands search offers, and the
 * shortcuts help all read it, so they cannot disagree. What each command
 * does lives with the page, which holds the state it acts on.
 */
import type { Selection } from './state.svelte.ts';

export type CommandId =
	| 'search'
	| 'help'
	| 'focus'
	| 'fit'
	| 'back'
	| 'forward'
	| 'clear'
	| 'view-geo'
	| 'view-hierarchy'
	| 'view-topology'
	| 'neighborhood'
	| 'path-from'
	| 'what-if'
	| 'live'
	| 'problems'
	| 'events'
	| 'maintenance'
	| 'oncall'
	| 'discovery'
	| 'discovery-map'
	| 'next-problem'
	| 'previous-problem'
	| 'earlier'
	| 'later'
	| 'now'
	| 'copy-link'
	| 'wall'
	| 'handover';

/** What a command needs before it can run. */
export type Need = 'selection' | 'device' | 'live' | 'problems' | 'replay';

export interface Command {
	id: CommandId;
	label: string;
	group: string;
	/**
	 * Keys that run it, as shown: `/`, `Ctrl+K`, `Alt+←`. `Ctrl` also means
	 * `⌘` on a Mac.
	 */
	keys: string[];
	/** Keys the browser handles itself (Back and Forward); listed, never caught. */
	browser?: boolean;
	/** Other words people might look for it by. */
	also?: string[];
	needs?: Need[];
}

export const COMMANDS: Command[] = [
	{ id: 'search', label: 'Search', group: 'Find and move', keys: ['/', 'Ctrl+K'] },
	{
		id: 'focus',
		label: 'Bring the selection into view',
		group: 'Find and move',
		keys: ['f'],
		also: ['zoom', 'locate', 'center'],
		needs: ['selection']
	},
	{
		id: 'fit',
		label: 'Show the whole network',
		group: 'Find and move',
		keys: ['0'],
		also: ['fit', 'zoom out', 'overview']
	},
	{ id: 'back', label: 'Back', group: 'Find and move', keys: ['Alt+←'], browser: true },
	{ id: 'forward', label: 'Forward', group: 'Find and move', keys: ['Alt+→'], browser: true },
	{
		id: 'clear',
		label: 'Clear the selection, or stop choosing a path',
		group: 'Find and move',
		keys: ['Esc'],
		also: ['deselect', 'cancel']
	},
	{ id: 'help', label: 'Keyboard shortcuts', group: 'Find and move', keys: ['?'], also: ['keys'] },
	{
		id: 'view-geo',
		label: 'Geographic view',
		group: 'Views',
		keys: ['1'],
		also: ['map']
	},
	{ id: 'view-hierarchy', label: 'Hierarchy view', group: 'Views', keys: ['2'], also: ['tiers'] },
	{
		id: 'view-topology',
		label: 'Topology view',
		group: 'Views',
		keys: ['3'],
		also: ['graph', 'layout']
	},
	{
		id: 'neighborhood',
		label: 'Neighborhood of the selection',
		group: 'Views',
		keys: ['n'],
		also: ['hops', 'around'],
		needs: ['selection']
	},
	{
		id: 'path-from',
		label: 'Path from the selected device',
		group: 'Views',
		keys: [],
		also: ['route', 'trace'],
		needs: ['device']
	},
	{
		id: 'what-if',
		label: 'What if the selection fails?',
		group: 'Views',
		keys: ['w'],
		also: ['impact', 'failure'],
		needs: ['selection']
	},
	{
		id: 'live',
		label: 'Live on or off',
		group: 'Live',
		keys: ['l'],
		also: ['status', 'state', 'monitoring']
	},
	{
		id: 'problems',
		label: 'Problems list',
		group: 'Lists',
		keys: ['p'],
		also: ['alarms', 'alerts'],
		needs: ['live']
	},
	{
		id: 'events',
		label: 'Events list',
		group: 'Lists',
		keys: ['e'],
		also: ['log'],
		needs: ['live']
	},
	{
		id: 'maintenance',
		label: 'Maintenance list',
		group: 'Lists',
		keys: ['m'],
		also: ['planned', 'windows', 'change']
	},
	{
		id: 'oncall',
		label: 'On-call list',
		group: 'Lists',
		keys: ['o'],
		also: ['who', 'page', 'pager', 'rota', 'escalation', 'carriers']
	},
	{
		id: 'discovery',
		label: 'Discovery against the documentation',
		group: 'Lists',
		keys: ['d'],
		also: ['lldp', 'cdp', 'neighbors', 'cabling', 'drift', 'audit']
	},
	{
		id: 'discovery-map',
		label: 'Discovery on the map',
		group: 'Views',
		keys: [],
		also: ['undocumented', 'cabling', 'lldp', 'drift', 'overlay']
	},
	{
		id: 'next-problem',
		label: 'Next problem',
		group: 'Live',
		keys: ['j'],
		needs: ['live', 'problems']
	},
	{
		id: 'previous-problem',
		label: 'Previous problem',
		group: 'Live',
		keys: ['k'],
		needs: ['live', 'problems']
	},
	{
		id: 'earlier',
		label: '5 minutes earlier',
		group: 'Live',
		keys: ['['],
		also: ['history', 'replay', 'back in time'],
		needs: ['live']
	},
	{
		id: 'later',
		label: '5 minutes later',
		group: 'Live',
		keys: [']'],
		also: ['history', 'replay', 'forward in time'],
		needs: ['replay']
	},
	{
		id: 'now',
		label: 'Back to now',
		group: 'Live',
		keys: [],
		also: ['present', 'latest'],
		needs: ['replay']
	},
	{
		id: 'copy-link',
		label: 'Copy link',
		group: 'Share',
		keys: ['c'],
		also: ['share', 'url', 'address']
	},
	{ id: 'wall', label: 'Wall display', group: 'Share', keys: [], also: ['kiosk', 'noc', 'screen'] },
	{
		id: 'handover',
		label: 'Shift handover',
		group: 'Share',
		keys: ['h'],
		also: ['shift', 'report', 'summary', 'print']
	}
];

/** What commands can act on at the moment. */
export interface Context {
	selection: Selection | null;
	live: boolean;
	/** Replaying an earlier moment rather than showing now. */
	replaying: boolean;
	/** How many problems the live state shows. */
	problems: number;
}

/**
 * Whether a command can run.
 *
 * @param command - The command.
 * @param context - What there is to act on.
 * @returns True when everything it needs is there.
 */
export function available(command: Command, context: Context): boolean {
	return (command.needs ?? []).every((need) => {
		if (need === 'selection') return context.selection !== null;
		if (need === 'device') return context.selection?.kind === 'device';
		if (need === 'live') return context.live;
		if (need === 'problems') return context.problems > 0;
		return context.replaying;
	});
}

/** The parts of a key press that pick a shortcut. */
export interface KeyPress {
	key: string;
	ctrlKey: boolean;
	metaKey: boolean;
	altKey: boolean;
}

/**
 * The command a key press runs, if any.
 *
 * Plain keys run only without Ctrl, Alt, or ⌘ held, so the browser's own
 * shortcuts keep working; Shift is allowed, since `?` needs it. Letters match
 * in either case.
 *
 * @param press - The key press.
 * @returns The command's id, or null.
 */
export function commandFor(press: KeyPress): CommandId | null {
	const modified = press.ctrlKey || press.metaKey;
	for (const command of COMMANDS) {
		if (command.browser) continue;
		for (const keys of command.keys) {
			if (matches(keys, press, modified)) return command.id;
		}
	}
	return null;
}

function matches(keys: string, press: KeyPress, modified: boolean): boolean {
	const key = press.key.length === 1 ? press.key.toLowerCase() : press.key;
	if (keys.startsWith('Ctrl+')) {
		return modified && !press.altKey && key === keys.slice(5).toLowerCase();
	}
	if (modified || press.altKey) return false;
	return keys === 'Esc' ? key === 'Escape' : key === keys;
}
