/**
 * A Vite plugin that records which npm packages end up in the browser build,
 * following vakr's. The package build copies each one's licence files into
 * `/opt/sunstone/share/doc/web-licenses/` (`scripts/collect-licenses.js`),
 * since the minified build keeps no licence comments.
 *
 * In `generateBundle`, every module of every client chunk is mapped to the
 * package it came from, and the sorted list is written to
 * `.svelte-kit/bundled-packages.json`.
 *
 * @packageDocumentation
 */
import { mkdirSync, writeFileSync } from 'node:fs';
import type { Plugin } from 'vite';

export const BUNDLED_FILE = '.svelte-kit/bundled-packages.json';

/**
 * Name the package a module belongs to: the last `node_modules` segment wins (nested copies).
 *
 * @param id - A module id (a file path, possibly with a query).
 * @returns The package name, or null for Sunstone's own modules.
 */
export function packageOf(id: string): string | null {
	const path = id.split('?')[0]?.replaceAll('\\', '/') ?? '';
	const at = path.lastIndexOf('/node_modules/');
	if (at < 0) return null;
	const rest = path.slice(at + '/node_modules/'.length).split('/');
	const name = rest[0]?.startsWith('@') ? `${rest[0]}/${rest[1] ?? ''}` : rest[0];
	return name || null;
}

/**
 * The plugin.
 *
 * @returns A build-only plugin.
 */
export function bundledPackages(): Plugin {
	return {
		name: 'sunstone-bundled-packages',
		apply: 'build',
		generateBundle(_options, bundle) {
			if (this.environment.name !== 'client') return;
			const found = new Set<string>();
			for (const output of Object.values(bundle)) {
				if (output.type !== 'chunk') continue;
				for (const id of output.moduleIds) {
					const name = packageOf(id);
					if (name) found.add(name);
				}
			}
			mkdirSync('.svelte-kit', { recursive: true });
			writeFileSync(BUNDLED_FILE, JSON.stringify([...found].sort(), null, 2) + '\n');
		}
	};
}
