import { describe, expect, it } from 'vitest';
import type { Topology } from '../api/topology.ts';
import { STATUS_COLOR } from '../status.ts';
import { layeredFixture, layeredIndex } from '../test-fixture.ts';
import { indexTopology } from '../topology.ts';
import { COLOR, DEPTH_COLOR } from '../theme.ts';
import { logicalGraph } from './graph.ts';

const index = layeredIndex();

describe('logicalGraph', () => {
	it('draws a network with what it rides faintly under it', () => {
		const g = logicalGraph(index, ['grey'], new Set());
		expect(g.shown).toEqual(['grey']);
		expect(g.under.sort()).toEqual(['black', 'blue']);
		const grey = g.edges.find((e) => e.tunnels?.includes('GREY-A-C'));
		expect(grey).toMatchObject({
			kind: 'tunnel',
			network: 'grey',
			color: DEPTH_COLOR[1],
			source: 'site:A',
			target: 'site:C'
		});
		expect(grey?.beneath).toBeUndefined();
		const blue = g.edges.find((e) => e.tunnels?.includes('BLUE-A-C'));
		expect(blue?.beneath).toBe(true);
	});

	it('keeps edges of different networks between the same nodes apart', () => {
		const g = logicalGraph(index, ['grey', 'blue'], new Set());
		const between = g.edges.filter((e) => e.source === 'site:A' && e.target === 'site:C');
		expect(between.map((e) => e.network).sort()).toEqual(['blue', 'grey']);
	});

	it('draws what a network rides only at its own sites', () => {
		// Red is only at C: the circuit at A into the Internet is not brought forward.
		const g = logicalGraph(index, ['red'], new Set());
		expect(g.nodes.map((n) => n.id).sort()).toEqual(['external:r1-c', 'site:C', 'transport:INET']);
		expect(g.edges.every((e) => e.source !== 'site:A' && e.target !== 'site:A')).toBe(true);
	});

	it('gives a fabric a node of its own that its members join, hubs marked', () => {
		const g = logicalGraph(index, ['corp'], new Set());
		expect(g.nodes.find((n) => n.id === 'fabric:DMVPN')).toMatchObject({ kind: 'fabric' });
		const joins = g.edges.filter((e) => e.fabric === 'DMVPN');
		expect(joins.map((e) => e.label ?? '').sort()).toEqual(['', 'hub', 'hub']);
	});

	it('shows every network when none is chosen, and services across a transport drawn', () => {
		const g = logicalGraph(index, [], new Set());
		expect(g.shown.sort()).toEqual(['black', 'blue', 'corp', 'grey', 'red']);
		expect(g.under).toEqual([]);
		expect(g.edges.find((e) => e.kind === 'reach')).toMatchObject({
			source: 'external:Nimbus Cloud',
			target: 'transport:INET'
		});
	});

	it('draws tunnels spokes built to each other now, apart from the fixed ones', () => {
		const topology = structuredClone(layeredFixture);
		topology.fabrics[0]!.members.push({
			device: 'b-core-01',
			interface: 'Tunnel100',
			role: 'spoke'
		});
		const spokes = indexTopology(topology);
		const built = [{ tunnel: 'DMVPN:b-core-01~c-wan-01', network: 'corp' }];
		const g = logicalGraph(spokes, ['corp'], new Set(), true, built);
		expect(g.edges.find((e) => e.dynamic)).toMatchObject({
			id: 'corp|tunnel|site:B~site:C|on demand',
			kind: 'tunnel',
			fabric: 'DMVPN',
			tunnels: ['DMVPN:b-core-01~c-wan-01']
		});
		// Only for the networks shown.
		expect(
			logicalGraph(spokes, ['grey'], new Set(), true, built).edges.some((e) => e.dynamic)
		).toBe(false);
	});

	it('shows the devices in the networks at an expanded site', () => {
		const g = logicalGraph(index, ['grey'], new Set(['C']));
		const atC = g.nodes.filter((n) => n.site === 'C').map((n) => n.id);
		expect(atC).toEqual(['site:C', 'c-wan-01', 'c-acc-02']);
	});
});

describe('resources in the logical graph', () => {
	// The Internet circuits at A and C (in black, the Internet's network) get
	// enterprise CIDs; resources hold them, a tunnel, a fabric, or another resource.
	const t: Topology = structuredClone(layeredFixture);
	t.links = t.links.map((l) =>
		l.circuit?.circuit_id.a === 'NO-1'
			? { ...l, enterprise_cid: { a: 'A-INET-01', z: null } }
			: l.circuit?.circuit_id.a === 'NO-2'
				? { ...l, enterprise_cid: { a: 'C-INET-01', z: null } }
				: l
	);
	const res = { tags: [], circuits: [], tunnels: [], fabrics: [], resources: [] };
	t.resources = [
		{ ...res, name: 'Access', circuits: ['A-INET-01', 'C-INET-01'] },
		{ ...res, name: 'Grey', tunnels: ['GREY-A-C'] },
		{ ...res, name: 'Corp', fabrics: ['DMVPN'] },
		{ ...res, name: 'Cloud', resources: ['Access'] },
		{ ...res, name: 'Nowhere', circuits: ['nothing'] }
	];
	const index = indexTopology(t);
	const resources = (g: ReturnType<typeof logicalGraph>) =>
		g.nodes.filter((n) => n.kind === 'resource').map((n) => n.id);
	const members = (g: ReturnType<typeof logicalGraph>) =>
		g.edges.filter((e) => e.kind === 'member').map((e) => `${e.source} > ${e.target}`);

	it('shows a resource when any of its members is drawn, inner resources included', () => {
		const g = logicalGraph(index, ['black'], new Set());
		expect(resources(g)).toEqual(['resource:Access', 'resource:Cloud']);
		expect(members(g)).toEqual([
			'resource:Access > site:A',
			'resource:Access > site:C',
			'resource:Cloud > resource:Access'
		]);
		expect(g.nodes.find((n) => n.id === 'resource:Access')).toMatchObject({
			kind: 'resource',
			label: 'Access',
			tint: COLOR.muted
		});
	});

	it("joins a circuit's device at an expanded site, a tunnel's ends, and a fabric's node", () => {
		expect(members(logicalGraph(index, ['black'], new Set(['A'])))).toContain(
			'resource:Access > a-wan-01'
		);
		expect(members(logicalGraph(index, ['grey'], new Set(['C']), false))).toEqual([
			'resource:Grey > site:A',
			'resource:Grey > c-acc-02'
		]);
		const corp = logicalGraph(index, ['corp'], new Set(), false);
		expect(resources(corp)).toEqual(['resource:Corp']);
		expect(members(corp)).toEqual(['resource:Corp > fabric:DMVPN']);
	});

	it('colors resources by status, with its glyph, and leaves the rest neutral', () => {
		const g = logicalGraph(
			index,
			['black'],
			new Set(),
			true,
			[],
			[{ name: 'Access', status: 'offline' }]
		);
		const node = (id: string) => g.nodes.find((n) => n.id === id);
		expect(node('resource:Access')).toMatchObject({
			label: '× Access',
			tint: STATUS_COLOR.offline
		});
		expect(node('resource:Cloud')?.tint).toBe(COLOR.muted);
	});
});
