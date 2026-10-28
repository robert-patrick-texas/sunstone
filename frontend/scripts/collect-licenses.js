/**
 * Copy the licence and notice files of every package bundled into the web UI
 * to one directory, after `npm run build`, and check that the package's
 * copyright file names each one. The package build runs it.
 *
 * Usage: `node scripts/collect-licenses.js DIR COPYRIGHT`
 *
 * @packageDocumentation
 */
import { copyFileSync, mkdirSync, readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';

const LEGAL = /^(licen[cs]e|copying|notice)(\.(md|txt))?$/i;

/**
 * Copy one package's legal files.
 *
 * @param {string} name - The package name, such as `maplibre-gl`.
 * @param {string} target - The destination root.
 * @returns {number} How many files were copied.
 */
export function collect(name, target) {
	const source = join('node_modules', name);
	const files = readdirSync(source).filter((f) => LEGAL.test(f));
	const dest = join(target, name.replace('/', '__'));
	mkdirSync(dest, { recursive: true });
	for (const file of files) copyFileSync(join(source, file), join(dest, file));
	return files.length;
}

if (import.meta.url === `file://${process.argv[1]}`) {
	const [target, copyright] = process.argv.slice(2);
	if (!target || !copyright) {
		console.error('usage: node scripts/collect-licenses.js DIR COPYRIGHT');
		process.exit(2);
	}
	/** @type {string[]} */
	const bundled = JSON.parse(readFileSync('.svelte-kit/bundled-packages.json', 'utf8'));
	const named = readFileSync(copyright, 'utf8');
	const missing = bundled.filter((name) => collect(name, target) === 0);
	const unnamed = bundled.filter((name) => !named.includes(name));
	if (missing.length > 0)
		console.error(`collect-licenses: no licence file in ${missing.join(', ')}`);
	if (unnamed.length > 0)
		console.error(`collect-licenses: ${copyright} does not name ${unnamed.join(', ')}`);
	if (missing.length > 0 || unnamed.length > 0) process.exit(1);
	console.log(`collect-licenses: ${bundled.length} packages' licence files in ${target}`);
}
