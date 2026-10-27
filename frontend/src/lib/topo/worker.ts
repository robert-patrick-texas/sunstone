/**
 * Runs topology layouts in a Web Worker, so laying out thousands of devices
 * leaves the page responsive. One layout runs at a time: a new request stops
 * the worker still busy with an older one, whose result nobody wants, and
 * starts a fresh worker.
 */
import type { Position } from 'cytoscape';
import type { LayoutRequest } from './layouts.ts';
import LayoutWorker from './layout.worker.ts?worker';

/** Thrown for a layout that a newer request replaced. */
export class Superseded extends Error {}

let worker: Worker | null = null;
let running: ((e: Error) => void) | null = null;

/**
 * Lay out a graph in the worker.
 *
 * @param request - The graph and how to lay it out.
 * @returns Positions of devices and site boxes.
 * @throws Superseded if another request replaces this one first.
 */
export function layoutInWorker(request: LayoutRequest): Promise<Map<string, Position>> {
	if (running) {
		worker?.terminate();
		worker = null;
		running(new Superseded('A newer layout replaced this one'));
	}
	const w = (worker ??= new LayoutWorker());
	return new Promise((resolve, reject) => {
		running = reject;
		w.onmessage = (e: MessageEvent<Map<string, Position>>) => {
			running = null;
			resolve(e.data);
		};
		w.onerror = (e) => {
			running = null;
			w.terminate();
			worker = null;
			reject(new Error(`Layout failed: ${e.message}`));
		};
		w.postMessage(request);
	});
}
