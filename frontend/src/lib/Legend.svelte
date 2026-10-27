<!--
@component
Key to what colors and lines mean: device roles and link kinds, or with live
state, device health and link load, or while an impact is shown, how
devices and links are affected. Every color is named here, and the glyphs
are shown, so color is never the only cue.
-->
<script lang="ts">
	import { IMPACT_LABEL, type DeviceImpact } from './impact.ts';
	import { HEALTH_LABEL, type DeviceHealth } from './live.ts';
	import {
		COLOR,
		HEALTH_COLOR,
		HEALTH_GLYPH,
		IMPACT_COLOR,
		IMPACT_GLYPH,
		LINK_NODATA,
		LINK_UNMONITORED,
		ROLE_COLOR,
		UTIL_BANDS
	} from './theme.ts';
	import { ROLE_LABEL, ROLES } from './topology.ts';

	const { live, impact }: { live: boolean; impact: boolean } = $props();

	const HEALTHS: DeviceHealth[] = ['up', 'degraded', 'down', 'nodata', 'unmonitored'];
	const IMPACTS: DeviceImpact[] = ['failed', 'cutoff', 'exposed'];
</script>

<div class="legend" class:live={live && !impact} aria-label="Legend">
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
		{#each ROLES as role (role)}
			<span><i class="swatch" style:background={ROLE_COLOR[role]}></i>{ROLE_LABEL[role]}</span>
		{/each}
		<span><i class="line" style:background={COLOR.wan}></i>WAN link</span>
		<span><i class="line" style:background={COLOR.lan}></i>LAN link</span>
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
		width: 52px;
		font-weight: 600;
		color: var(--text);
	}
	span {
		display: inline-flex;
		align-items: center;
		gap: 6px;
	}
	.swatch {
		width: 12px;
		height: 8px;
		border-radius: 2px;
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
