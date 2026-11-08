/**
 * Vite and SvelteKit configuration, following vakr's web UI.
 *
 * The app is a static single-page app: `adapter-static` writes `index.html`
 * plus hashed assets, which the Sunstone backend serves at `/`. The page is
 * prerendered with relative paths, so it also works behind a reverse proxy
 * that serves it under a path, such as `/sunstone/`; for the same reason the
 * API is asked at `api/...`, relative to the page. The dev
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
			// No fallback page: SvelteKit writes a fallback with paths from the site's
			// root, and the one page is prerendered instead (routes/+layout.ts).
			adapter: adapter({ pages: 'build', assets: 'build', strict: true }),
			// The prerendered page finds its assets and its base relative to where
			// the browser loaded it from.
			paths: { relative: true },
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
