<!--
@component
Geographic view: sites and site-to-site links on a map. Zooming in past
`DEVICE_ZOOM` opens each site into its devices and their links. Clicking a
site selects it and zooms in to its devices. A path, when shown, is drawn in
its own color with everything else faded.
-->
<script lang="ts">
	import { onMount, untrack } from 'svelte';
	import {
		LngLatBounds,
		Map as MapLibre,
		NavigationControl,
		setWorkerUrl,
		type ExpressionSpecification,
		type MapGeoJSONFeature,
		type PointLike
	} from 'maplibre-gl';
	import 'maplibre-gl/dist/maplibre-gl.css';
	// MapLibre looks for its worker next to its own module, which bundling moves;
	// hand it the worker's emitted URL instead.
	import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url';
	import type { PathResult } from '../paths.ts';
	import { select, ui, type Selection } from '../state.svelte.ts';
	import { COLOR, ROLE_COLOR } from '../theme.ts';
	import { siteOf, type TopologyIndex } from '../topology.ts';
	import {
		DEVICE_ZOOM,
		devicePositions,
		deviceFeatures,
		linkFeatures,
		pairKey,
		siteFeatures,
		sitePairFeatures,
		sitePairs,
		type LonLat
	} from './geojson.ts';

	const { index, path }: { index: TopologyIndex; path: PathResult | null } = $props();

	setWorkerUrl(workerUrl);

	const STYLE_URL = 'https://tiles.openfreemap.org/styles/dark';
	const SITE_FOCUS_ZOOM = 15;
	// Extra room at the bottom keeps sites clear of the legend.
	const FIT_PADDING = { top: 60, right: 60, bottom: 100, left: 60 };
	const DEVICE_FOCUS_ZOOM = 16.5;
	// Topmost first: the order clicks are resolved in when features overlap.
	const CLICKABLE = ['devices', 'sites', 'device-links', 'site-links'];
	const FONT = ['Noto Sans Regular'];

	let container: HTMLDivElement;
	let map = $state.raw<MapLibre | null>(null);
	let lastFocus = ui.focusRequest;
	let lastPath = untrack(() => path);

	// The topology never changes while the view is open, so these are computed once.
	const positions = untrack(() => devicePositions(index));
	const pairs = untrack(() => sitePairs(index));
	const pairOfLink = new Map(pairs.flatMap((p) => p.linkIds.map((id) => [id, p.key] as const)));

	const roleColor: ExpressionSpecification = [
		'match',
		['get', 'role'],
		'wan-edge',
		ROLE_COLOR['wan-edge'],
		'core',
		ROLE_COLOR.core,
		'distribution',
		ROLE_COLOR.distribution,
		'access',
		ROLE_COLOR.access,
		COLOR.muted
	];
	const isSelected: ExpressionSpecification = ['boolean', ['feature-state', 'selected'], false];
	const onPath: ExpressionSpecification = ['boolean', ['feature-state', 'path'], false];
	const FADED = 0.12;

	onMount(() => {
		const m = new MapLibre({
			container,
			style: STYLE_URL,
			bounds: allSitesBounds(),
			fitBoundsOptions: { padding: FIT_PADDING },
			attributionControl: { compact: true }
		});
		m.addControl(new NavigationControl({ showCompass: false }), 'top-right');
		m.on('load', () => {
			addLayers(m);
			m.on('click', (e) => onClick(featureAt(m, e.point)));
			m.on('mousemove', (e) => {
				m.getCanvas().style.cursor = featureAt(m, e.point) ? 'pointer' : '';
			});
			map = m;
			// On opening, a shown path matters more than the selection (often its end).
			if (path) fitDevices(m, [...path.devices.keys()]);
			else if (ui.selection) focus(m, ui.selection);
		});
		return () => m.remove();
	});

	function addLayers(m: MapLibre): void {
		m.addSource('site-links', {
			type: 'geojson',
			data: sitePairFeatures(index, pairs),
			promoteId: 'key'
		});
		m.addSource('sites', { type: 'geojson', data: siteFeatures(index), promoteId: 'code' });
		m.addSource('device-links', {
			type: 'geojson',
			data: linkFeatures(index.topology.links, positions),
			promoteId: 'id'
		});
		m.addSource('devices', {
			type: 'geojson',
			data: deviceFeatures(index, positions),
			promoteId: 'name'
		});
		m.addLayer({
			id: 'site-links',
			type: 'line',
			source: 'site-links',
			maxzoom: DEVICE_ZOOM,
			layout: { 'line-cap': 'round' },
			paint: {
				'line-color': ['case', isSelected, COLOR.selected, onPath, COLOR.path, COLOR.wan],
				'line-opacity': ['case', isSelected, 1, 0.55],
				'line-width': [
					'interpolate',
					['linear'],
					['get', 'capacity'],
					1_000,
					1.2,
					20_000,
					3,
					200_000,
					6
				]
			}
		});
		m.addLayer({
			id: 'device-links',
			type: 'line',
			source: 'device-links',
			minzoom: DEVICE_ZOOM,
			paint: {
				'line-color': [
					'case',
					isSelected,
					COLOR.selected,
					onPath,
					COLOR.path,
					['==', ['get', 'kind'], 'wan'],
					COLOR.wan,
					COLOR.lan
				],
				'line-width': ['interpolate', ['linear'], ['get', 'speed'], 1_000, 1, 100_000, 3]
			}
		});
		m.addLayer({
			id: 'sites',
			type: 'circle',
			source: 'sites',
			maxzoom: DEVICE_ZOOM,
			paint: {
				'circle-radius': ['interpolate', ['linear'], ['sqrt', ['get', 'devices']], 1, 5, 15, 16],
				'circle-color': COLOR.site,
				'circle-opacity': 0.9,
				'circle-stroke-color': [
					'case',
					isSelected,
					COLOR.selected,
					onPath,
					COLOR.path,
					COLOR.background
				],
				'circle-stroke-width': ['case', isSelected, 3, onPath, 3, 1.5]
			}
		});
		m.addLayer({
			id: 'devices',
			type: 'circle',
			source: 'devices',
			minzoom: DEVICE_ZOOM,
			paint: {
				'circle-radius': ['interpolate', ['linear'], ['zoom'], DEVICE_ZOOM, 3, 18, 9],
				'circle-color': roleColor,
				'circle-stroke-color': [
					'case',
					isSelected,
					COLOR.selected,
					onPath,
					COLOR.path,
					COLOR.background
				],
				'circle-stroke-width': ['case', isSelected, 3, onPath, 3, 1]
			}
		});
		m.addLayer({
			id: 'site-labels',
			type: 'symbol',
			source: 'sites',
			layout: {
				'text-field': ['get', 'code'],
				'text-font': FONT,
				'text-size': 12,
				'text-offset': [0, 1.3],
				'text-anchor': 'top'
			},
			paint: {
				'text-color': COLOR.text,
				'text-halo-color': COLOR.background,
				'text-halo-width': 1.5
			}
		});
		m.addLayer({
			id: 'device-labels',
			type: 'symbol',
			source: 'devices',
			minzoom: 15.5,
			layout: {
				'text-field': ['get', 'name'],
				'text-font': FONT,
				'text-size': 10,
				'text-offset': [0, 0.9],
				'text-anchor': 'top'
			},
			paint: {
				'text-color': COLOR.text,
				'text-halo-color': COLOR.background,
				'text-halo-width': 1.5
			}
		});
	}

	function featureAt(m: MapLibre, point: { x: number; y: number }): MapGeoJSONFeature | undefined {
		const box: [PointLike, PointLike] = [
			[point.x - 4, point.y - 4],
			[point.x + 4, point.y + 4]
		];
		const found = m.queryRenderedFeatures(box, { layers: CLICKABLE });
		for (const layer of CLICKABLE) {
			const feature = found.find((f) => f.layer.id === layer);
			if (feature) return feature;
		}
		return undefined;
	}

	function onClick(feature: MapGeoJSONFeature | undefined): void {
		const p = feature?.properties ?? {};
		switch (feature?.layer.id) {
			case 'devices':
				return select({ kind: 'device', id: String(p['name']) });
			case 'sites':
				return select({ kind: 'site', id: String(p['code']) }, true);
			case 'device-links':
				return select({ kind: 'links', ids: [String(p['id'])] });
			case 'site-links': {
				const pair = pairs.find((x) => x.key === p['key']);
				return select(pair ? { kind: 'links', ids: pair.linkIds } : null);
			}
			default:
				return select(null);
		}
	}

	$effect(() => {
		const m = map;
		const selection = ui.selection;
		if (!m) return;
		for (const source of ['sites', 'site-links', 'devices', 'device-links']) {
			m.removeFeatureState({ source });
		}
		if (path) {
			const trace = (source: string, id: string) =>
				m.setFeatureState({ source, id }, { path: true });
			for (const device of path.devices.keys()) {
				trace('devices', device);
				trace('sites', siteOf(index, device));
			}
			for (const id of path.links) {
				trace('device-links', id);
				const pair = pairOfLink.get(id);
				if (pair) trace('site-links', pair);
			}
		}
		fade(m, path !== null);
		const mark = (source: string, id: string) =>
			m.setFeatureState({ source, id }, { selected: true });
		if (selection?.kind === 'device') {
			mark('devices', selection.id);
			mark('sites', siteOf(index, selection.id));
		} else if (selection?.kind === 'site') {
			mark('sites', selection.id);
		} else if (selection?.kind === 'links') {
			for (const id of selection.ids) {
				mark('device-links', id);
				const pair = pairOfLink.get(id);
				if (pair) mark('site-links', pair);
			}
		}
	});

	$effect(() => {
		const request = ui.focusRequest;
		const m = map;
		if (!m || request === lastFocus) return;
		lastFocus = request;
		untrack(() => ui.selection && focus(m, ui.selection));
	});

	// A newly shown path is brought into view.
	$effect(() => {
		const [m, p] = [map, path];
		if (!m || p === lastPath) return;
		lastPath = p;
		if (p) untrack(() => fitDevices(m, [...p.devices.keys()]));
	});

	/** While a path is shown, everything off it fades. */
	function fade(m: MapLibre, on: boolean): void {
		const opacity = (normal: number): ExpressionSpecification =>
			on ? ['case', isSelected, 1, onPath, 1, FADED] : ['case', isSelected, 1, normal];
		m.setPaintProperty('site-links', 'line-opacity', opacity(0.55));
		m.setPaintProperty('device-links', 'line-opacity', opacity(1));
		m.setPaintProperty('sites', 'circle-opacity', opacity(0.9));
		m.setPaintProperty('devices', 'circle-opacity', opacity(1));
	}

	/** Fit devices in view: their ring positions within one site, else their sites. */
	function fitDevices(m: MapLibre, devices: string[]): void {
		const sameSite = new Set(devices.map((d) => siteOf(index, d))).size === 1;
		const points: LonLat[] = devices.flatMap((d) => {
			const site = index.sites.get(siteOf(index, d));
			const at = sameSite ? positions.get(d) : site && ([site.lon, site.lat] as LonLat);
			return at ? [at] : [];
		});
		if (points.length) m.fitBounds(bounds(points), { padding: 120, maxZoom: 17 });
	}

	function focus(m: MapLibre, selection: Selection): void {
		if (selection.kind === 'device') {
			const at = positions.get(selection.id);
			if (at) m.flyTo({ center: at, zoom: Math.max(m.getZoom(), DEVICE_FOCUS_ZOOM) });
		} else if (selection.kind === 'site') {
			const site = index.sites.get(selection.id);
			if (site) {
				m.flyTo({ center: [site.lon, site.lat], zoom: Math.max(m.getZoom(), SITE_FOCUS_ZOOM) });
			}
		} else {
			const ends = selection.ids.flatMap((id) => {
				const link = index.links.get(id);
				return link ? [link.a.device, link.b.device] : [];
			});
			fitDevices(m, ends);
		}
	}

	function bounds(points: LonLat[]): LngLatBounds {
		return points.reduce((b, p) => b.extend(p), new LngLatBounds(points[0], points[0]));
	}

	function allSitesBounds(): LngLatBounds {
		return bounds(index.topology.sites.map((s) => [s.lon, s.lat] as LonLat));
	}
</script>

<div class="map" bind:this={container}></div>
<div class="tools">
	<button onclick={() => map?.fitBounds(allSitesBounds(), { padding: FIT_PADDING })}
		>Fit all sites</button
	>
</div>

<style>
	.map {
		position: absolute;
		inset: 0;
	}
	.tools {
		position: absolute;
		top: 12px;
		left: 12px;
		display: flex;
		gap: 6px;
	}
</style>
