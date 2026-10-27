/**
 * How the large sample behaves: live updates, zooming, and laying out the
 * whole network. Prints one table; nothing here passes or fails on speed.
 */
import { expect, test, type Page } from '@playwright/test';

interface Timing {
	last: number;
	max: number;
	total: number;
	count: number;
}
interface Perf {
	longestTaskMs: number;
	timings: Record<string, Timing>;
}
interface Row {
	scenario: string;
	fps?: number;
	worstFrameMs?: number;
	longestTaskMs: number;
	timings: string;
}

const rows: Row[] = [];

async function perfOf(page: Page): Promise<Perf> {
	return page.evaluate(() => {
		const p = (window as unknown as { sunstonePerf: Perf }).sunstonePerf;
		return { longestTaskMs: p.longestTaskMs, timings: { ...p.timings } };
	});
}

/** Measure one scenario: the work's timings, the longest block, and optionally the frame rate. */
async function measure(
	page: Page,
	scenario: string,
	action: () => Promise<void>,
	frames = false
): Promise<void> {
	await page.evaluate(() => {
		const w = window as unknown as {
			sunstonePerf: Perf;
			benchFrames: number[];
			benchCounting: boolean;
		};
		w.sunstonePerf.timings = {};
		w.sunstonePerf.longestTaskMs = 0;
		w.benchFrames = [];
		w.benchCounting = true;
		const tick = (t: number) => {
			w.benchFrames.push(t);
			if (w.benchCounting) requestAnimationFrame(tick);
		};
		requestAnimationFrame(tick);
	});
	await action();
	const counted = await page.evaluate(() => {
		const w = window as unknown as { benchFrames: number[]; benchCounting: boolean };
		w.benchCounting = false;
		const f = w.benchFrames;
		const gaps = f.slice(1).map((t, i) => t - (f[i] ?? t));
		const span = (f[f.length - 1] ?? 0) - (f[0] ?? 0);
		return { fps: span ? ((f.length - 1) * 1000) / span : 0, worst: Math.max(0, ...gaps) };
	});
	const p = await perfOf(page);
	rows.push({
		scenario,
		...(frames ? { fps: Math.round(counted.fps), worstFrameMs: Math.round(counted.worst) } : {}),
		longestTaskMs: p.longestTaskMs,
		timings: Object.entries(p.timings)
			.map(
				([name, t]) => `${name} ${Math.round(t.total / t.count)}${t.count > 1 ? `×${t.count}` : ''}`
			)
			.join(', ')
	});
}

async function pan(page: Page, ms: number): Promise<void> {
	const box = { x: 800, y: 500 };
	await page.mouse.move(box.x, box.y);
	await page.mouse.down();
	const steps = Math.round(ms / 16);
	for (let i = 0; i < steps; i++) {
		await page.mouse.move(box.x + 200 * Math.sin(i / 10), box.y + 100 * Math.cos(i / 10));
	}
	await page.mouse.up();
}

async function zoom(page: Page, times: number): Promise<void> {
	await page.mouse.move(800, 500);
	for (let i = 0; i < times; i++) {
		await page.mouse.wheel(0, i < times / 2 ? -300 : 300);
		await page.waitForTimeout(100);
	}
}

const timing = (page: Page, name: string) =>
	page.waitForFunction(
		(n) => Boolean((window as unknown as { sunstonePerf: Perf }).sunstonePerf.timings[n]),
		name,
		{ timeout: 120_000 }
	);

test('large sample', async ({ page }) => {
	await page.goto('/?perf');
	await expect(page.getByText('2960 devices')).toBeVisible();
	await page.waitForSelector('.maplibregl-canvas');
	await page.waitForTimeout(3000);

	await measure(page, 'map: zoom in and out', () => zoom(page, 20), true);
	await measure(page, 'map: live on, first update', async () => {
		await page.getByRole('button', { name: 'Live' }).click();
		await expect(page.getByText(/simulated · as of/)).toBeVisible({ timeout: 30_000 });
		await timing(page, 'map update');
		await page.waitForTimeout(1000);
	});
	await measure(page, 'map: next live update', async () => {
		await timing(page, 'live fetch');
		await timing(page, 'map update');
		await page.waitForTimeout(500);
	});
	await measure(page, 'map: zoom with live state', () => zoom(page, 20), true);
	await page.getByRole('button', { name: 'Live' }).click();

	await page.getByRole('button', { name: 'Hierarchy' }).click();
	await page.waitForTimeout(2000);
	await measure(page, 'hierarchy: expand all', async () => {
		await page.getByRole('button', { name: 'Expand all' }).click();
		await timing(page, 'hierarchy layout');
		await page.waitForTimeout(1000);
	});
	await measure(page, 'hierarchy: pan, all expanded', () => pan(page, 3000), true);

	// Every site is still expanded, so the topology view lays out all 2,960 devices.
	await measure(page, 'topology: whole network, all expanded', async () => {
		await page.getByRole('button', { name: 'Topology' }).click();
		await timing(page, 'topology layout');
		await page.waitForTimeout(1000);
	});
	// Dragging here would move a device, so zoom instead.
	await measure(page, 'topology: zoom, all expanded', () => zoom(page, 20), true);
	await measure(page, 'topology: collapse all', async () => {
		await page.getByRole('button', { name: 'Collapse all' }).click();
		await timing(page, 'topology layout');
		await page.waitForTimeout(500);
	});

	const width = Math.max(...rows.map((r) => r.scenario.length));
	const lines = rows.map(
		(r) =>
			`${r.scenario.padEnd(width)}  ${String(r.fps ?? '').padStart(4)}  ${String(r.worstFrameMs ?? '').padStart(6)}  ${String(r.longestTaskMs).padStart(7)}  ${r.timings}`
	);
	console.log(
		[
			`${'Scenario'.padEnd(width)}   fps  worst  longest  timings (ms)`,
			`${''.padEnd(width)}        frame    block`,
			...lines
		].join('\n')
	);
});
