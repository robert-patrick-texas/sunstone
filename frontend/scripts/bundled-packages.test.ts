import { describe, expect, it } from 'vitest';
import { packageOf } from './bundled-packages.ts';

describe('packageOf', () => {
	it('names the package a bundled module came from', () => {
		expect(packageOf('/w/node_modules/maplibre-gl/dist/maplibre-gl.js')).toBe('maplibre-gl');
		expect(packageOf('/w/node_modules/@sveltejs/kit/src/runtime/client.js?v=1')).toBe(
			'@sveltejs/kit'
		);
		expect(packageOf('/w/node_modules/a/node_modules/b/index.js')).toBe('b');
		expect(packageOf('/w/src/lib/url.ts')).toBeNull();
	});
});
