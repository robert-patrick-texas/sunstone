import { expect, test, type Page } from '@playwright/test';

const details = (page: Page) => page.getByRole('complementary', { name: 'Details' });
const impact = (page: Page) => page.getByRole('region', { name: 'Impact' });

async function searchFor(page: Page, text: string): Promise<void> {
	await page.getByRole('combobox', { name: 'Search' }).fill(text);
	await page.keyboard.press('Enter');
}

test('a link shows someone else the same view, selection, and path', async ({ page }) => {
	await page.goto('/');
	await expect(page.getByText('5 sites · 52 devices · 106 links')).toBeVisible();
	await page.getByRole('button', { name: 'Hierarchy' }).click();
	await searchFor(page, 'dal-acc-01');
	await details(page).getByRole('button', { name: 'Path from here' }).click();
	await searchFor(page, 'hou-acc-02');
	await expect(page).toHaveURL(/view=hierarchy/);
	await expect(page).toHaveURL(/from=dal-acc-01&to=hou-acc-02/);

	const other = await page.context().newPage();
	await other.goto(page.url());
	await expect(other.getByRole('button', { name: 'Hierarchy' })).toHaveAttribute(
		'aria-pressed',
		'true'
	);
	const path = other.getByRole('region', { name: 'Path' });
	await expect(path).toContainText('dal-acc-01 → hou-acc-02');
	await expect(details(other).getByRole('heading', { name: 'hou-acc-02' })).toBeVisible();
});

test('a link opens a "what if" and a replayed moment again', async ({ page }) => {
	await page.goto('/?fail=device:dal-dist-01&fail=device:dal-dist-02');
	await expect(impact(page).getByRole('heading', { name: 'What if these fail' })).toBeVisible();
	await expect(impact(page).getByText('Cut off (6)')).toBeVisible();

	const hourAgo = new Date(Date.now() - 60 * 60_000);
	hourAgo.setUTCSeconds(0, 0);
	await page.goto(`/?live=1&at=${hourAgo.toISOString()}&select=device:dal-core-01`);
	await expect(page.getByText(/simulated · replaying/)).toBeVisible();
	await expect(details(page).getByRole('heading', { name: 'dal-core-01' })).toBeVisible();
});

test('the wall display moves on by itself, steps with the keys, and leaves with Escape', async ({
	page
}) => {
	await page.goto('/?wall=1&dwell=5');
	await expect(page.getByText('Network map')).toBeVisible();
	await expect(page.getByText(/simulated · as of/)).toBeVisible();
	await expect(page.getByText('Sites and tiers')).toBeVisible({ timeout: 10_000 });
	// The simulated network always has a device down, so there is a problem to show.
	await page.keyboard.press('ArrowRight');
	await expect(page.getByText(/^Problem 1 of \d+ · at /)).toBeVisible();
	await page.keyboard.press('Escape');
	await expect(page.getByRole('button', { name: 'Wall display' })).toBeVisible();
	await expect(page).not.toHaveURL(/wall=1/);
});
