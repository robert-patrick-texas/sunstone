import { describe, expect, it } from 'vitest';
import type { Topology } from './api/topology.ts';
import type { StatusReport } from './api/status.ts';
import {
	linkByCid,
	membersOf,
	resourceDevices,
	resourceSites,
	resourcesHolding,
	resourcesNeeding
} from './resources.ts';
import { layeredFixture } from './test-fixture.ts';
import { indexTopology } from './topology.ts';

function index() {
	const t: Topology = structuredClone(layeredFixture);
	t.links = t.links.map((l) =>
		l.circuit?.circuit_id.a === 'NO-1'
			? { ...l, enterprise_cid: { a: 'A-INET-01', z: null } }
			: l.circuit?.circuit_id.a === 'NO-2'
				? { ...l, enterprise_cid: { a: 'C-INET-01', z: 'INET-C' } }
				: l
	);
	t.resources = [
		{
			name: 'Access',
			tags: [],
			circuits: ['A-INET-01', 'INET-C'],
			tunnels: [],
			fabrics: [],
			resources: []
		},
		{
			name: 'Cloud',
			tags: [],
			circuits: [],
			tunnels: ['GREY-A-C'],
			fabrics: ['DMVPN'],
			resources: ['Access']
		}
	];
	return indexTopology(t);
}

describe('resources', () => {
	it('finds circuits by either side of their CID', () => {
		const i = index();
		expect(linkByCid(i, 'A-INET-01')?.circuit?.circuit_id.a).toBe('NO-1');
		expect(linkByCid(i, 'INET-C')?.circuit?.circuit_id.a).toBe('NO-2');
		expect(linkByCid(i, 'nothing')).toBeUndefined();
	});

	it('lists members circuits first, then tunnels, fabrics, and resources', () => {
		const i = index();
		const kinds = membersOf(i, i.resources.get('Cloud')!).map((m) => `${m.kind}:${m.name}`);
		expect(kinds).toEqual(['tunnel:GREY-A-C', 'fabric:DMVPN', 'resource:Access']);
	});

	it('gathers the devices and sites of its members, inner resources included', () => {
		const i = index();
		expect(resourceDevices(i, 'Access').sort()).toEqual(['a-wan-01', 'c-wan-01']);
		expect(resourceDevices(i, 'Cloud').sort()).toEqual([
			'a-acc-01',
			'a-wan-01',
			'b-wan-01',
			'c-acc-02',
			'c-wan-01'
		]);
		expect(resourceSites(i, 'Cloud').sort()).toEqual(['A', 'B', 'C']);
	});

	it('says which resources hold something directly', () => {
		const i = index();
		const link = linkByCid(i, 'A-INET-01')!;
		expect(resourcesHolding(i, { kind: 'links', ids: [link.id] }).map((r) => r.name)).toEqual([
			'Access'
		]);
		expect(resourcesHolding(i, { kind: 'resource', id: 'Access' }).map((r) => r.name)).toEqual([
			'Cloud'
		]);
		expect(resourcesHolding(i, { kind: 'fabric', id: 'DMVPN' }).map((r) => r.name)).toEqual([
			'Cloud'
		]);
	});

	it('lists those needing someone, offline first', () => {
		const r = (name: string, status: 'operational' | 'degraded' | 'offline') => ({
			name,
			status,
			reasons: [],
			members: []
		});
		const report = {
			resources: [r('a', 'degraded'), r('b', 'operational'), r('c', 'offline')]
		} as unknown as StatusReport;
		expect(resourcesNeeding(report).map((x) => x.name)).toEqual(['c', 'a']);
	});
});
