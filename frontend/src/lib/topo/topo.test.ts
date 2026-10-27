import { describe, expect, it } from 'vitest';
import { fixtureIndex } from '../test-fixture.ts';
import { neighborhoodGraph, networkGraph, radialRoots } from './graph.ts';
import { layoutPositions, sitewisePositions } from './layouts.ts';
import { neighborhood, seedsOf } from './neighborhood.ts';

describe('seedsOf', () => {
	const index = fixtureIndex();

	it('starts from a device, every device of a site, or both ends of links', () => {
		expect(seedsOf(index, { kind: 'device', id: 'c-wan-01' })).toEqual(['c-wan-01']);
		expect(seedsOf(index, { kind: 'site', id: 'C' })).toEqual(['c-wan-01', 'c-acc-01', 'c-acc-02']);
		expect(seedsOf(index, { kind: 'links', ids: ['c-acc-01:Te1/0/49--c-wan-01:Te1/0/1'] })).toEqual(
			['c-wan-01', 'c-acc-01']
		);
	});

	it('is empty for nothing selected or an unknown device', () => {
		expect(seedsOf(index, null)).toEqual([]);
		expect(seedsOf(index, { kind: 'device', id: 'nope' })).toEqual([]);
	});
});

describe('neighborhood', () => {
	const index = fixtureIndex();

	it('records each device at its hop distance', () => {
		const hood = neighborhood(index, ['c-acc-01'], 2, 100);
		expect(Object.fromEntries(hood.hops)).toEqual({
			'c-acc-01': 0,
			'c-wan-01': 1,
			'a-wan-01': 2,
			'b-wan-01': 2,
			'c-acc-02': 2
		});
		expect([hood.reached, hood.cut]).toEqual([2, 0]);
	});

	it('stops early when the network runs out', () => {
		const hood = neighborhood(index, ['c-acc-01'], 9, 100);
		expect(hood.hops.size).toBe(index.topology.devices.length);
		expect(hood.reached).toBeLessThan(9);
	});

	it('leaves out a whole hop that would pass the limit, and says how big it was', () => {
		const hood = neighborhood(index, ['c-acc-01'], 2, 4);
		expect([...hood.hops.keys()]).toEqual(['c-acc-01', 'c-wan-01']);
		expect([hood.reached, hood.cut]).toEqual([1, 3]);
	});
});

describe('networkGraph', () => {
	it('draws collapsed sites as boxes and expanded sites as devices', () => {
		const { nodes, edges } = networkGraph(fixtureIndex(), new Set(['C']), true);
		expect(nodes.map((n) => n.id)).toEqual([
			'site:A',
			'site:B',
			'site:C',
			'c-wan-01',
			'c-acc-01',
			'c-acc-02'
		]);
		expect(nodes.find((n) => n.id === 'c-acc-01')?.parent).toBe('site:C');
		expect(edges.map((e) => e.id).sort()).toEqual([
			'c-acc-01~c-wan-01',
			'c-acc-02~c-wan-01',
			'c-wan-01~site:A',
			'c-wan-01~site:B',
			'site:A~site:B'
		]);
	});

	it('leaves devices unframed when grouping is off', () => {
		const { nodes } = networkGraph(fixtureIndex(), new Set(['C']), false);
		expect(nodes.some((n) => n.kind === 'frame')).toBe(false);
		expect(nodes.find((n) => n.id === 'c-acc-01')?.parent).toBeUndefined();
	});
});

describe('neighborhoodGraph', () => {
	const index = fixtureIndex();
	const hood = neighborhood(index, ['c-acc-01'], 1, 100);

	it('keeps only links among the included devices', () => {
		const { nodes, edges } = neighborhoodGraph(index, hood, false);
		expect(nodes.map((n) => [n.id, n.hop])).toEqual([
			['c-acc-01', 0],
			['c-wan-01', 1]
		]);
		expect(edges.map((e) => [e.id, e.sourceLabel, e.targetLabel])).toEqual([
			['c-acc-01~c-wan-01', 'Te1/0/49', 'Te1/0/1']
		]);
	});

	it('adds a frame for each site the neighborhood touches when grouped', () => {
		const { nodes } = neighborhoodGraph(index, neighborhood(index, ['c-wan-01'], 1, 100), true);
		expect(nodes.filter((n) => n.kind === 'frame').map((n) => n.id)).toEqual([
			'site:C',
			'site:A',
			'site:B'
		]);
	});
});

