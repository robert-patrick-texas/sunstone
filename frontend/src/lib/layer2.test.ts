import { describe, expect, it } from 'vitest';
import type { Link, Topology, Transport } from './api/topology.ts';
import {
	lagMembers,
	lagOf,
	macsecLinks,
	macsecOn,
	serviceText,
	showsText,
	transportService
} from './connections.ts';
import { hopsOf, linksBetween, shortestPaths } from './paths.ts';
import { search, topologyEntries } from './search.ts';
import { fixture } from './test-fixture.ts';
import { indexTopology } from './topology.ts';

/** Into a transport, for transit, showing our devices on the same service. */
function into(device: string, port: string, transport: string, root = false): Link {
	return {
		a: { device, interface: port },
		b: root ? { transport, role: 'root' } : { transport },
		speed_mbps: 1_000,
		kind: 'wan',
		circuit: { provider: 'Metro Co', circuit_id: { a: `${device}-1`, z: null }, type: 'carrier' },
		carries: [{ network: 'metro' }],
		edges: ['transit'],
		neighbors: ['far-end'],
		id: `${device}:${port}--transport:${transport}`
	};
}

const service = (name: string, kind: Transport['service']): Transport => ({
	name,
	kind: 'private-wan',
	network: 'metro',
	service: kind,
	technology: kind === 'e-tree' ? 'MPLS EVPN' : 'VPLS',
	tags: []
});

/**
 * The tiny topology, with two more branches, D and E, on an E-Tree rooted
 * at a-wan-01 alone; an E-LAN joining a-wan-01 and c-wan-01, with MACsec
 * across it; and the LAG between a-core-01 and a-acc-01 listed with a CID.
 */
function metro(): Topology {
	const topology = structuredClone(fixture);
	topology.sites.push(
		{ code: 'D', name: 'Branch D', lat: 30, lon: -97 },
		{ code: 'E', name: 'Branch E', lat: 31, lon: -97 }
	);
	topology.devices.push(
		{ name: 'd-wan-01', site: 'D', role: 'wan-edge' },
		{ name: 'e-wan-01', site: 'E', role: 'wan-edge' }
	);
	topology.transports.push(service('Tree', 'e-tree'), service('Lan', 'e-lan'));
	topology.links.push(
		into('a-wan-01', 'Gi0/0/5', 'Tree', true),
		into('d-wan-01', 'Gi0/0/5', 'Tree'),
		into('e-wan-01', 'Gi0/0/5', 'Tree'),
		into('a-wan-01', 'Gi0/0/6', 'Lan'),
		{
			...into('c-wan-01', 'Gi0/0/6', 'Lan'),
			circuit: {
				provider: 'Metro Co',
				circuit_id: { a: 'C-ELAN', z: null },
				type: 'carrier',
				service: 'e-access'
			}
		}
	);
	topology.tunnels.push({
		name: 'SEC-1',
		network: 'corp',
		rides: 'metro',
		kind: 'macsec',
		a: { device: 'a-wan-01', interface: 'Gi0/0/6' },
		b: { device: 'c-wan-01', interface: 'Gi0/0/6' },
		tags: [],
		edges: []
	});
	topology.lags.push({
		a: { device: 'a-core-01', interface: 'Port-channel1' },
		b: { device: 'a-acc-01', interface: 'Port-channel10' },
		enterprise_cid: { a: 'A-PO01', z: 'A-PO01' },
		id: 'a-acc-01:Port-channel10--a-core-01:Port-channel1'
	});
	return topology;
}

const LEAF_D = 'd-wan-01:Gi0/0/5--transport:Tree';
const ROOT = 'a-wan-01:Gi0/0/5--transport:Tree';

describe('E-Tree paths', () => {
	it('go from leaf to leaf through a root, as traffic does', () => {
		const index = indexTopology(metro());
		const path = shortestPaths(index, 'd-wan-01', 'e-wan-01');
		expect(path.hops).toBe(4);
		expect(path.listed).toEqual([
			['d-wan-01', 'transport:Tree', 'a-wan-01', 'transport:Tree', 'e-wan-01']
		]);
		// The views know only the transport, not each leaf's corner of it.
		expect([...path.devices.keys()]).toEqual([
			'e-wan-01',
			'transport:Tree',
			'a-wan-01',
			'd-wan-01'
		]);
		expect(linksBetween(index, path, 'd-wan-01', 'transport:Tree').map((l) => l.id)).toEqual([
			LEAF_D
		]);
		expect(linksBetween(index, path, 'transport:Tree', 'a-wan-01').map((l) => l.id)).toEqual([
			ROOT
		]);
	});

	it('cut a leaf off when no root is reached', () => {
		const topology = metro();
		topology.links = topology.links.filter((l) => l.id !== ROOT);
		const path = shortestPaths(indexTopology(topology), 'd-wan-01', 'e-wan-01');
		expect(path.hops).toBeNull();
	});

	it('join a leaf to its own corner, which only the roots reach', () => {
		const hops = hopsOf(indexTopology(metro()));
		const corner = `transport:Tree~${LEAF_D}`;
		expect(hops.get('d-wan-01')?.map((h) => h.to)).toEqual([corner]);
		expect(
			hops
				.get(corner)
				?.map((h) => h.to)
				.sort()
		).toEqual(['a-wan-01', 'd-wan-01']);
		expect(hops.get('transport:Tree')?.map((h) => h.to)).toEqual(['a-wan-01']);
	});
});

