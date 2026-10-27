<!--
@component
Key to device colors and link lines, shared by every view.
-->
<script lang="ts">
	import { COLOR, ROLE_COLOR } from './theme.ts';
	import { ROLE_LABEL, ROLES } from './topology.ts';
</script>

<div class="legend" aria-label="Legend">
	{#each ROLES as role (role)}
		<span><i class="swatch" style:background={ROLE_COLOR[role]}></i>{ROLE_LABEL[role]}</span>
	{/each}
	<span><i class="line" style:background={COLOR.wan}></i>WAN link</span>
	<span><i class="line" style:background={COLOR.lan}></i>LAN link</span>
</div>

<style>
	.legend {
		position: absolute;
		left: 12px;
		bottom: 12px;
		display: flex;
		flex-wrap: wrap;
		gap: 4px 14px;
		max-width: calc(100% - 120px);
		padding: 6px 10px;
		background: rgb(22 28 36 / 0.85);
		border: 1px solid var(--border);
		border-radius: 6px;
		font-size: 12px;
		color: var(--muted);
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
</style>
