import { describe, expect, it } from 'vitest';
import { fixture, fixtureIndex, link } from '../test-fixture.ts';
import { indexTopology } from '../topology.ts';
import { buildHierarchy, siteLevels, siteNodeId, type HNode } from './layout.ts';

const byId = (nodes: HNode[]) => new Map(nodes.map((n) => [n.id, n]));

describe('siteLevels', () => {
	it('puts sites with a core tier on top and branches below', () => {
		expect(siteLevels(fixtureIndex())).toEqual([['A', 'B'], ['C']]);
	});
});

describe('buildHierarchy, all collapsed', () => {
	const graph = buildHierarchy(fixtureIndex(), new Set());

	it('draws one box per site, hubs above the branch', () => {
		const nodes = byId(graph.nodes);
		expect(graph.nodes.every((n) => n.kind === 'site')).toBe(true);
		expect(nodes.get('site:A')?.y).toBe(nodes.get('site:B')?.y);
		expect(nodes.get('site:A')?.y ?? 0).toBeLessThan(nodes.get('site:C')?.y ?? 0);
	});

	it('merges links into one edge per site pair, with no intra-site loops', () => {
		const edges = Object.fromEntries(graph.edges.map((e) => [e.id, e.linkIds.length]));
		expect(edges).toEqual({ 'site:A~site:B': 1, 'site:A~site:C': 1, 'site:B~site:C': 1 });
	});
});

describe('buildHierarchy, one site expanded', () => {
	const graph = buildHierarchy(fixtureIndex(), new Set(['A']));
	const nodes = byId(graph.nodes);

	it('draws the site as a frame with its devices in tier rows', () => {
		expect(nodes.get(siteNodeId('A'))?.kind).toBe('frame');
		expect(nodes.get('a-acc-01')?.parent).toBe('site:A');
		const y = (id: string) => nodes.get(id)?.y ?? NaN;
		expect(y('a-wan-01')).toBeLessThan(y('a-core-01'));
		expect(y('a-core-01')).toBeLessThan(y('a-acc-01'));
	});

	it('labels a LAG with its bundle and member count at each end', () => {
		const lag = graph.edges.find((e) => e.id === 'a-acc-01~a-core-01');
		expect(lag?.linkIds).toHaveLength(2);
		expect([lag?.sourceLabel, lag?.targetLabel]).toEqual(['Po10 ×2', 'Po1 ×2']);
	});

	it('labels the device end of an edge to a collapsed site only', () => {
		const edge = graph.edges.find((e) => e.id === 'a-wan-01~site:B');
		expect([edge?.sourceLabel, edge?.targetLabel]).toEqual(['Hu1/0/2', '']);
	});
});

describe('buildHierarchy, all expanded', () => {
	it('keeps frames and devices from overlapping', () => {
		const graph = buildHierarchy(fixtureIndex(), new Set(['A', 'B', 'C']));
		const frames = graph.nodes.filter((n) => n.kind === 'frame');
		for (const [i, p] of frames.entries()) {
			for (const q of frames.slice(i + 1)) {
				const apartX = Math.abs(p.x - q.x) >= ((p.w ?? 0) + (q.w ?? 0)) / 2;
				const apartY = Math.abs(p.y - q.y) >= ((p.h ?? 0) + (q.h ?? 0)) / 2;
				expect(apartX || apartY, `${p.id} overlaps ${q.id}`).toBe(true);
			}
		}
		const points = graph.nodes.filter((n) => n.kind === 'device').map((n) => `${n.x},${n.y}`);
		expect(new Set(points).size).toBe(points.length);
	});
});

describe('buildHierarchy, many sites expanded', () => {
	it('wraps sites into a screen-shaped area instead of a tall column', () => {
		const topology = structuredClone(fixture);
		for (let i = 0; i < 40; i++) {
			const code = `S${i}`;
			topology.sites.push({ code, name: code, lat: 30, lon: -90 });
			topology.devices.push({ name: `${code}-wan`, site: code, role: 'wan-edge' });
			for (let n = 1; n <= 14; n++) {
				topology.devices.push({ name: `${code}-acc-${n}`, site: code, role: 'access' });
				topology.links.push(link(`${code}-wan:Te1/0/${n}`, `${code}-acc-${n}:Te1/0/49`));
			}
			topology.links.push(link(`${code}-wan:Gi0/0/0`, `a-wan-01:Gi0/1/${i}`, 1_000));
		}
		const sites = topology.sites.map((s) => s.code);
		const { nodes } = buildHierarchy(indexTopology(topology), new Set(sites));
		const xs = nodes.map((n) => n.x);
		const ys = nodes.map((n) => n.y);
		const aspect = (Math.max(...xs) - Math.min(...xs)) / (Math.max(...ys) - Math.min(...ys));
		expect(aspect).toBeGreaterThan(1);
		expect(aspect).toBeLessThan(3);
	});
});
