import { describe, expect, it } from 'vitest';
import { fixtureIndex } from './test-fixture.ts';
import {
	DEFAULT_DWELL_S,
	fromQuery,
	readable,
	readItem,
	toQuery,
	writeItem,
	type Shared
} from './url.ts';

const CIRCUIT = 'a-wan-01:Gi1/0/1--c-wan-01:Gi1/0/1';

const OPENING: Shared = {
	view: 'geo',
	selection: null,
	live: false,
	at: null,
	path: null,
	whatIf: [],
	problem: null,
	topo: { scope: 'network', hops: 2, layout: 'force', grouped: true, center: null },
	expanded: [],
	camera: null,
	wall: null
};

describe('toQuery and fromQuery', () => {
	const index = fixtureIndex();

	it('leave out everything that is as Sunstone opens', () => {
		expect(toQuery(OPENING, index).toString()).toBe('');
		expect(fromQuery(new URLSearchParams(''), index)).toEqual({});
	});

	it('carry a replayed problem in a topology neighborhood there and back', () => {
		const shared: Shared = {
			...OPENING,
			view: 'topology',
			selection: { kind: 'links', ids: [CIRCUIT] },
			live: true,
			at: '2026-10-27T14:05:00.000Z',
			problem: `down:${CIRCUIT}`,
			path: { from: 'a-acc-01', to: 'c-acc-02' },
			whatIf: [
				{ kind: 'site', id: 'C' },
				{ kind: 'device', id: 'b-wan-01' }
			],
			topo: {
				scope: 'neighborhood',
				hops: 3,
				layout: 'radial',
				grouped: false,
				center: { kind: 'device', id: 'c-wan-01' }
			},
			expanded: ['A', 'C'],
			wall: { dwell: 30 }
		};
		const q = toQuery(shared, index);
		expect(q.get('select')).toBe(`links:${CIRCUIT}`);
		expect(q.getAll('fail')).toEqual(['site:C', 'device:b-wan-01']);
		expect(fromQuery(new URLSearchParams(q.toString()), index)).toEqual({
			view: 'topology',
			selection: shared.selection,
			live: true,
			at: shared.at,
			problem: shared.problem,
			path: shared.path,
			whatIf: shared.whatIf,
			topo: shared.topo,
			expanded: ['A', 'C'],
			wall: { dwell: 30 }
		});
	});

	it('write every site expanded as all, and the map camera only for the map', () => {
		const all = { ...OPENING, view: 'hierarchy' as const, expanded: ['A', 'B', 'C'] };
		expect(toQuery(all, index).get('expanded')).toBe('all');
		expect(fromQuery(new URLSearchParams('expanded=all'), index).expanded).toEqual(['A', 'B', 'C']);
		const map = { ...OPENING, camera: { lon: -96.79701, lat: 32.77671, zoom: 13.456 } };
		expect(toQuery(map, index).get('map')).toBe('-96.7970,32.7767,13.46');
		expect(toQuery({ ...map, view: 'hierarchy' }, index).has('map')).toBe(false);
	});

	it('skip what no longer matches the network, and keep the rest', () => {
		const q = new URLSearchParams(
			'view=sideways&select=device:gone-01&fail=site:ZZZ&fail=device:c-wan-01&hops=9&dwell=1&wall=1&map=0,95,3&from=a-wan-01&to=gone'
		);
		expect(fromQuery(q, index)).toEqual({
			selection: null,
			whatIf: [{ kind: 'device', id: 'c-wan-01' }],
			topo: { scope: 'network', hops: 2, layout: 'force', grouped: true, center: null },
			wall: { dwell: DEFAULT_DWELL_S }
		});
	});
});

describe('writeItem and readItem', () => {
	it('keep only the links that exist', () => {
		const index = fixtureIndex();
		expect(writeItem({ kind: 'site', id: 'A' })).toBe('site:A');
		expect(readItem(`links:${CIRCUIT} nope`, index)).toEqual({ kind: 'links', ids: [CIRCUIT] });
		expect(readItem('links:nope', index)).toBeNull();
		expect(readItem('router:a-wan-01', index)).toBeNull();
	});
});

describe('readable', () => {
	it('leaves colons, commas, and slashes unescaped, and still reads back', () => {
		const index = fixtureIndex();
		const q = toQuery({ ...OPENING, selection: { kind: 'links', ids: [CIRCUIT] } }, index);
		const text = readable(q);
		expect(text).toBe('select=links:a-wan-01:Gi1/0/1--c-wan-01:Gi1/0/1');
		expect(fromQuery(new URLSearchParams(text), index).selection).toEqual({
			kind: 'links',
			ids: [CIRCUIT]
		});
	});
});
