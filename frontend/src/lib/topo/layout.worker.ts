/**
 * Lays out topology graphs off the main thread: receives a layout request,
 * answers with positions.
 */
import { layoutPositions, type LayoutRequest } from './layouts.ts';

self.onmessage = (e: MessageEvent<LayoutRequest>) => {
	self.postMessage(layoutPositions(e.data));
};
