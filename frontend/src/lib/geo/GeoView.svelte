<!--
@component
Geographic view: sites and site-to-site links on a map. Zooming in past
`DEVICE_ZOOM` opens each site into its devices and their links. Clicking a
site selects it and zooms in to its devices. A path, when shown, is drawn in
its own color with everything else faded. With live state, sites and
devices take their health colors and glyphs, and links their load colors;
links that are down or partly down are dashed, and links with no data dotted.
An impact is drawn like a path: affected sites, devices, and links in impact
styles, everything else faded.
-->
<script lang="ts">
	import { onMount, untrack } from 'svelte';
	import {
		LngLatBounds,
		Map as MapLibre,
		NavigationControl,
		setWorkerUrl,
		type ExpressionSpecification,
		type FilterSpecification,
		type GeoJSONSource,
		type MapGeoJSONFeature,
		type PointLike
	} from 'maplibre-gl';
	import 'maplibre-gl/dist/maplibre-gl.css';
	// MapLibre looks for its worker next to its own module, which bundling moves;
	// hand it the worker's emitted URL instead.
	import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url';
	import type { Impact } from '../impact.ts';
	import type { LiveIndex } from '../live.ts';
	import type { PathResult } from '../paths.ts';
	import { select, ui, type Selection } from '../state.svelte.ts';
	import {
		COLOR,
		HEALTH_COLOR,
		IMPACT_COLOR,
		LINK_NODATA,
		LINK_UNMONITORED,
		ROLE_COLOR,
		UTIL_BANDS
	} from '../theme.ts';
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

	const {
		index,
		path,
		impact,
		live
	}: {
		index: TopologyIndex;
		path: PathResult | null;
		impact: Impact | null;
		live: LiveIndex | null;
	} = $props();

	setWorkerUrl(workerUrl);

	const STYLE_URL = 'https://tiles.openfreemap.org/styles/dark';
	const SITE_FOCUS_ZOOM = 15;
	// Extra room at the bottom keeps sites clear of the legend.
	const FIT_PADDING = { top: 60, right: 60, bottom: 100, left: 60 };
	const DEVICE_FOCUS_ZOOM = 16.5;
	// Topmost first: the order clicks are resolved in when features overlap.
	const SOURCES = ['devices', 'sites', 'device-links', 'site-links'];
	const LINE_STYLES = ['', '-dashed', '-dotted'];
	const CLICKABLE = [
		'devices',
		'sites',
		...['device-links', 'site-links'].flatMap((s) => LINE_STYLES.map((style) => s + style))
	];
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

	// Live styling applies only to features that carry live properties.
	const hasLive: ExpressionSpecification = ['has', 'health'];
	const healthIs = (h: string): ExpressionSpecification => ['==', ['get', 'health'], h];
	const healthFill: ExpressionSpecification = [
		'match',
		['get', 'health'],
		'up',
		HEALTH_COLOR.up,
		'degraded',
		HEALTH_COLOR.degraded,
		'down',
		HEALTH_COLOR.down,
		'nodata',
		HEALTH_COLOR.nodata,
		'rgba(0, 0, 0, 0)'
	];
	const loadColor = [
		'match',
		['get', 'health'],
		'down',
		HEALTH_COLOR.down,
		'nodata',
		LINK_NODATA,
		'unmonitored',
		LINK_UNMONITORED,
		[
			'step',
			['coalesce', ['get', 'util'], 0],
			UTIL_BANDS[0]?.[1] ?? COLOR.lan,
			...UTIL_BANDS.slice(1).flat()
		]
	] as ExpressionSpecification;
	// Impact styling applies only to features an impact touches.
	const hasImpact: ExpressionSpecification = ['has', 'impact'];
	const impactIs = (i: string): ExpressionSpecification => ['==', ['get', 'impact'], i];
	const impactFill: ExpressionSpecification = [
		'match',
		['get', 'impact'],
		'failed',
		IMPACT_COLOR.failed,
		'exposed',
		IMPACT_COLOR.exposed,
		COLOR.background
	];
	const impactLine: ExpressionSpecification = [
		'match',
		['get', 'impact'],
		'lost',
		IMPACT_COLOR.failed,
		IMPACT_COLOR.exposed
	];
	const valueIn = (key: string, values: string[]): ExpressionSpecification => [
		'in',
		['coalesce', ['get', key], ''],
		['literal', values]
	];
	const dashed: ExpressionSpecification = [
		'any',
		valueIn('health', ['down', 'partial']),
		valueIn('impact', ['lost', 'partial'])
	];
	// One layer per line style: dash patterns cannot vary feature by feature.
	const LINE_FILTER: Record<string, FilterSpecification> = {
		'': ['all', ['!', dashed], ['!', valueIn('health', ['nodata'])]],
		'-dashed': dashed,
		'-dotted': ['all', ['!', dashed], valueIn('health', ['nodata'])]
	};
	const LINE_DASH: Record<string, number[] | undefined> = {
		'': undefined,
		'-dashed': [2, 1.5],
		'-dotted': [0.6, 1.6]
	};

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
			addLayers(
				m,
				untrack(() => live)
			);
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

	function addLayers(m: MapLibre, l: LiveIndex | null): void {
		const i = untrack(() => impact);
		m.addSource('site-links', {
			type: 'geojson',
			data: sitePairFeatures(index, pairs, l, i),
			promoteId: 'key'
		});
		m.addSource('sites', { type: 'geojson', data: siteFeatures(index, l, i), promoteId: 'code' });
		m.addSource('device-links', {
			type: 'geojson',
			data: linkFeatures(index.topology.links, positions, l, i),
			promoteId: 'id'
		});
		m.addSource('devices', {
			type: 'geojson',
			data: deviceFeatures(index, positions, l, i),
			promoteId: 'name'
		});
		for (const style of LINE_STYLES) {
			const dash = LINE_DASH[style];
			m.addLayer({
				id: `site-links${style}`,
				type: 'line',
				source: 'site-links',
				maxzoom: DEVICE_ZOOM,
				filter: LINE_FILTER[style],
				layout: { 'line-cap': 'round' },
				paint: {
					'line-color': [
						'case',
						isSelected,
						COLOR.selected,
						onPath,
						COLOR.path,
						hasImpact,
						impactLine,
						hasLive,
						loadColor,
						COLOR.wan
					],
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
					],
					...(dash ? { 'line-dasharray': dash } : {})
				}
			});
		}
		for (const style of LINE_STYLES) {
			const dash = LINE_DASH[style];
			m.addLayer({
				id: `device-links${style}`,
				type: 'line',
				source: 'device-links',
				minzoom: DEVICE_ZOOM,
				filter: LINE_FILTER[style],
				paint: {
					'line-color': [
						'case',
						isSelected,
						COLOR.selected,
						onPath,
						COLOR.path,
						hasImpact,
						impactLine,
						hasLive,
						loadColor,
						['==', ['get', 'kind'], 'wan'],
						COLOR.wan,
						COLOR.lan
					],
					'line-width': ['interpolate', ['linear'], ['get', 'speed'], 1_000, 1, 100_000, 3],
					...(dash ? { 'line-dasharray': dash } : {})
				}
			});
		}
		const ring: ExpressionSpecification = [
			'case',
			isSelected,
			COLOR.selected,
			onPath,
			COLOR.path,
			impactIs('cutoff'),
			IMPACT_COLOR.cutoff,
			hasImpact,
			COLOR.background,
			healthIs('unmonitored'),
			HEALTH_COLOR.unmonitored,
			healthIs('nodata'),
			COLOR.text,
			COLOR.background
		];
		m.addLayer({
			id: 'sites',
			type: 'circle',
			source: 'sites',
			maxzoom: DEVICE_ZOOM,
			paint: {
				'circle-radius': ['interpolate', ['linear'], ['sqrt', ['get', 'devices']], 1, 5, 15, 16],
				'circle-color': ['case', hasImpact, impactFill, hasLive, healthFill, COLOR.site],
				'circle-opacity': 0.9,
				'circle-stroke-color': ring,
				'circle-stroke-width': ['case', isSelected, 3, onPath, 3, impactIs('cutoff'), 2.5, 1.5]
			}
		});
		m.addLayer({
			id: 'devices',
			type: 'circle',
			source: 'devices',
			minzoom: DEVICE_ZOOM,
			paint: {
				'circle-radius': ['interpolate', ['linear'], ['zoom'], DEVICE_ZOOM, 3, 18, 9],
				'circle-color': ['case', hasImpact, impactFill, hasLive, healthFill, roleColor],
				'circle-stroke-color': ring,
				'circle-stroke-width': [
					'case',
					isSelected,
					3,
					onPath,
					3,
					impactIs('cutoff'),
					2,
					hasImpact,
					1,
					['any', healthIs('unmonitored'), healthIs('nodata')],
					1.5,
					1
				]
			}
		});
		m.addLayer({
			id: 'device-glyphs',
			type: 'symbol',
			source: 'devices',
			minzoom: DEVICE_ZOOM,
			filter: ['has', 'glyph'],
			layout: {
				'text-field': ['get', 'glyph'],
				'text-font': FONT,
				'text-size': ['interpolate', ['linear'], ['zoom'], DEVICE_ZOOM, 6, 18, 12],
				'text-allow-overlap': true,
				'text-ignore-placement': true
			},
			paint: { 'text-color': COLOR.background }
		});
		m.addLayer({
			id: 'site-labels',
			type: 'symbol',
			source: 'sites',
			layout: {
				'text-field': ['coalesce', ['get', 'label'], ['get', 'code']],
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
		for (const source of SOURCES) {
			const feature = found.find((f) => f.source === source);
			if (feature) return feature;
		}
		return undefined;
	}

	function onClick(feature: MapGeoJSONFeature | undefined): void {
		const p = feature?.properties ?? {};
		switch (feature?.source) {
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

	// New snapshots, or a new impact to show, replace the features' properties.
	$effect(() => {
		const [m, l, i] = [map, live, impact];
		if (!m) return;
		untrack(() => {
			const update = (id: string, data: GeoJSON.FeatureCollection) =>
				(m.getSource(id) as GeoJSONSource | undefined)?.setData(data);
			update('sites', siteFeatures(index, l, i));
			update('site-links', sitePairFeatures(index, pairs, l, i));
			update('devices', deviceFeatures(index, positions, l, i));
			update('device-links', linkFeatures(index.topology.links, positions, l, i));
		});
	});

	$effect(() => {
		const m = map;
		const selection = ui.selection;
		if (!m) return;
		for (const source of SOURCES) m.removeFeatureState({ source });
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
		fade(m, path !== null ? onPath : impact !== null ? hasImpact : null, live !== null);
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

	/**
	 * While a path or an impact is shown, everything else fades. Live load
	 * colors need more opacity.
	 */
	function fade(m: MapLibre, shown: ExpressionSpecification | null, liveShown: boolean): void {
		const opacity = (normal: number): ExpressionSpecification =>
			shown ? ['case', isSelected, 1, shown, 1, FADED] : ['case', isSelected, 1, normal];
		for (const style of LINE_STYLES) {
			m.setPaintProperty(`site-links${style}`, 'line-opacity', opacity(liveShown ? 0.9 : 0.55));
			m.setPaintProperty(`device-links${style}`, 'line-opacity', opacity(1));
		}
		m.setPaintProperty('sites', 'circle-opacity', opacity(0.9));
		m.setPaintProperty('devices', 'circle-opacity', opacity(1));
		// Outlines and glyphs fade with their circles.
		m.setPaintProperty('sites', 'circle-stroke-opacity', opacity(1));
		m.setPaintProperty('devices', 'circle-stroke-opacity', opacity(1));
		m.setPaintProperty('device-glyphs', 'text-opacity', opacity(1));
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
