import { afterEach, describe, expect, it } from 'vitest';
import type { Finding } from './api/discovery.ts';
import type { OverrideNow, RuleNow, Target } from './api/overrides.ts';
import {
	describeRule,
	effects,
	effectsKey,
	emptyMatch,
	hiddenFromStatus,
	hiddenOnMap,
	labels,
	lockOf,
	matchText,
	namePattern,
	on,
	overrides,
	presetFrom,
	ruleName,
	ruleOffers,
	rulesOn,
	signature,
	tags,
	target
} from './overrides.svelte.ts';
import { fixtureIndex } from './test-fixture.ts';

const index = fixtureIndex();

function rule(more: Partial<RuleNow> & Pick<RuleNow, 'kind'>, on: Target[] = []): RuleNow {
	return {
		id: `r-${more.kind}`,
		name: 'Rule',
		match: emptyMatch('device'),
		key: null,
		value: null,
		note: '',
		by: 'Pat',
		at: '2026-11-09T12:00:00Z',
		expires: null,
		renewed: null,
		withdrawn: null,
		excepted: [],
		state: 'active',
		reason: null,
		matches: on.map((t) => ({ target: t, topology_value: null })),
		overridden: [],
		...more
	};
}

function own(of: Target, kind: OverrideNow['kind'], more: Partial<OverrideNow> = {}): OverrideNow {
	return {
		id: `o-${kind}`,
		target: of,
		kind,
		key: null,
		value: null,
		note: '',
		by: 'Pat',
		at: '2026-11-09T12:00:00Z',
		expires: null,
		renewed: null,
		withdrawn: null,
		state: 'active',
		reason: null,
		topology_value: null,
		...more
	};
}

const acc1 = target('device', 'a-acc-01');
const acc2 = target('device', 'c-acc-01');

afterEach(() => {
	overrides.list = [];
	overrides.rules = [];
	overrides.showHidden = false;
});

describe('what rules do on the objects they apply on', () => {
	it('adds tags and labels beside those made on the object, once each', () => {
		overrides.list = [own(acc1, 'tag', { value: 'Lab' })];
		overrides.rules = [
			rule({ kind: 'tag', value: 'lab' }, [acc1, acc2]),
			rule({ id: 'r2', kind: 'label', key: 'lifecycle', value: 'EoL 2027' }, [acc1])
		];
		expect(tags(acc1)).toEqual(['Lab']);
		expect(tags(acc2)).toEqual(['lab']);
		expect(labels(acc1)).toEqual([{ key: 'lifecycle', value: 'EoL 2027' }]);
		// Overrides on the object are listed alone.
		expect(on(acc1).map((o) => o.kind)).toEqual(['tag']);
	});

	it('hides from the map and from status, and counts each object hidden', () => {
		overrides.rules = [
			rule({ kind: 'hide-map' }, [acc1, acc2]),
			rule({ id: 'r2', kind: 'hide-status' }, [acc2])
		];
		const hidden = hiddenOnMap(index);
		expect([...hidden.devices].sort()).toEqual(['a-acc-01', 'c-acc-01']);
		expect(hidden.count).toBe(2);
		expect(hiddenFromStatus(acc2)?.rule?.id).toBe('r2');
		expect(hiddenFromStatus(acc1)).toBeUndefined();
	});

	it("gives a rule's lock, and what the topology says, where none of the object's own applies", () => {
		const r = rule({ kind: 'lock', key: 'platform', value: 'C9300' }, [acc1, acc2]);
		r.matches[0] = { target: acc1, topology_value: '' };
		overrides.rules = [r];
		overrides.list = [own(acc2, 'lock', { key: 'platform', value: 'Own', state: 'expired' })];
		expect(lockOf(acc1, 'platform')?.rule?.id).toBe(r.id);
		expect(lockOf(acc1, 'platform')?.topology_value).toBe('');
		// A rule's lock that applies comes before the object's own expired one…
		expect(lockOf(acc2, 'platform')?.rule?.id).toBe(r.id);
		// …which is still given where no lock applies, to renew.
		overrides.rules = [];
		expect(lockOf(acc2, 'platform')?.value).toBe('Own');
	});

	it('leaves rules on ports to discovery, and lists them on the device', () => {
		const ports = rule(
			{
				kind: 'ignore-neighbor',
				value: '*-acc-*',
				match: { ...emptyMatch('port'), interface: ['Gi1/0/48'] }
			},
			[acc1]
		);
		overrides.rules = [ports];
		expect(effects()).toEqual([]);
		expect(rulesOn(acc1).map((r) => [r.rule.id, r.how])).toEqual([[ports.id, 'applies']]);
	});

	it('says where a rule is overridden or taken out', () => {
		overrides.rules = [
			rule({
				kind: 'hide-status',
				overridden: [acc1],
				excepted: [{ target: acc2, by: 'Sam', at: '2026-11-09T13:00:00Z' }]
			})
		];
		expect(rulesOn(acc1).map((r) => r.how)).toEqual(['overridden']);
		const [out] = rulesOn(acc2);
		expect(out?.how).toBe('excepted');
		expect(out?.excepted?.by).toBe('Sam');
		expect(effects()).toEqual([]);
	});

	it('changes the keys views follow when what applies changes', () => {
		const before = [effectsKey(), signature(overrides.list, overrides.rules)];
		overrides.rules = [rule({ kind: 'tag', value: 'x' }, [acc1])];
		// A tag is the views' alone; the server need not be asked again.
		expect(effectsKey()).not.toBe(before[0]);
		expect(signature(overrides.list, overrides.rules)).toBe(before[1]);
		overrides.rules = [rule({ kind: 'hide-status' }, [acc1])];
		expect(signature(overrides.list, overrides.rules)).not.toBe(before[1]);
	});
});

