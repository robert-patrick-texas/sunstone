import { describe, expect, it } from 'vitest';
import type { OverrideNow } from './api/overrides.ts';
import { emptyMatch, target } from './overrides.svelte.ts';
import { counted, missing, offered, patterns, patternText, suggestions } from './ruleForm.ts';
import { fixture, layeredFixture, layeredIndex } from './test-fixture.ts';
import { indexTopology } from './topology.ts';

describe('patterns a test gives', () => {
	it('splits on commas and drops what is empty', () => {
		expect(patterns(' ISR4431, C9200-24T,, ')).toEqual(['ISR4431', 'C9200-24T']);
		expect(patterns('')).toEqual([]);
		expect(patternText(['ISR4431', 'C9200-24T'])).toBe('ISR4431, C9200-24T');
	});

	it('counts in words', () => {
		expect(counted(1, ['device', 'devices'])).toBe('1 device');
		expect(counted(53, ['device', 'devices'])).toBe('53 devices');
	});
});

describe('what the topology suggests for a test', () => {
	const index = indexTopology({
		...structuredClone(layeredFixture),
		regions: [{ name: 'South' }, { name: 'Americas' }],
		devices: fixture.devices.map((d, i) => ({ ...d, platform: i % 2 ? 'ISR4431' : 'C9200-24T' }))
	});

	it('gives site codes, regions, and platforms, each once and in order', () => {
		expect(suggestions(index, 'device', 'site')).toEqual(['A', 'B', 'C']);
		expect(suggestions(index, 'site', 'region')).toEqual(['Americas', 'East', 'South']);
		expect(suggestions(index, 'port', 'platform')).toEqual(['C9200-24T', 'ISR4431']);
	});

	it("gives a link's roles at the edge, and internal for our own cables", () => {
		expect(suggestions(index, 'link', 'role')).toEqual(['access', 'internal', 'tbd', 'transit']);
		expect(suggestions(index, 'device', 'role')).toEqual(['access', 'core', 'wan-edge']);
	});

	it('gives kinds and tenants by what has them', () => {
		expect(suggestions(index, 'link', 'kind')).toEqual(['lan', 'wan']);
		expect(suggestions(index, 'external', 'kind')).toEqual(['application', 'tenant']);
		expect(suggestions(index, 'external', 'tenant')).toEqual(['T1']);
	});

	it('gives tags of the kind, its own and those overrides add', () => {
		const tag = { kind: 'tag', state: 'active', value: 'lab' } as const;
		const added = [
			{ ...tag, target: target('tunnel', 'BLUE-A-C') },
			{ ...tag, value: 'old', state: 'expired', target: target('tunnel', 'BLUE-A-C') },
			{ ...tag, value: 'branch', target: target('device', 'c-acc-01') }
		] as OverrideNow[];
		expect(suggestions(index, 'tunnel', 'tag', added)).toEqual(['lab', 'secure']);
		expect(suggestions(index, 'port', 'tag', added)).toEqual(['branch']);
	});

	it('gives none for a name or an interface', () => {
		expect(suggestions(layeredIndex(), 'device', 'name')).toEqual([]);
		expect(suggestions(layeredIndex(), 'port', 'interface')).toEqual([]);
	});
});

describe('suggestions as the field reads', () => {
	const values = ['C9200-24T', 'ISR4431'];

	it('offers the values alone before any comma', () => {
		expect(offered('IS', values)).toEqual(values);
	});

	it('goes on after a comma, without what is given already', () => {
		expect(offered('isr4431, C', values)).toEqual(['isr4431, C9200-24T']);
		expect(offered('ISR4431,', values)).toEqual(['ISR4431,C9200-24T']);
	});
});

describe('what a draft still needs', () => {
	const draft = { match: emptyMatch('device'), kind: 'tag', key: null, value: 'lab' } as const;

	it('needs an interface on ports, a key or field, and a value', () => {
		expect(missing(draft)).toBeNull();
		expect(missing({ ...draft, value: '' })).toBe('a value');
		expect(missing({ ...draft, kind: 'label' })).toBe('a key');
		expect(missing({ ...draft, kind: 'lock' })).toBe('a field');
		const port = { ...draft, match: emptyMatch('port'), kind: 'ignore-neighbor' } as const;
		expect(missing(port)).toBe('an interface');
		const iface = { ...port.match, interface: ['Gi1/0/48'] };
		expect(missing({ ...port, match: iface, value: null })).toBe("the neighbors' names");
	});

	it('takes no value to hide, or for one device on each port', () => {
		expect(missing({ ...draft, kind: 'hide-status', value: null })).toBeNull();
		const port = { ...emptyMatch('port'), interface: ['Gi1/0/48'] };
		expect(missing({ ...draft, match: port, kind: 'one-device', value: null })).toBeNull();
	});
});
