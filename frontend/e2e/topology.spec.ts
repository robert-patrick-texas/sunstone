import { expect, test, type Page } from '@playwright/test';

const status = (page: Page) => page.getByRole('status');
const heading = (page: Page) =>
	page.getByRole('complementary', { name: 'Details' }).getByRole('heading', { level: 2 });

async function searchFor(page: Page, text: string): Promise<void> {
	await page.getByRole('searchbox', { name: 'Search sites and devices' }).fill(text);
	await page.keyboard.press('Enter');
}

test.beforeEach(async ({ page }) => {
	await page.goto('/');
	await expect(page.getByText('5 sites · 52 devices · 106 links')).toBeVisible();
});

test('the details panel opens a device neighborhood in the topology view', async ({ page }) => {
	await searchFor(page, 'hou-dist-01');
	await page.getByRole('button', { name: 'Show neighborhood' }).click();
	await expect(page.getByRole('button', { name: 'Topology' })).toHaveAttribute(
		'aria-pressed',
		'true'
	);
	await expect(status(page)).toHaveText('hou-dist-01 · 2 hops · 10 devices');

	// One hop: the device and its seven distinct neighbors.
	await page.getByLabel('Hops').selectOption('1');
	await expect(status(page)).toHaveText('hou-dist-01 · 1 hop · 8 devices');
	await expect(heading(page)).toHaveText('hou-dist-01');
});

test('searching inside a neighborhood moves it', async ({ page }) => {
	await page.getByRole('button', { name: 'Topology' }).click();
	await searchFor(page, 'hou-acc-01');
	await page.getByRole('button', { name: 'Neighborhood', exact: true }).click();
	await expect(status(page)).toContainText('hou-acc-01 · 2 hops');
	await searchFor(page, 'dal-core-01');
	await expect(status(page)).toContainText('dal-core-01 · 2 hops');
	await expect(heading(page)).toHaveText('dal-core-01');
});

test('a site neighborhood starts from all of its devices', async ({ page }) => {
	await searchFor(page, 'AUS');
	await page.getByRole('button', { name: 'Show neighborhood' }).click();
	await page.getByLabel('Hops').selectOption('1');
	await expect(status(page)).toHaveText('Site AUS · 1 hop · 13 devices');
});

test('the whole network and radial layouts draw without a selection', async ({ page }) => {
	await page.getByRole('button', { name: 'Topology' }).click();
	await expect(status(page)).toHaveText('5 sites, 5 expanded');
	await page.getByRole('button', { name: 'Radial' }).click();
	await expect(status(page)).toHaveText('5 sites, 5 expanded');
	await page.getByRole('button', { name: 'Neighborhood', exact: true }).click();
	await expect(page.getByText('Select a device or site, then choose Neighborhood.')).toBeVisible();
});
