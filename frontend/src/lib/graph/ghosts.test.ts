import { describe, expect, it } from 'vitest';
import type { SeenLink } from '../api/discovery.ts';
import { devicePositions, seenFeatures } from '../geo/geojson.ts';
import { fixtureIndex } from '../test-fixture.ts';
import { ghostElements } from './model.ts';

const SEEN: SeenLink[] = [
	{
		id: 'seen:c-acc-01:Gi1/0/48--c-acc-02:Gi1/0/48',
		a: { device: 'c-acc-01', interface: 'GigabitEthernet1/0/48' },
		b: { device: 'c-acc-02', interface: 'GigabitEthernet1/0/48' },
		known: true,
		finding: 'undocumented:x'
	},
	{
		id: 'seen:c-acc-01:Gi1/0/47--lab-sw-01:Gi0/1',
		a: { device: 'c-acc-01', interface: 'GigabitEthernet1/0/47' },
		b: { device: 'lab-sw-01', interface: 'GigabitEthernet0/1' },
		known: false,
		finding: 'unknown-device:y',
		platform: 'WS-C2960X-24TS'
	}
];

describe('ghostElements', () => {
	const at = () => ({ x: 100, y: 200 });

	it('draws seen cables between device nodes, and unknown neighbors beside theirs', () => {
		const elements = ghostElements(SEEN, (d) => d, at);
		expect(elements.map((e) => [e.group, e.data['source'] ?? e.data['label']])).toEqual([
			['edges', 'c-acc-01'],
			['nodes', 'lab-sw-01'],
			['edges', 'c-acc-01']
		]);
		const [cable, lab] = elements;
		expect(cable?.data['target']).toBe('c-acc-02');
		expect(cable?.data['sourceLabel']).toBe('Gi1/0/48');
		expect(lab?.position).toEqual({ x: 170, y: 155 });
		expect(elements.every((e) => e.classes === 'ghost')).toBe(true);
	});

	it('leaves out cables inside one collapsed site, and devices not drawn', () => {
		const collapsed = ghostElements(SEEN, () => 'site:C', at);
		expect(collapsed.filter((e) => e.group === 'edges' && e.data['target'] === 'site:C')).toEqual(
			[]
		);
		expect(ghostElements(SEEN, () => null, at)).toEqual([]);
	});
});

describe('seenFeatures', () => {
	it('draws a line per cable and a point beyond its device for an unknown neighbor', () => {
		const index = fixtureIndex();
		const positions = devicePositions(index);
		const { features } = seenFeatures(index, SEEN, positions);
		expect(features.map((f) => f.geometry.type)).toEqual(['LineString', 'Point', 'LineString']);
		expect(features[1]?.properties).toMatchObject({ device: 'c-acc-01', label: 'lab-sw-01' });
		const site = index.sites.get('C')!;
		const [x, y] = (features[1]?.geometry as GeoJSON.Point).coordinates as [number, number];
		const [dx, dy] = positions.get('c-acc-01')!;
		// Further from the middle of the site than its device.
		expect(Math.hypot(x - site.lon, y - site.lat)).toBeGreaterThan(
			Math.hypot(dx - site.lon, dy - site.lat)
		);
	});
});
