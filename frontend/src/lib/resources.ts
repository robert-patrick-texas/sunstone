/**
 * Resources: what the enterprise depends on beyond its own networks, such
 * as a way out to the world or a cloud, each with a status of its own from
 * its members' (circuits by their enterprise CID at either side, tunnels,
 * fabrics, and other resources). Their status comes from `GET /api/status`;
 * these are the lookups every view shares.
 */
import type { Link, Resource } from './api/topology.ts';
import type { ResourceStatus, StatusReport } from './api/status.ts';
import { deviceEnds, siteOf, type TopologyIndex } from './topology.ts';

/** One of a resource's members, as listed in the topology. */
export type Member =
	| { kind: 'circuit'; name: string; link: Link | undefined }
	| { kind: 'tunnel'; name: string }
	| { kind: 'fabric'; name: string }
	| { kind: 'resource'; name: string };

/** Something a resource can hold, as a selection names it. */
export type Holdable =
	| { kind: 'links'; ids: string[] }
	| { kind: 'tunnel'; id: string }
	| { kind: 'fabric'; id: string }
	| { kind: 'resource'; id: string };

const byCid = new WeakMap<TopologyIndex, Map<string, Link>>();

/**
 * The link an enterprise CID names, at either side.
 *
 * @param index - Topology index.
 * @param cid - The CID.
 * @returns The link, or undefined.
 */
export function linkByCid(index: TopologyIndex, cid: string): Link | undefined {
	let found = byCid.get(index);
	if (!found) {
		found = new Map();
		for (const link of index.topology.links) {
			const ids = link.enterprise_cid;
			if (!ids) continue;
			for (const c of [ids.a, ids.z]) if (c && !found.has(c)) found.set(c, link);
		}
		byCid.set(index, found);
	}
	return found.get(cid);
}

/**
 * A resource's members, in the order the status lists them: circuits,
 * tunnels, fabrics, then resources.
 *
 * @param index - Topology index.
 * @param resource - The resource.
 * @returns Its members.
 */
export function membersOf(index: TopologyIndex, resource: Resource): Member[] {
	return [
		...resource.circuits.map((name): Member => ({
			kind: 'circuit',
			name,
			link: linkByCid(index, name)
		})),
		...resource.tunnels.map((name): Member => ({ kind: 'tunnel', name })),
		...resource.fabrics.map((name): Member => ({ kind: 'fabric', name })),
		...resource.resources.map((name): Member => ({ kind: 'resource', name }))
	];
}

/**
 * The devices a resource's members are at, its inner resources' included:
 * a circuit's or cable's devices, a tunnel's own ends, a fabric's members.
 *
 * @param index - Topology index.
 * @param name - The resource.
 * @returns Device names, each once.
 */
export function resourceDevices(index: TopologyIndex, name: string): string[] {
	const found = new Set<string>();
	const seen = new Set<string>();
	const visit = (n: string): void => {
		const r = index.resources.get(n);
		if (!r || seen.has(n)) return;
		seen.add(n);
		for (const m of membersOf(index, r)) {
			if (m.kind === 'circuit' && m.link) {
				for (const e of deviceEnds(m.link)) found.add(e.device);
			} else if (m.kind === 'tunnel') {
				const t = index.tunnels.get(m.name);
				if (t) {
					found.add(t.a.device);
					if ('device' in t.b) found.add(t.b.device);
				}
			} else if (m.kind === 'fabric') {
				for (const x of index.fabrics.get(m.name)?.members ?? []) found.add(x.device);
			} else if (m.kind === 'resource') {
				visit(m.name);
			}
		}
	};
	visit(name);
	return [...found];
}

/**
 * The sites a resource's members are at.
 *
 * @param index - Topology index.
 * @param name - The resource.
 * @returns Site codes, each once.
 */
export function resourceSites(index: TopologyIndex, name: string): string[] {
	return [...new Set(resourceDevices(index, name).map((d) => siteOf(index, d)))].filter(Boolean);
}

/**
 * The resources that list something as a member, directly.
 *
 * @param index - Topology index.
 * @param item - Links (any of them), a tunnel, a fabric, or a resource.
 * @returns Those resources, in the topology's order.
 */
export function resourcesHolding(index: TopologyIndex, item: Holdable): Resource[] {
	return index.topology.resources.filter((r) => {
		if (item.kind === 'links') {
			return r.circuits.some((c) => {
				const link = linkByCid(index, c);
				return link !== undefined && item.ids.includes(link.id);
			});
		}
		if (item.kind === 'tunnel') return r.tunnels.includes(item.id);
		if (item.kind === 'fabric') return r.fabrics.includes(item.id);
		return r.resources.includes(item.id);
	});
}

/**
 * A resource's status in a report.
 *
 * @param report - The report, or null without live state.
 * @param name - The resource.
 * @returns Its status, or undefined.
 */
export function resourceStatus(
	report: StatusReport | null,
	name: string
): ResourceStatus | undefined {
	return report?.resources.find((r) => r.name === name);
}

/**
 * The resources that need someone: degraded or offline, offline first.
 *
 * @param report - The report.
 * @returns Those resources, in the topology's order within each state.
 */
export function resourcesNeeding(report: StatusReport): ResourceStatus[] {
	return report.resources
		.filter((r) => r.status !== 'operational')
		.sort((x, y) => Number(x.status !== 'offline') - Number(y.status !== 'offline'));
}
