/**
 * Vite and SvelteKit configuration, following vakr's web UI.
 *
 * The app is a static single-page app: `adapter-static` writes `index.html`
 * plus hashed assets, which the Sunstone backend serves at `/`. The dev
 * server proxies `/api/` to a local backend (`SUNSTONE_API_URL`, default
 * `http://127.0.0.1:8000`). The build records the npm packages it bundles,
 * for the licence files the Debian package carries.
 */
import { sveltekit } from '@sveltejs/kit/vite';
import adapter from '@sveltejs/adapter-static';
import { defineConfig } from 'vitest/config';
import { bundledPackages } from './scripts/bundled-packages.ts';

const apiTarget = process.env['SUNSTONE_API_URL'] ?? 'http://127.0.0.1:8000';

export default defineConfig({
	plugins: [
		sveltekit({
			adapter: adapter({ pages: 'build', assets: 'build', fallback: 'index.html', strict: true }),
			paths: { relative: false },
			// As vakr's: the package build sets SOURCE_DATE_EPOCH, so two builds of
			// one commit are byte-identical; SvelteKit's default is the build time.
			version: { name: process.env['SOURCE_DATE_EPOCH'] ?? 'dev', pollInterval: 0 },
			compilerOptions: { runes: true }
		}),
		bundledPackages()
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
		include: ['src/**/*.test.ts', 'scripts/**/*.test.ts'],
		environment: 'node'
	}
});
