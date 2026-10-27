import { describe, expect, it } from 'vitest';
import { available, COMMANDS, commandFor, type Context, type KeyPress } from './commands.ts';

const press = (key: string, mods: Partial<KeyPress> = {}): KeyPress => ({
	key,
	ctrlKey: false,
	metaKey: false,
	altKey: false,
	...mods
});

describe('commandFor', () => {
	it('runs a command by its key, in either case', () => {
		expect(commandFor(press('l'))).toBe('live');
		expect(commandFor(press('L'))).toBe('live');
		expect(commandFor(press('2'))).toBe('view-hierarchy');
		expect(commandFor(press('?'))).toBe('help');
		expect(commandFor(press('Escape'))).toBe('clear');
	});

	it('takes Ctrl or ⌘ with K for search, and leaves other modified keys to the browser', () => {
		expect(commandFor(press('k', { ctrlKey: true }))).toBe('search');
		expect(commandFor(press('k', { metaKey: true }))).toBe('search');
		expect(commandFor(press('k'))).toBe('previous-problem');
		expect(commandFor(press('l', { ctrlKey: true }))).toBeNull();
		expect(commandFor(press('c', { metaKey: true }))).toBeNull();
		expect(commandFor(press('ArrowLeft', { altKey: true }))).toBeNull();
	});

	it('gives no two commands the same key', () => {
		const keys = COMMANDS.flatMap((c) => c.keys);
		expect(new Set(keys).size).toBe(keys.length);
	});
});

describe('available', () => {
	const none: Context = { selection: null, live: false, replaying: false, problems: 0 };
	const byId = (id: string) => COMMANDS.find((c) => c.id === id)!;

	it('needs a selection for what acts on one, and a device for a path', () => {
		expect(available(byId('focus'), none)).toBe(false);
		const site: Context = { ...none, selection: { kind: 'site', id: 'A' } };
		expect(available(byId('focus'), site)).toBe(true);
		expect(available(byId('path-from'), site)).toBe(false);
		expect(available(byId('path-from'), { ...none, selection: { kind: 'device', id: 'x' } })).toBe(
			true
		);
	});

	it('needs live state, problems, or a replayed moment for what works on them', () => {
		const live: Context = { ...none, live: true };
		expect(available(byId('earlier'), none)).toBe(false);
		expect(available(byId('earlier'), live)).toBe(true);
		expect(available(byId('next-problem'), live)).toBe(false);
		expect(available(byId('next-problem'), { ...live, problems: 2 })).toBe(true);
		expect(available(byId('later'), live)).toBe(false);
		expect(available(byId('later'), { ...live, replaying: true })).toBe(true);
	});
});
