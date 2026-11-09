/**
 * What the drawings draw, as overrides leave it: everything but what is
 * hidden from the map (see `hiddenOnMap`), with circuits into a transport
 * hidden left out too, and devices and external nodes by the names they are
 * shown by.
 *
 * Kept apart from `model.ts`, which the layout worker loads: the overrides
 * are Svelte state, which the worker cannot hold.
 */
import type { OverrideNow } from '../api/overrides.ts';
import type { Link } from '../api/topology.ts';
import { hiddenOnMap, overrides, shown, targetKey } from '../overrides.svelte.ts';
import { isDeviceEnd, nodeKey, type TopologyIndex } from '../topology.ts';
import type { GraphNode } from './model.ts';

/**
 * The links drawn.
 *
 * @param index - Topology index.
 * @returns Every link but those hidden from the map, those of devices and
 *   sites hidden, and those into transports and to external nodes hidden.
 */
export function drawnLinks(index: TopologyIndex): Link[] {
	const hidden = hiddenOnMap(index);
	return index.topology.links.filter(
		(l) => !hidden.links.has(l.id) && !('transport' in l.b && hidden.transports.has(l.b.transport))
	);
}

/**
 * The transports and external nodes drawn: those with a link drawn.
 *
 * @param links - From {@link drawnLinks}.
 * @returns Their `transport:` and `external:` keys, each once, in the order of the links.
 */
export function drawnBeyond(links: Link[]): string[] {
	return [...new Set(links.flatMap((l) => (isDeviceEnd(l.b) ? [] : [nodeKey(l.b)])))];
}

/**
 * The overrides that hide something from the map now.
 *
 * @returns Them, newest first.
 */
export function hiding(): OverrideNow[] {
	return overrides.list.filter((o) => o.kind === 'hide-map' && o.state === 'active');
}

/**
 * What is hidden from the map now, as part of a layout's key: a layout made
 * with something hidden has no place for it.
 *
 * @returns The targets hidden, or empty while the legend's switch shows them.
 */
export function hiddenKey(): string {
	if (overrides.showHidden) return '';
	return hiding()
		.map((o) => targetKey(o.target))
		.sort()
		.join();
}

/**
 * What a node is labeled.
 *
 * @param node - The node.
 * @returns A device's or external node's name as it is shown; any other node's own label.
 */
export function nodeLabel(node: GraphNode): string {
	if (node.kind === 'device') return shown(node.id);
	if (node.kind === 'external') return shown(node.id.slice('external:'.length));
	return node.label;
}
