<!--
@component
Key to what colors and lines mean: device roles and link kinds, or with live
state, device health and link load, or while an impact is shown, how
devices and links are affected, or while discovery is shown, what it sees
that the documentation does not. Every color is named here, and the glyphs
are shown, so color is never the only cue. With named networks shown, also
what their colors and dashes mean; where resources are drawn, their hexagons.
With anything hidden from the map, how many, and a switch to show them anyway.
-->
<script lang="ts">
	import type { Status } from './api/status.ts';
	import { hiding } from './graph/drawn.ts';
	import { IMPACT_LABEL, type DeviceImpact } from './impact.ts';
	import { HEALTH_LABEL, type DeviceHealth } from './live.ts';
	import { overrides } from './overrides.svelte.ts';
	import { STATUS_COLOR, STATUS_GLYPH, STATUS_LABEL } from './status.ts';
	import {
		COLOR,
		DRIFT_COLOR,
		HEALTH_COLOR,
		HEALTH_GLYPH,
		IMPACT_COLOR,
		IMPACT_GLYPH,
		LINK_NODATA,
		LINK_UNMONITORED,
		DEPTH_COLOR,
		ROLE_COLOR,
		TUNNEL_COLOR,
		UTIL_BANDS
	} from './theme.ts';
	import { ROLE_LABEL, ROLES } from './topology.ts';

	const {
		live,
		impact,
		discovery,
		layers = false,
		resources = false,
		map = false
	}: {
		live: boolean;
		impact: boolean;
		discovery: boolean;
		/** Named networks are drawn. */
		layers?: boolean;
		/** Resources are drawn. */
		resources?: boolean;
		/** Over the geographic map, whose attribution takes the bottom right corner. */
		map?: boolean;
	} = $props();
	const DEPTHS = ['Over circuits', 'Over another', 'Three deep'];

	const HEALTHS: DeviceHealth[] = ['up', 'degraded', 'down', 'nodata', 'unmonitored'];
	const IMPACTS: DeviceImpact[] = ['failed', 'cutoff', 'exposed'];
	const STATUSES: Status[] = ['operational', 'degraded', 'offline'];

	const hidden = $derived(hiding().length);
</script>

<div
	class="legend"
	class:live={(live && !impact) || layers || resources}
	class:map
	aria-label="Legend"
