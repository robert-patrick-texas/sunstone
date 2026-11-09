import { afterEach, describe, expect, it } from 'vitest';
import type { OverrideNow, Target } from './api/overrides.ts';
import {
	aliases,
	describe as said,
	hiddenOnMap,
	labels,
	lockOf,
	named,
	on,
	overrides,
	shown,
	signature,
	tags,
	target,
	targetName,
	targetOf
} from './overrides.svelte.ts';
import { fixtureIndex } from './test-fixture.ts';

const index = fixtureIndex();

let next = 0;

function made(of: Target, kind: OverrideNow['kind'], more: Partial<OverrideNow> = {}): OverrideNow {
	next += 1;
	return {
		id: `o${next}`,
		target: of,
		kind,
		key: null,
		value: null,
		note: '',
		by: 'Pat',
		at: '2026-11-08T12:00:00Z',
		expires: null,
		renewed: null,
		withdrawn: null,
		state: 'active',
		reason: null,
		topology_value: null,
		...more
	};
}

afterEach(() => {
	overrides.list = [];
	overrides.showHidden = false;
});

describe('names', () => {
	it('shows a device by its new name, and replaces it in text as a whole word', () => {
		overrides.list = [made(target('device', 'c-acc-01'), 'rename', { value: 'C ACC One' })];
		expect(shown('c-acc-01')).toBe('C ACC One');
		expect(shown('c-acc-02')).toBe('c-acc-02');
		expect(named('c-wan-01 – c-acc-01 down; c-acc-010 too')).toBe(
			'c-wan-01 – C ACC One down; c-acc-010 too'
		);
		expect(aliases(target('device', 'c-acc-01'))).toEqual(['C ACC One']);
	});

	it('leaves names alone for one not applied, and text alone without any', () => {
		overrides.list = [
			made(target('device', 'c-acc-01'), 'rename', { value: 'X', state: 'expired' })
		];
		expect(shown('c-acc-01')).toBe('c-acc-01');
		expect(named('c-acc-01 down')).toBe('c-acc-01 down');
	});
});

describe('tags, labels, and locks', () => {
	it('gives what applies on each target', () => {
		const d = target('device', 'a-acc-01');
		overrides.list = [
			made(d, 'label', { key: 'rack', value: 'B12' }),
			made(d, 'tag', { value: 'lab' }),
			made(d, 'tag', { value: 'old', state: 'expired' }),
			made(d, 'lock', { key: 'role', value: 'distribution', topology_value: 'access' }),
			made(target('device', 'a-core-01'), 'tag', { value: 'core' })
		];
		expect(tags(d)).toEqual(['lab']);
		expect(labels(d)).toEqual([{ key: 'rack', value: 'B12' }]);
		expect(lockOf(d, 'role')?.topology_value).toBe('access');
		expect(on(d)).toHaveLength(4);
		expect(said(overrides.list[3]!)).toBe('Role locked: distribution');
	});
});

describe('hiding from the map', () => {
	it('hides a site with its devices and their links, unless shown anyway', () => {
		overrides.list = [made(target('site', 'C'), 'hide-map')];
		const hidden = hiddenOnMap(index);
		expect([...hidden.devices].sort()).toEqual(['c-acc-01', 'c-acc-02', 'c-wan-01']);
		expect(hidden.links.size).toBe(4);
		expect(hidden.count).toBe(1);
		overrides.showHidden = true;
		expect(hiddenOnMap(index).devices.size).toBe(0);
		expect(hiddenOnMap(index).count).toBe(1);
	});
});

describe('targets', () => {
	it('come from a selection, and are said as people say them', () => {
		expect(targetOf({ kind: 'links', ids: ['x', 'y'] })).toBeNull();
		const link = index.topology.links[0]!;
		const of = targetOf({ kind: 'links', ids: [link.id] });
		expect(of).toEqual({ kind: 'link', id: link.id, interface: null });
		expect(targetName(of!, index)).toBe('a-wan-01 – a-core-01');
		expect(targetName(target('site', 'C'), index)).toBe('C (Branch C)');
		expect(targetName(target('port', 'c-wan-01', 'GigabitEthernet1/0/1'))).toBe('c-wan-01 Gi1/0/1');
	});
});

describe('signature', () => {
	it('changes only for what the server applies', () => {
		const tag = made(target('device', 'a-acc-01'), 'tag', { value: 'lab' });
		const lock = made(target('device', 'a-acc-01'), 'lock', { key: 'role', value: 'core' });
		expect(signature([tag])).toBe('');
		expect(signature([tag, lock])).toBe(lock.id);
		expect(signature([{ ...lock, state: 'expired' }])).toBe('');
	});
});
