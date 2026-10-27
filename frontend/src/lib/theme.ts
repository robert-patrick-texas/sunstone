/**
 * Colors the canvas-drawn views use. MapLibre and Cytoscape take colors as
 * values, not CSS variables, so they live here; `app.css` mirrors the UI ones.
 */
import type { Role } from './api/topology.ts';

export const ROLE_COLOR: Record<Role, string> = {
	'wan-edge': '#c792ea',
	core: '#f78c6c',
	distribution: '#82aaff',
	access: '#7fdbca'
};

export const COLOR = {
	background: '#0f1419',
	text: '#d8dee9',
	muted: '#8a96a8',
	site: '#f5a623',
	siteBox: '#1c2632',
	group: '#141c26',
	groupBorder: '#3a4a5e',
	wan: '#f5a623',
	lan: '#5c6b80',
	selected: '#ffe066'
};