>
	{#if impact}
		<div class="row">
			<b>Impact</b>
			{#each IMPACTS as i (i)}
				<span>
					<i class="dot {i}" style:--c={IMPACT_COLOR[i]}>{IMPACT_GLYPH[i]}</i>{IMPACT_LABEL[i]}
				</span>
			{/each}
			<span><i class="line dashed" style:color={IMPACT_COLOR.failed}></i>Link lost</span>
			<span><i class="line dashed" style:color={IMPACT_COLOR.exposed}></i>Some links lost</span>
			<span>Faded: not affected</span>
		</div>
	{:else if discovery}
		<div class="row">
			<b>Discovery</b>
			<span><i class="line dashed" style:color={DRIFT_COLOR}></i>Seen, not documented</span>
			<span
				><i class="line dotted" style:color={DRIFT_COLOR}></i>Documented, not seen as documented</span
			>
			<span><i class="ring" style:--c={DRIFT_COLOR}></i>Involved</span>
			<span>Faded: as documented</span>
		</div>
	{:else if live}
		<div class="row">
			<b>Devices</b>
			{#each HEALTHS as health (health)}
				<span>
					<i
						class="dot {health}"
						style:background={health === 'unmonitored' ? 'transparent' : HEALTH_COLOR[health]}
						>{HEALTH_GLYPH[health]}</i
					>{HEALTH_LABEL[health]}
				</span>
			{/each}
		</div>
		<div class="row">
			<b>Links</b>
			<span class="bands" aria-label="Load, percent of capacity">
				{#each UTIL_BANDS as [from, color] (from)}
					<i class="band" style:background={color}><b>{from}</b></i>
				{/each}
				<b class="end">100%</b>
			</span>
			<span><i class="line dashed" style:color={HEALTH_COLOR.down}></i>Down</span>
			<span><i class="line dotted" style:color={LINK_NODATA}></i>No data</span>
			<span><i class="line" style:background={LINK_UNMONITORED}></i>Not monitored</span>
		</div>
	{:else}
		<div class="row">
			{#each ROLES as role (role)}
				<span><i class="swatch" style:background={ROLE_COLOR[role]}></i>{ROLE_LABEL[role]}</span>
			{/each}
			<span><i class="line" style:background={COLOR.wan}></i>WAN link</span>
			<span><i class="line" style:background={COLOR.lan}></i>LAN link</span>
		</div>
	{/if}
	{#if layers}
		<div class="row">
			<b>Networks</b>
			{#each DEPTHS as label, i (label)}
				<span><i class="swatch round" style:background={DEPTH_COLOR[i]}></i>{label}</span>
			{/each}
			{#if live}
				<span><i class="line dashed" style:color={TUNNEL_COLOR.up}></i>Tunnel up</span>
				<span><i class="line dashed" style:color={TUNNEL_COLOR.down}></i>Down</span>
				<span><i class="line dashed" style:color={TUNNEL_COLOR.unknown}></i>Not reported</span>
			{:else}
				<span><i class="line dashed" style:color={DEPTH_COLOR[0]}></i>Tunnel</span>
			{/if}
			<span><i class="outside"></i>Outside the boundary</span>
		</div>
	{/if}
	{#if resources}
		<div class="row">
			<b>Resources</b>
			{#if live}
				{#each STATUSES as s (s)}
					<span
						><i class="hex" style:--c={STATUS_COLOR[s]}>{STATUS_GLYPH[s]}</i>{STATUS_LABEL[s]}</span
					>
				{/each}
			{:else}
				<span><i class="hex" style:--c={COLOR.muted}></i>Status colors in live state</span>
			{/if}
			<span><i class="line dotted" style:color={COLOR.muted}></i>To its members</span>
		</div>
	{/if}
	{#if hidden > 0}
		<div class="row">
			<span>{hidden} hidden from the map</span>
			<label><input type="checkbox" bind:checked={overrides.showHidden} />Show</label>
		</div>
	{/if}
</div>

<style>
	.legend {
		position: absolute;
		left: 12px;
		bottom: 12px;
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 4px 14px;
		max-width: min(calc(100% - 120px), 600px);
		padding: 6px 10px;
		background: rgb(22 28 36 / 0.85);
		border: 1px solid var(--border);
		border-radius: 6px;
		font-size: 12px;
		color: var(--muted);
	}
	/* Clear of the map's attribution when the map is too narrow for both. */
	.legend.map {
		bottom: 40px;
	}
	.legend.live {
		flex-direction: column;
		align-items: flex-start;
	}
	.row {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 4px 14px;
	}
	.row > b {
		width: 62px;
		font-weight: 600;
		color: var(--text);
	}
	span,
	label {
		display: inline-flex;
		align-items: center;
		gap: 6px;
	}
	input {
		margin: 0;
	}
	.swatch {
		width: 12px;
		height: 8px;
		border-radius: 2px;
	}
	.swatch.round {
		width: 9px;
		height: 9px;
		border-radius: 50%;
	}
	.hex {
		display: inline-grid;
		place-items: center;
		width: 16px;
		height: 14px;
		clip-path: polygon(25% 0, 75% 0, 100% 50%, 75% 100%, 25% 100%, 0 50%);
		background: var(--c);
		font-style: normal;
		font-size: 10px;
		font-weight: 700;
		color: var(--bg);
	}
	.outside {
		display: inline-block;
		width: 14px;
		height: 9px;
		border: 1.5px dashed var(--muted);
		border-radius: 50%;
	}
	.ring {
		display: inline-block;
		width: 9px;
		height: 9px;
		margin-right: 5px;
		border-radius: 50%;
		border: 2px solid var(--c);
		vertical-align: -1px;
	}
	.line {
		width: 18px;
		height: 3px;
		border-radius: 2px;
	}
	.line.dashed,
	.line.dotted {
		height: 0;
		border-top: 3px dashed currentColor;
		border-radius: 0;
	}
	.line.dotted {
		border-top-style: dotted;
	}
	.dot {
		display: inline-grid;
		place-items: center;
		width: 14px;
		height: 14px;
		border-radius: 50%;
		font-style: normal;
		font-size: 11px;
		font-weight: 700;
		color: var(--bg);
	}
	.dot.unmonitored {
		box-sizing: border-box;
		border: 1px solid var(--muted);
	}
	.dot.failed,
	.dot.exposed {
		background: var(--c);
	}
	.dot.cutoff {
		box-sizing: border-box;
		border: 2px solid var(--c);
	}
	.bands {
		display: inline-flex;
		align-items: flex-end;
		gap: 2px;
		padding-bottom: 12px;
		position: relative;
	}
	.band {
		position: relative;
		width: 22px;
		height: 6px;
	}
	.band b,
	.end {
		position: absolute;
		top: 8px;
		left: -3px;
		font-weight: normal;
		font-size: 10px;
	}
	.end {
		position: static;
		margin-left: 2px;
		align-self: flex-start;
		transform: translateY(8px);
	}
</style>