describe('radialRoots', () => {
	const index = fixtureIndex();

	it('starts from the neighborhood center', () => {
		const { nodes } = neighborhoodGraph(index, neighborhood(index, ['c-acc-01'], 2, 100), false);
		expect(radialRoots(index, nodes)).toEqual(['c-acc-01']);
	});

	it('starts the whole network from the top-level sites, at their top tier when expanded', () => {
		const { nodes } = networkGraph(index, new Set(['A']), false);
		expect(radialRoots(index, nodes)).toEqual(['a-wan-01', 'site:B']);
	});
});

describe('sitewisePositions', () => {
	it('places every device, keeping each site in its own area', () => {
		const index = fixtureIndex();
		const graph = networkGraph(index, new Set(['A', 'B', 'C']), true);
		const positions = sitewisePositions(graph);
		const devices = graph.nodes.filter((n) => n.kind === 'device');
		expect(devices.every((n) => positions.has(n.id))).toBe(true);
		const box = (site: string) => {
			const points = devices.filter((n) => n.site === site).map((n) => positions.get(n.id));
			const xs = points.map((p) => p?.x ?? NaN);
			const ys = points.map((p) => p?.y ?? NaN);
			return { x1: Math.min(...xs), x2: Math.max(...xs), y1: Math.min(...ys), y2: Math.max(...ys) };
		};
		const sites = ['A', 'B', 'C'].map(box);
		for (const [i, p] of sites.entries()) {
			for (const q of sites.slice(i + 1)) {
				const apart = p.x2 < q.x1 || q.x2 < p.x1 || p.y2 < q.y1 || q.y2 < p.y1;
				expect(apart).toBe(true);
			}
		}
	});
});

describe('layoutPositions', () => {
	const index = fixtureIndex();

	it('places every device and site box, and leaves frames to follow', () => {
		const graph = networkGraph(index, new Set(['A', 'C']), true);
		const positions = layoutPositions({ ...graph, kind: 'force', roots: [] });
		const placed = graph.nodes.filter((n) => n.kind !== 'frame').map((n) => n.id);
		expect([...positions.keys()].sort()).toEqual(placed.sort());
		const distinct = new Set(
			[...positions.values()].map((p) => `${p.x.toFixed(0)},${p.y.toFixed(0)}`)
		);
		expect(distinct.size).toBe(positions.size);
	});

	it('puts the roots of a layered layout above everything else', () => {
		const graph = networkGraph(index, new Set(['A', 'B', 'C']), false);
		const positions = layoutPositions({ ...graph, kind: 'layered', roots: ['a-core-01'] });
		const top = positions.get('a-core-01')?.y ?? Infinity;
		for (const [id, p] of positions) if (id !== 'a-core-01') expect(p.y).toBeGreaterThan(top);
	});

	it('adjusts given positions rather than starting over', () => {
		const graph = networkGraph(index, new Set(['A', 'B', 'C']), false);
		const first = layoutPositions({ ...graph, kind: 'force', roots: [] });
		const again = layoutPositions({ ...graph, kind: 'force', roots: [], start: first });
		const moved = [...first].map(([id, p]) => {
			const q = again.get(id) ?? p;
			return Math.hypot(p.x - q.x, p.y - q.y);
		});
		const xs = [...first.values()].map((p) => p.x);
		const ys = [...first.values()].map((p) => p.y);
		const extent = Math.hypot(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys));
		// On average, nodes move a small part of the picture's size.
		const mean = moved.reduce((a, b) => a + b, 0) / moved.length;
		expect(mean).toBeLessThan(extent / 4);
	});
});
