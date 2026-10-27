import { expect, test, type Page } from '@playwright/test';

const details = (page: Page) => page.getByRole('complementary', { name: 'Details' });
const time = (page: Page) => page.getByRole('group', { name: 'Time' });
const replaying = (page: Page) => page.getByText(/simulated · replaying/);

async function goLive(page: Page): Promise<void> {
	await page.goto('/');
	await expect(page.getByText('5 sites · 52 devices · 106 links')).toBeVisible();
	await page.getByRole('button', { name: 'Live' }).click();
	await expect(time(page).getByRole('slider', { name: 'Moment to show' })).toBeVisible();
}

test('the time slider replays an earlier moment, then follows the present again', async ({
	page
}) => {
	await goLive(page);
	const slider = time(page).getByRole('slider', { name: 'Moment to show' });
	await expect(slider).toHaveAttribute('aria-valuetext', 'Now');
	await time(page).getByRole('button', { name: '5 minutes earlier' }).click();
	await expect(replaying(page)).toBeVisible();
	await expect(slider).toHaveAttribute('aria-valuetext', /min ago$/);

	await time(page).getByRole('button', { name: 'Back to now' }).click();
	await expect(page.getByText(/simulated · as of/)).toBeVisible();
	await expect(slider).toHaveAttribute('aria-valuetext', 'Now');
});

test('an event replays its moment and selects what changed', async ({ page }) => {
	await goLive(page);
	await page.getByRole('tab', { name: /^Events \d+$/ }).click();
	const events = page.getByRole('region', { name: 'Events' });
	const first = events.getByRole('listitem').first().getByRole('button');
	await first.click();
	await expect(first).toHaveAttribute('aria-pressed', 'true');
	await expect(replaying(page)).toBeVisible();
	await expect(details(page)).toBeVisible();

	await events.getByRole('button', { name: 'No data' }).click();
	await expect(events.getByText(/stopped reporting|reporting again/)).toHaveCount(0);
});

test('a monitored device charts its last day, and the chart replays a moment', async ({ page }) => {
	await goLive(page);
	await page.getByRole('combobox', { name: 'Search' }).fill('dal-core-01');
	await page.keyboard.press('Enter');
	const panel = details(page);
	await expect(panel.getByRole('heading', { name: 'Last 24 hours' })).toBeVisible();
	await expect(panel.locator('figcaption')).toContainText('west (DAL)');
	await expect(panel.locator('figcaption')).toContainText('east (IAD)');
	await expect(panel.getByRole('columnheader', { name: '24 h' })).toBeVisible();

	const chart = panel.getByRole('slider', { name: /^Round trip to dal-core-01/ });
	await chart.focus();
	await page.keyboard.press('ArrowLeft');
	await expect(chart).toHaveAttribute('aria-valuetext', /west \(DAL\)/);
	await page.keyboard.press('Enter');
	await expect(replaying(page)).toBeVisible();
});