describe('layer-2 connections', () => {
	const topology = metro();
	const link = (id: string): Link => {
		const found = topology.links.find((l) => l.id === id);
		if (!found) throw new Error(id);
		return found;
	};

	it('say what a port shows, one or more', () => {
		expect(showsText(['far-end', 'provider'])).toBe("The provider's equipment and the far end");
		expect(showsText([])).toBe('Not said');
	});

	it('name the service a circuit is part of', () => {
		expect(transportService(service('Lan', 'e-lan'))).toBe('E-LAN · VPLS');
		expect(serviceText(topology, link(ROOT))).toBe('E-Tree · MPLS EVPN · root');
		expect(serviceText(topology, link(LEAF_D))).toBe(
			'E-Tree · MPLS EVPN · leaf: reaches the roots only'
		);
		expect(serviceText(topology, link('c-wan-01:Gi0/0/6--transport:Lan'))).toBe(
			'E-LAN · VPLS · over E-Access'
		);
		// A routed transport's circuit is part of no layer-2 service.
		const eline = structuredClone(link(ROOT));
		eline.b = { device: 'b-wan-01', interface: 'Gi0/0/5' };
		eline.circuit = { ...eline.circuit!, service: 'e-line', technology: 'VPWS' };
		expect(serviceText(topology, eline)).toBe('E-Line · VPWS');
	});

	it('find MACsec on a port, and the links it is carried on', () => {
		const [macsec] = topology.tunnels.filter((t) => t.kind === 'macsec');
		expect(macsecOn(topology, link('a-wan-01:Gi0/0/6--transport:Lan')).map((t) => t.name)).toEqual([
			'SEC-1'
		]);
		expect(macsecOn(topology, link(ROOT))).toEqual([]);
		expect(macsecLinks(topology, macsec!).map((l) => l.id)).toEqual([
			'a-wan-01:Gi0/0/6--transport:Lan',
			'c-wan-01:Gi0/0/6--transport:Lan'
		]);
	});

	it('find the port channel a link is a member of', () => {
		const member = topology.links.find((l) => l.a.lag === 'Port-channel1');
		const lag = member ? lagOf(topology, member) : null;
		expect(lag?.enterprise_cid?.a).toBe('A-PO01');
		expect(lag ? lagMembers(topology, lag).length : 0).toBe(2);
		expect(lagOf(topology, link(ROOT))).toBeNull();
	});
});

describe('search', () => {
	const index = indexTopology(metro());
	const entries = topologyEntries(index);
	const found = (query: string) =>
		search(query, [entries]).flatMap((g) => g.entries.map((e) => e.label));

	it('finds a port channel by its own CID, with all its members', () => {
		const [group] = search('A-PO01', [entries]);
		expect(group?.entries[0]?.label).toBe('Port channel A-PO01');
		expect(group?.entries[0]?.target).toEqual({
			kind: 'item',
			item: {
				kind: 'links',
				ids: fixture.links.filter((l) => l.a.lag === 'Port-channel1').map((l) => l.id)
			}
		});
	});

	it("finds a one-member channel's link once, by the channel's CID", () => {
		const topology = metro();
		const [member] = topology.links.filter((l) => l.a.lag === 'Port-channel1');
		topology.links = topology.links.filter((l) => l.a.lag !== 'Port-channel1' || l === member);
		const results = search('A-PO01', [topologyEntries(indexTopology(topology))]).flatMap(
			(g) => g.entries
		);
		expect(results.map((e) => e.target)).toEqual([
			{ kind: 'item', item: { kind: 'links', ids: [member!.id] } }
		]);
	});

	it('finds transports, circuits, and MACsec by their service', () => {
		expect(found('e-lan')).toContain('Lan');
		expect(found('vpls')).toContain('Lan');
		expect(found('e-access')).toContain('Circuit C-ELAN');
		expect(found('macsec')).toContain('SEC-1');
	});
});
