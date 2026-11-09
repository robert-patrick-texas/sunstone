import { afterEach, describe, expect, it } from 'vitest';
import type { OverrideNow, TargetKind } from '../api/overrides.ts';
import type { Topology } from '../api/topology.ts';
import {
	deviceFeatures,
	devicePositions,
	linkFeatures,
	networkArcs,
	resourceFeatures,
	resourcePositions,
	siteFeatures,
	sitePairs
} from '../geo/geojson.ts';
import { buildHierarchy } from '../hierarchy/layout.ts';
import { logicalGraph } from '../logical/graph.ts';
import { overrides, target } from '../overrides.svelte.ts';
import { fixtureIndex, layeredFixture, layeredIndex } from '../test-fixture.ts';
import { networkGraph, neighborhoodGraph } from '../topo/graph.ts';
import { neighborhood } from '../topo/neighborhood.ts';
import { indexTopology } from '../topology.ts';
import { drawnLinks, hiddenKey, nodeLabel } from './drawn.ts';
import { deviceNode, externalNode } from './model.ts';

function made(kind: OverrideNow['kind'], of: TargetKind, id: string, value = ''): OverrideNow {
	return {
		id: `${kind}:${of}:${id}`,
		target: target(of, id),
		kind,
		value: value || null,
		note: '',
		by: 'Pat',
		at: '2026-11-08T12:00:00Z',
		state: 'active'
	};
}

const hide = (of: TargetKind, id: string) => made('hide-map', of, id);
const ids = (items: { id: string }[]) => items.map((n) => n.id);

afterEach(() => {
	overrides.list = [];
	overrides.showHidden = false;
});

describe('hidden from the map', () => {
	it('leaves a site, its devices, and their links off the map, until shown anyway', () => {
		const index = fixtureIndex();
		const positions = devicePositions(index);
		const drawn = () => ({
			sites: siteFeatures(index).features.map((f) => f.properties?.['code']),
			devices: deviceFeatures(index, positions).features.map((f) => f.properties?.['name']),
			pairs: sitePairs(index).map((p) => p.key),
			links: linkFeatures(drawnLinks(index), positions).features.length
		});
		const all = drawn();
		overrides.list = [hide('site', 'C')];
		expect(drawn()).toEqual({
			sites: ['A', 'B'],
			devices: ['a-wan-01', 'a-core-01', 'a-acc-01', 'b-wan-01', 'b-core-01'],
			pairs: ['A|B'],
			links: 5
		});
		overrides.showHidden = true;
		expect(drawn()).toEqual(all);
	});

	it('leaves a site out of the hierarchy and the topology', () => {
		const index = fixtureIndex();
		overrides.list = [hide('site', 'C')];
		const hierarchy = buildHierarchy(index, new Set());
		expect(ids(hierarchy.nodes)).toEqual(['site:A', 'site:B']);
		expect(ids(hierarchy.edges)).toEqual(['site:A~site:B']);
		const topology = networkGraph(index, new Set(), false);
		expect(ids(topology.nodes)).toEqual(['site:A', 'site:B']);
		expect(ids(topology.edges)).toEqual(['site:A~site:B']);
	});

	it('leaves a device and its links out of an expanded site and a neighborhood', () => {
		const index = fixtureIndex();
		overrides.list = [hide('device', 'c-acc-01')];
		const { nodes, edges } = networkGraph(index, new Set(['C']), false);
		expect(ids(nodes)).not.toContain('c-acc-01');
		expect(edges.some((e) => e.source === 'c-acc-01' || e.target === 'c-acc-01')).toBe(false);
		const hood = neighborhoodGraph(index, neighborhood(index, ['c-wan-01'], 1, 100), false);
		expect(ids(hood.nodes).sort()).toEqual(['a-wan-01', 'b-wan-01', 'c-acc-02', 'c-wan-01']);
	});

	it('leaves out a transport with its circuits, and an external node with its links', () => {
		const index = layeredIndex();
		const beyond = (nodes: { kind: string }[]) =>
			nodes.filter((n) => n.kind === 'transport' || n.kind === 'external');
		expect(beyond(networkGraph(index, new Set(), false).nodes)).toHaveLength(2);
		overrides.list = [hide('transport', 'INET'), hide('external', 'r1-c')];
		expect(drawnLinks(index).some((l) => !('device' in l.b))).toBe(false);
		expect(siteFeatures(index).features.some((f) => f.properties?.['transports'])).toBe(false);
		expect(beyond(networkGraph(index, new Set(), false).nodes)).toEqual([]);
		expect(beyond(buildHierarchy(index, new Set()).nodes)).toEqual([]);
		expect(beyond(logicalGraph(index, [], new Set()).nodes)).toEqual([]);
	});

	it('leaves out a tunnel and a fabric, on the map and in the logical view', () => {
		const index = layeredIndex();
		expect(networkArcs(index, ['blue', 'corp']).features).not.toEqual([]);
		overrides.list = [hide('tunnel', 'BLUE-A-C'), hide('fabric', 'DMVPN')];
		expect(networkArcs(index, ['blue', 'corp']).features).toEqual([]);
		const g = logicalGraph(index, [], new Set());
		expect(ids(g.nodes)).not.toContain('fabric:DMVPN');
		expect(g.edges.some((e) => e.tunnels?.includes('BLUE-A-C') || e.fabric === 'DMVPN')).toBe(
			false
		);
	});

	it('leaves out a resource, and its leader to a site hidden', () => {
		const t: Topology = structuredClone(layeredFixture);
		t.resources = [
			{ name: 'Blue', circuits: [], resources: [], tunnels: ['BLUE-A-C'], fabrics: [], tags: [] }
		];
		const index = indexTopology(t);
		const map = () =>
			resourceFeatures(index, resourcePositions(index)).features.map((f) => f.properties?.['id']);
		expect(map().sort()).toEqual(['Blue', 'Blue|A', 'Blue|C']);
		overrides.list = [hide('site', 'C')];
		expect(map().sort()).toEqual(['Blue', 'Blue|A']);
		overrides.list = [hide('resource', 'Blue')];
		expect(map()).toEqual([]);
		expect(ids(logicalGraph(index, [], new Set()).nodes)).not.toContain('resource:Blue');
	});

	it('keys layouts by what is hidden, and by nothing while it is shown anyway', () => {
		expect(hiddenKey()).toBe('');
		overrides.list = [hide('site', 'C'), hide('device', 'a-acc-01')];
		expect(hiddenKey()).toBe('device:a-acc-01,site:C');
		overrides.showHidden = true;
		expect(hiddenKey()).toBe('');
	});
});

describe('names shown', () => {
	it('labels a renamed device and external node by their new names, keyed as before', () => {
		const index = layeredIndex();
		overrides.list = [
			made('rename', 'device', 'c-acc-01', 'C-ACC-ONE'),
			made('rename', 'external', 'r1-c', 'BRV-IAD-ENC01')
		];
		const feature = deviceFeatures(index, devicePositions(index)).features.find(
			(f) => f.properties?.['name'] === 'c-acc-01'
		);
		expect(feature?.properties?.['label']).toBe('C-ACC-ONE');
		const device = deviceNode(index.devices.get('c-acc-01')!, false);
		expect([device.id, nodeLabel(device)]).toEqual(['c-acc-01', 'C-ACC-ONE']);
		const external = externalNode(index.externals.get('r1-c')!);
		expect([external.id, nodeLabel(external)]).toEqual(['external:r1-c', 'BRV-IAD-ENC01']);
	});
});
