import { describe, expect, it } from 'vitest';
import type { Link, Topology } from './api/topology.ts';
import { linkRating, ratingText, responsibleText } from './priorities.ts';
import { layeredFixture } from './test-fixture.ts';

const find = (t: Topology, pred: (l: Link) => boolean): Link => t.links.find(pred)!;
const encryptor = (l: Link) => 'external' in l.b;
const circuit = (l: Link) => l.circuit?.circuit_id.a === 'NO-1';
const cable = (l: Link) => !l.circuit && 'device' in l.b;

describe('linkRating', () => {
	it('defaults by role: access low, the downstream party answering first', () => {
		const t = structuredClone(layeredFixture);
		expect(linkRating(t, find(t, encryptor))).toEqual({
			priority: 'low',
			source: 'default',
			by: 'access',
			responsible: 'T1'
		});
	});

	it('defaults to medium for TBD circuits and internal cables, the enterprise answering', () => {
		const t = structuredClone(layeredFixture);
		expect(linkRating(t, find(t, circuit))).toMatchObject({ priority: 'medium', by: 'tbd' });
		expect(linkRating(t, find(t, cable))).toMatchObject({
			priority: 'medium',
			by: 'internal',
			responsible: null
		});
	});

	it('takes the highest default of its roles, and the table in the topology', () => {
		const t = structuredClone(layeredFixture);
		const link = { ...find(t, encryptor), edges: ['access', 'transit'] } as Link;
		expect(linkRating(t, link)).toMatchObject({ priority: 'medium', responsible: null });
		t.priorities = { access: 'ignored' };
		expect(linkRating(t, find(t, encryptor)).priority).toBe('ignored');
	});

	it("takes a device's or the far end's, the higher of the two, before the default", () => {
		const t = structuredClone(layeredFixture);
		const link = find(t, encryptor);
		t.externals = t.externals.map((e) => (e.name === 'r1-c' ? { ...e, priority: 'medium' } : e));
		expect(linkRating(t, link)).toMatchObject({ priority: 'medium', source: 'device', by: 'r1-c' });
		t.devices = t.devices.map((d) => (d.name === link.a.device ? { ...d, priority: 'high' } : d));
		expect(linkRating(t, link)).toMatchObject({ priority: 'high', by: link.a.device });
	});

	it("takes the link's own before anything else", () => {
		const t = structuredClone(layeredFixture);
		const link = { ...find(t, cable), priority: 'ignored' } as Link;
		t.devices = t.devices.map((d) => ({ ...d, priority: 'high' }));
		expect(linkRating(t, link)).toMatchObject({ priority: 'ignored', source: 'link' });
	});

	it('says where it comes from', () => {
		const t = structuredClone(layeredFixture);
		expect(ratingText(linkRating(t, find(t, encryptor)))).toBe('Low · access, by default');
	});
});

describe('responsibleText', () => {
	const said = (t: Topology, link: Link) => responsibleText(t, link, linkRating(t, link));

	it('names the enterprise, or the party downstream and what kind it is', () => {
		const t = structuredClone(layeredFixture);
		expect(said(t, find(t, cable))).toBe('Enterprise');
		expect(said(t, find(t, encryptor))).toBe('T1 (tenant)');
		t.terms = { tenant: 'Customer' };
		expect(said(t, find(t, encryptor))).toBe('T1 (customer)');
	});

	it("names a transport's provider, or the transport", () => {
		const t = structuredClone(layeredFixture);
		const link = { ...find(t, circuit), edges: ['interconnect'] } as Link;
		expect(said(t, link)).toBe('INET (transport)');
		t.transports = t.transports.map((x) => ({ ...x, provider: 'Mesa Carrier' }));
		expect(said(t, link)).toBe('Mesa Carrier (provider of INET)');
	});
});
