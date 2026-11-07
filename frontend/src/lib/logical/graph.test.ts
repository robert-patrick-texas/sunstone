import { describe, expect, it } from 'vitest';
import { layeredIndex } from '../test-fixture.ts';
import { DEPTH_COLOR } from '../theme.ts';
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

	it('shows the devices in the networks at an expanded site', () => {
		const g = logicalGraph(index, ['grey'], new Set(['C']));
		const atC = g.nodes.filter((n) => n.site === 'C').map((n) => n.id);
		expect(atC).toEqual(['site:C', 'c-wan-01', 'c-acc-02']);
	});
});
