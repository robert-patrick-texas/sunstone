import { describe, expect, it } from 'vitest';
import type { OnCall, Ownership, TeamNow } from './api/oncall.ts';
import { carriersFor, linksOf, ownerOf, personOf, wouldPage } from './oncall.ts';
import { commandEntries, oncallEntries, search } from './search.ts';
import { fixtureIndex } from './test-fixture.ts';

const shift = (primary: string, secondary: string | null) => ({
	team: 'net',
	primary,
	secondary,
	since: '2026-10-26T14:00:00Z',
	until: '2026-11-02T14:00:00Z'
});

const NET: TeamNow = {
	id: 'net',
	name: 'Network Central',
	owns: ['Everything in South'],
	rotation: ['pat', 'lee'],
	now: shift('pat', 'lee'),
	next: shift('lee', 'pat'),
	manager: 'dana',
	escalation: [
		{ after_min: 0, to: 'primary' },
		{ after_min: 15, to: 'secondary' },
		{ after_min: 30, to: 'manager' }
	]
};

const ONCALL: OnCall = {
	at: '2026-10-27T15:00:00Z',
	teams: [
		NET,
		{
			...NET,
			id: 'wan',
			name: 'WAN and carriers',
			owns: ['WAN links'],
			rotation: ['sam'],
			manager: null,
			now: shift('sam', null)
		}
	],
	people: [
		{ id: 'pat', name: 'Pat Rivera', phone: '+1 214 555 0100' },
		{ id: 'lee', name: 'Lee Chen', phone: '+1 214 555 0101' },
		{ id: 'dana', name: 'Dana Novak' },
		{ id: 'sam', name: 'Sam Okafor' }
	],
	carriers: [{ provider: 'Mesa Carrier', phone: '+1 800 555 0102' }],
	covers: [],
	urgency: {
		outage: 'high',
		'link-down': 'high',
		congested: 'high',
		loss: 'low',
		busy: 'low',
		nodata: 'low'
	}
};

describe('ownerOf', () => {
	const owners: Ownership = {
		sites: { A: 'net' },
		devices: { 'a-core-01': 'net' },
		links: { l2: 'wan' }
	};

	it('looks up a site, a device, or the first owned of some links', () => {
		expect(ownerOf(owners, { kind: 'site', id: 'A' })).toBe('net');
		expect(ownerOf(owners, { kind: 'device', id: 'a-core-01' })).toBe('net');
		expect(ownerOf(owners, { kind: 'links', ids: ['l1', 'l2'] })).toBe('wan');
		expect(ownerOf(owners, { kind: 'device', id: 'nobody-owns-me' })).toBeNull();
	});
});

describe('wouldPage', () => {
	it('names whom each step of escalation would page now', () => {
		expect(wouldPage(ONCALL, NET).map((s) => [s.person.name, s.to, s.afterMin])).toEqual([
			['Pat Rivera', 'primary', 0],
			['Lee Chen', 'secondary', 15],
			['Dana Novak', 'manager', 30]
		]);
	});

	it('leaves out steps with no one to page', () => {
		const [, wan] = ONCALL.teams;
		expect(wouldPage(ONCALL, wan!).map((s) => s.to)).toEqual(['primary']);
	});
});

describe('personOf', () => {
	it('names someone gone from the directory by id', () => {
		expect(personOf(ONCALL, 'pat').name).toBe('Pat Rivera');
		expect(personOf(ONCALL, 'ghost').name).toBe('ghost');
	});
});

describe('carriersFor', () => {
	it('gives the carrier to call about each circuit', () => {
		const index = fixtureIndex();
		const ids = index.topology.links.map((l) => l.id);
		const found = carriersFor(ONCALL, index, ids);
		// The fixture's three WAN links are all Mesa Carrier circuit ME-1.
		expect(found).toHaveLength(3);
		expect(found[0]?.carrier?.phone).toBe('+1 800 555 0102');
		expect(linksOf({ kind: 'device', id: 'x' })).toEqual([]);
	});
});

describe('oncallEntries', () => {
	it('finds teams by name or what they own, and people by name, leading to their team', () => {
		const entries = oncallEntries(ONCALL);
		expect(search('central', [entries])[0]?.entries[0]?.label).toBe('Network Central');
		expect(search('wan links', [entries])[0]?.entries[0]?.label).toBe('WAN and carriers');
		const [lee] = search('lee', [entries]).flatMap((g) => g.entries);
		expect(lee?.detail).toBe('Network Central · +1 214 555 0101');
		expect(lee?.target).toEqual({ kind: 'team', team: 'net' });
		const [pat] = search('pat rivera', [entries]).flatMap((g) => g.entries);
		expect(pat?.detail).toMatch(/^On call for Network Central/);
		// Someone on no team, or only a manager, is still found by name.
		expect(search('dana', [entries]).flatMap((g) => g.entries)).toHaveLength(1);
		expect(search('lee', [commandEntries([])])).toEqual([]);
	});
});
