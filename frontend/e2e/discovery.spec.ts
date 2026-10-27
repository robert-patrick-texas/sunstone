import { expect, test, type Page } from '@playwright/test';

const details = (page: Page) => page.getByRole('complementary', { name: 'Details' });
const discovery = (page: Page) => page.getByRole('region', { name: 'Discovery' });

async function searchFor(page: Page, text: string): Promise<void> {
	await page.getByRole('combobox', { name: 'Search' }).fill(text);
	await page.keyboard.press('Enter');
}

test.beforeEach(async ({ page }) => {
	await page.goto('/');
	await expect(page.getByText('5 sites · 52 devices · 106 links')).toBeVisible();
});

test('discovery lists where the network and the documentation disagree', async ({ page }) => {
	await page.keyboard.press('d');
	await expect(discovery(page).getByText(/of 106 documented links confirmed/)).toBeVisible();
	await expect(discovery(page).getByText(/devices\s+answered/)).toBeVisible();
	// The simulator seeds a disagreement of each kind; whichever discovery can see now.
	const first = discovery(page).getByRole('button').first();
	const detail = (await first.locator('.detail').textContent()) ?? '';
	await first.click();
	await expect(first).toHaveAttribute('aria-pressed', 'true');
	await expect(details(page).getByRole('heading', { name: 'Discovery' })).toBeVisible();
	await expect(details(page)).toContainText(detail);
});

test('a device and a link say what discovery found', async ({ page }) => {
	await searchFor(page, 'hou-dist-01');
	const section = details(page).getByRole('heading', { name: 'Discovery' });
	await expect(section).toBeVisible();
	await expect(
		details(page).getByText(/documented links confirmed|did not answer the latest run/)
	).toBeVisible();

	await searchFor(page, 'ME-595185');
	await expect(section).toBeVisible();
	await expect(
		details(page).getByText(/^(Confirmed|Seen elsewhere|Not seen|Down, so not seen|Not checked)$/)
	).toBeVisible();
});

test('the d key and search both open discovery', async ({ page }) => {
	await page.getByRole('combobox', { name: 'Search' }).fill('lldp');
	await expect(page.getByRole('option').first()).toContainText(
		'Discovery against the documentation'
	);
	await page.keyboard.press('Enter');
	await expect(discovery(page)).toBeVisible();
	await page.keyboard.press('d');
	await expect(discovery(page)).toHaveCount(0);
});
