/**
 * Vite and SvelteKit configuration, following vakr's web UI.
 *
 * The app is a static single-page app: `adapter-static` writes `index.html`
 * plus hashed assets, which the Sunstone backend serves at `/`. The dev
 * server proxies `/api/` to a local backend (`SUNSTONE_API_URL`, default
 * `http://127.0.0.1:8000`).
 */
import { sveltekit } from '@sveltejs/kit/vite';
import adapter from '@sveltejs/adapter-static';
import { defineConfig } from 'vitest/config';

const apiTarget = process.env['SUNSTONE_API_URL'] ?? 'http://127.0.0.1:8000';

export default defineConfig({
	plugins: [
		sveltekit({
			adapter: adapter({ pages: 'build', assets: 'build', fallback: 'index.html', strict: true }),
			paths: { relative: false },
			compilerOptions: { runes: true }
		})
	],
	build: {
		// MapLibre and Cytoscape are large on their own; the warning is noise here.
		chunkSizeWarningLimit: 1500
	},
	server: {
		host: '127.0.0.1',
		proxy: { '/api/': { target: apiTarget, changeOrigin: false } }
	},
	test: {
		include: ['src/**/*.test.ts'],
		environment: 'node'
	}
});
