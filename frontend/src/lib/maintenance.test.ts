import { describe, expect, it } from 'vitest';
import type { Window } from './api/operations.ts';
import { phaseOf, targetName, windowsFor } from './maintenance.ts';
import { fixtureIndex } from './test-fixture.ts';

const CIRCUIT = 'a-wan-01:Gi1/0/1--c-wan-01:Gi1/0/1';

function window(id: string, targets: Window['targets']): Window {
	return {
		id,
		title: id,
		start: '2026-10-27T14:00:00Z',
		end: '2026-10-27T16:00:00Z',
		targets,
		note: '',
		by: 'Pat',
		saved_at: '2026-10-27T13:00:00Z'
	};
}

const WINDOWS = [
	window('site-c', [{ kind: 'site', id: 'C' }]),
	window('router', [{ kind: 'device', id: 'a-wan-01' }]),
	window('circuit', [{ kind: 'links', ids: [CIRCUIT] }])
];

describe('phaseOf', () => {
	it('tells coming, open, and ended windows apart', () => {
		const [w] = WINDOWS;
		expect(w && phaseOf(w, Date.parse('2026-10-27T13:59:00Z'))).toBe('upcoming');
		expect(w && phaseOf(w, Date.parse('2026-10-27T14:00:00Z'))).toBe('open');
		expect(w && phaseOf(w, Date.parse('2026-10-27T16:00:00Z'))).toBe('ended');
	});
});

describe('windowsFor', () => {
	const index = fixtureIndex();
	const ids = (item: Parameters<typeof windowsFor>[2]) =>
		windowsFor(index, WINDOWS, item).map((w) => w.id);

	it('finds a device through its own name or its site', () => {
		expect(ids({ kind: 'device', id: 'c-acc-01' })).toEqual(['site-c']);
		expect(ids({ kind: 'device', id: 'a-wan-01' })).toEqual(['router']);
	});

	it('finds a site through any of its devices', () => {
		expect(ids({ kind: 'site', id: 'A' })).toEqual(['router']);
	});

	it('finds a link through itself or a device at either end', () => {
		expect(ids({ kind: 'links', ids: [CIRCUIT] })).toEqual(['router', 'circuit']);
	});
});

describe('targetName', () => {
	it('names devices, whole sites, and links', () => {
		const index = fixtureIndex();
		expect(targetName(index, { kind: 'device', id: 'c-wan-01' })).toBe('c-wan-01');
		expect(targetName(index, { kind: 'site', id: 'C' })).toBe('C (whole site)');
		expect(targetName(index, { kind: 'links', ids: [CIRCUIT] })).toBe('Circuit ME-1');
	});
});