describe('rules in words', () => {
	it('says what a rule matches', () => {
		expect(matchText(emptyMatch('site'))).toBe('Every site');
		expect(
			matchText({ ...emptyMatch('device'), role: ['access'], platform: ['ISR4431', 'C9200-24T'] })
		).toBe('Every device with role access, on platform ISR4431 or C9200-24T');
		expect(
			matchText({
				...emptyMatch('port'),
				role: ['access'],
				interface: ['GigabitEthernet1/0/48']
			})
		).toBe('Port Gi1/0/48 on every device with role access');
		expect(matchText({ ...emptyMatch('link'), role: ['transit'], tag: ['a', 'b', 'c'] })).toBe(
			'Every link with role at the edge transit, tagged a, b, or c'
		);
	});

	it('says what a rule does, and names it until someone does', () => {
		expect(describeRule({ kind: 'ignore-neighbor', key: null, value: '*' })).toBe(
			'Ignores every neighbor'
		);
		expect(describeRule({ kind: 'lock', key: 'priority', value: 'low' })).toBe(
			'Priority locked: low'
		);
		expect(
			ruleName({
				kind: 'hide-status',
				key: null,
				value: null,
				match: { ...emptyMatch('device'), role: ['access'] }
			})
		).toBe('Hidden from status: every device with role access');
	});
});

describe('making a rule like an override', () => {
	it('matches by the role and platform of a port’s device, and the port', () => {
		const o = own(target('port', 'c-acc-01', 'GigabitEthernet1/0/48'), 'ignore-neighbor', {
			value: 'c-acc-02'
		});
		const draft = presetFrom(o, index);
		expect(draft.match).toEqual({
			...emptyMatch('port'),
			role: ['access'],
			interface: ['Gi1/0/48']
		});
		expect([draft.kind, draft.value]).toEqual(['ignore-neighbor', 'c-acc-02']);
	});

	it('matches a site by its region, and takes no value where a rule takes none', () => {
		const draft = presetFrom(own(target('site', 'C'), 'hide-map'), index);
		expect(draft.match.region).toEqual(['South']);
		expect(draft.value).toBeNull();
	});
});

describe('rules discovery offers', () => {
	function finding(id: string, kind: Finding['kind'], seen: [string, string][]): Finding {
		return {
			id,
			kind,
			title: id,
			detail: '',
			seen: seen.map(([device, iface]) => ({ device, interface: iface })),
			devices: seen.map(([device]) => device)
		} as Finding;
	}

	it('offers one for a cable no one documented on the same port of two devices with one role', () => {
		const chain = finding('u1', 'undocumented', [
			['a-acc-01', 'GigabitEthernet1/0/48'],
			['c-acc-01', 'GigabitEthernet1/0/48']
		]);
		const lone = finding('u2', 'unknown-device', [
			['c-acc-02', 'GigabitEthernet1/0/10'],
			['SEP0040ABCD', 'Port 1']
		]);
		const lab = finding('u3', 'unknown-device', [
			['c-acc-02', 'GigabitEthernet1/0/48'],
			['lab-sw-01', 'Gi0/1']
		]);
		const labToo = finding('u4', 'unknown-device', [
			['a-acc-01', 'GigabitEthernet1/0/48'],
			['lab-sw-02', 'Gi0/1']
		]);
		const [labs, offer, ...more] = ruleOffers([chain, lone, lab, labToo], index);
		expect(more).toEqual([]);
		// Lab switches on the same port are another offer, not ignored with the chain.
		expect(labs?.draft.value).toBe('lab-sw-*');
		expect(labs?.findings).toEqual(['u3', 'u4']);
		expect(offer?.label).toBe('Rule: ignore *-acc-* on Gi1/0/48 of every access device…');
		expect(offer?.draft.match.interface).toEqual(['Gi1/0/48']);
		expect(offer?.draft.match.role).toEqual(['access']);
		expect(offer?.draft.value).toBe('*-acc-*');
		expect(offer?.findings).toEqual(['u1']);
	});

	it('makes a pattern from the names seen', () => {
		expect(namePattern(['SEP0040AB', 'SEP0040CD'], index)).toBe('SEP0040*');
		expect(namePattern(['a-acc-01', 'a-acc-02'], index)).toBe('*-acc-*');
		expect(namePattern(['x-1', 'y-2'], index)).toBe('*');
	});
});
