import { describe, expect, it } from 'vitest';
import { beneath, carried, fabricTunnels, footprint, layersOf, onDemand } from './layers.ts';
import { term, termWords } from './terms.ts';
import { layeredFixture, layeredIndex } from './test-fixture.ts';
import { deviceEnds, endName, farDevice, indexTopology, portName } from './topology.ts';
import type { Fabric } from './api/topology.ts';

const index = layeredIndex();
const circuit = 'c-wan-01:GigabitEthernet0/0/0--transport:INET';

describe('link ends', () => {
	it('names ends that are not devices, and leaves them out of device ends', () => {
		const link = index.links.get(circuit)!;
		expect(deviceEnds(link).map((e) => e.device)).toEqual(['c-wan-01']);
		expect(farDevice(link)).toBeNull();
		expect([endName(link.b), portName(link.b)]).toEqual(['INET', 'INET']);
		expect(portName(link.a)).toBe('c-wan-01 Gi0/0/0');
		const encryptor = index.links.get('c-acc-02:Gi1/0/9--external:r1-c:black')!;
		expect(portName(encryptor.b)).toBe('r1-c black');
		expect(index.linksByNode.get('transport:INET')).toHaveLength(2);
	});
});

describe('layersOf', () => {
	const layers = layersOf(index);

	it('gives circuits into a transport its network', () => {
		expect(carried(index, index.links.get(circuit)!)).toEqual(['black']);
	});

	it('works out how deep each network sits', () => {
		const depth = (n: string) => layers.slices.get(n)?.depth;
		expect([depth('black'), depth('blue'), depth('grey'), depth('red'), depth('corp')]).toEqual([
			0, 1, 2, 3, 1
		]);
		expect([...(layers.slices.get('blue')?.riders ?? [])]).toEqual(['grey']);
	});

	it("brings a tenant's network to the places of the network it rides", () => {
		const red = layers.slices.get('red')!;
		expect([...red.devices]).toEqual(['c-acc-02']);
		expect([...red.sites]).toEqual(['C']);
		expect([...red.nodes]).toEqual(['external:r1-c']);
	});

	it('knows which transports each site has circuits into', () => {
		expect(layers.transportsAt.get('C')).toEqual(['INET']);
		expect(layers.transportsAt.has('B')).toBe(false);
	});

	it('lists every network under some, however deep', () => {
		expect([...beneath(layers, ['red'])].sort()).toEqual(['black', 'blue', 'grey']);
		expect([...beneath(layers, ['grey', 'blue'])]).toEqual(['black']);
	});
});

describe('fabrics', () => {
	const dmvpn = index.fabrics.get('DMVPN')!;
	const members = (n: number) =>
		Array.from({ length: n }, (_, i) => ({
			device: `d${i}`,
			interface: 'Tunnel1',
			role: 'peer' as const
		}));

	it('makes a tunnel from each spoke to each hub', () => {
		expect(fabricTunnels(dmvpn).map(({ a, b }) => `${a.device}–${b.device}`)).toEqual([
			'c-wan-01–a-wan-01',
			'c-wan-01–b-wan-01'
		]);
		expect(
			onDemand({ ...dmvpn, members: [...dmvpn.members, { ...dmvpn.members[2]!, device: 'x' }] })
		).toBe(1);
	});

	it('makes every pair for a full mesh, and none for a group', () => {
		const mesh: Fabric = { ...dmvpn, shape: 'full-mesh', members: members(4) };
		expect(fabricTunnels(mesh)).toHaveLength(6);
		expect(onDemand(mesh)).toBe(0);
		expect(fabricTunnels({ ...mesh, shape: 'group' })).toEqual([]);
	});
});

describe('footprint', () => {
	it('is the circuits and their devices for a transport', () => {
		const f = footprint(index, { kind: 'transport', id: 'INET' });
		expect([...f.devices].sort()).toEqual(['a-wan-01', 'c-wan-01']);
		expect([...f.nodes]).toEqual(['transport:INET']);
		expect([...f.sites].sort()).toEqual(['A', 'C']);
	});

	it("is a tunnel's ends, a fabric's members, and a tenant's networks", () => {
		expect([...footprint(index, { kind: 'tunnel', id: 'GREY-A-C' }).devices]).toEqual([
			'a-acc-01',
			'c-acc-02'
		]);
		expect(footprint(index, { kind: 'fabric', id: 'DMVPN' }).sites).toEqual(
			new Set(['A', 'B', 'C'])
		);
		expect([...footprint(index, { kind: 'tenant', id: 'T1' }).nodes]).toEqual(['external:r1-c']);
	});

	it('is the members of a resource, inner resources included', () => {
		const t = structuredClone(layeredFixture);
		t.links = t.links.map((l) =>
			l.circuit?.circuit_id.a === 'NO-1' ? { ...l, enterprise_cid: { a: 'A-INET-01', z: null } } : l
		);
		const res = { tags: [], circuits: [], tunnels: [], fabrics: [], resources: [] };
		t.resources = [
			{ ...res, name: 'Access', circuits: ['A-INET-01'] },
			{ ...res, name: 'Cloud', tunnels: ['GREY-A-C'], resources: ['Access'] }
		];
		const f = footprint(indexTopology(t), { kind: 'resource', id: 'Cloud' });
		expect([...f.devices].sort()).toEqual(['a-acc-01', 'a-wan-01', 'c-acc-02']);
		expect([...f.links]).toEqual(['a-wan-01:GigabitEthernet0/0/0--transport:INET']);
		expect([...f.sites].sort()).toEqual(['A', 'C']);
	});

	it('is empty for a name not in the topology', () => {
		expect(footprint(index, { kind: 'network', id: 'gray' }).devices.size).toBe(0);
		expect(footprint(index, { kind: 'resource', id: 'gray' }).devices.size).toBe(0);
	});
});

describe('terms', () => {
	it("uses the organization's word where it has one", () => {
		const custom = indexTopology({ ...index.topology, terms: { tenant: 'Customer' } });
		expect([term(custom, 'tenant'), term(custom, 'tenant', true)]).toEqual([
			'Customer',
			'Customers'
		]);
		expect(termWords(custom, 'tenant')).toEqual(['Tenant', 'Customer']);
		expect(term(index, 'fabric')).toBe('Fabric');
		expect(termWords(index, 'fabric')).toEqual(['Fabric']);
	});
});
