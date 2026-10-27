import { expect, test, type Page } from '@playwright/test';

async function searchFor(page: Page, text: string): Promise<void> {
	await page.getByRole('combobox', { name: 'Search' }).fill(text);
	await page.keyboard.press('Enter');
}

test.beforeEach(async ({ page }) => {
	await page.goto('/');
	await expect(page.getByText('5 sites · 52 devices · 106 links')).toBeVisible();
});

test('a path is listed hop by hop and drawn in the topology view', async ({ page }) => {
	await searchFor(page, 'hou-acc-01');
	await page.getByRole('button', { name: 'Path from here' }).click();
	await expect(page.getByText('Choose the destination for a path from')).toBeVisible();
	await searchFor(page, 'sat-acc-02');

	// Two distribution switches and two WAN routers on each side: 8 equal paths.
	const path = page.getByRole('region', { name: 'Path' });
	await expect(path.getByText('6 hops by link count · 8 equal-length paths')).toBeVisible();
	await expect(path.locator('details')).toHaveCount(8);
	await expect(path.locator('details').first().getByRole('listitem')).toHaveCount(7);

	await path.getByRole('button', { name: 'Show in topology' }).click();
	await expect(page.getByRole('status')).toHaveText(
		'hou-acc-01 → sat-acc-02 · 6 hops · 8 equal-length paths · 12 devices'
	);
	await path.getByRole('button', { name: 'Clear path' }).click();
	await expect(path).toBeHidden();
});

test('Escape stops choosing a destination but keeps the selection', async ({ page }) => {
	await searchFor(page, 'dal-core-01');
	await page.getByRole('button', { name: 'Path from here' }).click();
	await expect(page.getByText('Choose the destination for a path from')).toBeVisible();
	await page.locator('body').press('Escape');
	await expect(page.getByText('Choose the destination for a path from')).toBeHidden();
	const details = page.getByRole('complementary', { name: 'Details' });
	await expect(details.getByRole('heading', { level: 2 })).toHaveText('dal-core-01');
});
