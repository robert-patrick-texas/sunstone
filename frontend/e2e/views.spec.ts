import { expect, test, type Page } from '@playwright/test';

const details = (page: Page) => page.getByRole('complementary', { name: 'Details' });
const heading = (page: Page) => details(page).getByRole('heading', { level: 2 });

async function searchFor(page: Page, text: string): Promise<void> {
	await page.getByRole('combobox', { name: 'Search' }).fill(text);
	await page.keyboard.press('Enter');
}

test.beforeEach(async ({ page }) => {
	await page.goto('/');
	await expect(page.getByText('5 sites · 52 devices · 106 links')).toBeVisible();
});

test('a device found by search stays selected when switching views', async ({ page }) => {
	await searchFor(page, 'hou-dist-01');
	await expect(heading(page)).toHaveText('hou-dist-01');
	// Header row plus one row per neighbor.
	await expect(details(page).getByRole('row')).toHaveCount(9);

	await page.getByRole('button', { name: 'Hierarchy' }).click();
	await expect(page.getByRole('button', { name: 'Expand all' })).toBeVisible();
	await expect(heading(page)).toHaveText('hou-dist-01');

	await page.getByRole('button', { name: 'Geographic' }).click();
	await expect(page.getByRole('button', { name: 'Fit all sites' })).toBeVisible();
	await expect(heading(page)).toHaveText('hou-dist-01');
});

test('a neighbor in the details panel can be followed', async ({ page }) => {
	await searchFor(page, 'hou-acc-01');
	await details(page).getByRole('button', { name: 'hou-dist-02' }).click();
	await expect(heading(page)).toHaveText('hou-dist-02');
});

test('a site shows its links to other sites', async ({ page }) => {
	await searchFor(page, 'AUS');
	await expect(heading(page)).toHaveText('AUS · Austin');
	await expect(details(page).getByText('Links to other sites (2)')).toBeVisible();
});

test('Escape clears the selection', async ({ page }) => {
	await searchFor(page, 'dal-core-01');
	await expect(details(page)).toBeVisible();
	await page.locator('body').press('Escape');
	await expect(details(page)).toBeHidden();
});
