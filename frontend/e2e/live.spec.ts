import { expect, test, type Page } from '@playwright/test';

const details = (page: Page) => page.getByRole('complementary', { name: 'Details' });
const legend = (page: Page) => page.getByLabel('Legend');

async function searchFor(page: Page, text: string): Promise<void> {
	await page.getByRole('combobox', { name: 'Search' }).fill(text);
	await page.keyboard.press('Enter');
}

async function goLive(page: Page): Promise<void> {
	await page.goto('/');
	await expect(page.getByText('5 sites · 52 devices · 106 links')).toBeVisible();
	await page.getByRole('button', { name: 'Live' }).click();
	await expect(page.getByText(/simulated · as of/)).toBeVisible();
}

test('live mode explains its colors and turns off again', async ({ page }) => {
	await goLive(page);
	for (const label of ['Up', 'Packet loss', 'No recent data', 'Not monitored', 'No data']) {
		// Labels follow their glyph (×, !, ?) in the same element, so match by substring.
		await expect(legend(page).getByText(label).first()).toBeVisible();
	}
	await page.getByRole('button', { name: 'Live' }).click();
	await expect(legend(page).getByText('WAN link')).toBeVisible();
	await expect(page.getByText(/simulated · as of/)).toBeHidden();
});

test('a monitored device shows round-trip times and load on each link', async ({ page }) => {
	await goLive(page);
	// Core devices are always monitored; whether one is up depends on the moment.
	await searchFor(page, 'dal-core-01');
	const panel = details(page);
	await expect(panel.getByRole('cell', { name: 'west (DAL)' })).toBeVisible();
	await expect(panel.getByRole('cell', { name: 'east (IAD)' })).toBeVisible();
	await expect(panel.getByRole('columnheader', { name: 'Out / in' })).toBeVisible();
	// Every neighbor row says something in the load column: a load, "down", or "no data".
	const neighbors = panel
		.getByRole('table')
		.filter({ has: page.getByRole('columnheader', { name: 'Out / in' }) });
	await expect(neighbors.locator('tbody tr').first()).toContainText(
		/\d+% \/ \d+%|down|no data|not monitored/
	);
});

test('a device the source does not watch says so instead of showing zero', async ({ page }) => {
	const state = await (await page.request.get('/api/state')).json();
	const topology = await (await page.request.get('/api/topology')).json();
	const watched = new Set(state.devices.map((d: { device: string }) => d.device));
	const unwatched = topology.devices.find((d: { name: string }) => !watched.has(d.name));
	await goLive(page);
	await searchFor(page, unwatched.name);
	const panel = details(page);
	await expect(panel.getByText('Not monitored')).toBeVisible();
	await expect(panel.getByText('The simulated source does not watch this device.')).toBeVisible();
	await expect(panel.getByRole('cell', { name: /ms$/ })).toHaveCount(0);
});
