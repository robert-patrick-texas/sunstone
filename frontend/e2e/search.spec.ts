import { expect, test, type Page } from '@playwright/test';

const details = (page: Page) => page.getByRole('complementary', { name: 'Details' });
const heading = (page: Page) => details(page).getByRole('heading', { level: 2 });
const box = (page: Page) => page.getByRole('combobox', { name: 'Search' });
const results = (page: Page) => page.getByRole('listbox', { name: 'Search results' });
const view = (page: Page, name: string) => page.getByRole('button', { name, exact: true });

async function searchFor(page: Page, text: string): Promise<void> {
	await box(page).fill(text);
	await page.keyboard.press('Enter');
}

test.beforeEach(async ({ page }) => {
	await page.goto('/');
	await expect(page.getByText('5 sites · 52 devices · 106 links')).toBeVisible();
});

test('finds a circuit by its ID and a link by the interface at one end', async ({ page }) => {
	await box(page).fill('me-595185');
	await expect(results(page).getByRole('option').first()).toContainText('Circuit ME-595185');
	await page.keyboard.press('Enter');
	await expect(heading(page)).toHaveText('Link');
	await expect(details(page)).toContainText('ME-595185');

	// Full or short interface names, with the device to say which end.
	await box(page).fill('dal-core-01 Hu1/0/5');
	await expect(results(page).getByRole('option').first()).toContainText(
		'dal-core-01 Hu1/0/5 – dal-dist-01 Hu1/0/1'
	);
	await box(page).fill('dal-core-01 hundredgige1/0/5');
	await expect(results(page).getByRole('option').first()).toContainText('dal-dist-01 Hu1/0/1');
});

test('finds devices by address and address range, best match first', async ({ page }) => {
	await box(page).fill('10.1.0.3');
	await expect(results(page).getByRole('option').first()).toContainText('dal-core-01');
	await box(page).fill('10.1.0.0/30');
	// 10.1.0.0 to 10.1.0.3: the two WAN routers and a core switch.
	await expect(results(page).getByRole('option')).toHaveCount(3);
	await page.keyboard.press('ArrowDown');
	await page.keyboard.press('Enter');
	await expect(heading(page)).toHaveText('dal-wan-02');
});

test('offers what was looked at recently before anything is typed', async ({ page }) => {
	await searchFor(page, 'hou-dist-01');
	await searchFor(page, 'AUS');
	await box(page).focus();
	const recent = results(page).getByRole('option');
	await expect(recent).toHaveText([/AUS · Austin/, /hou-dist-01/]);
	await recent.nth(1).click();
	await expect(heading(page)).toHaveText('hou-dist-01');

	// Remembered across visits, until cleared.
	await page.reload();
	await box(page).focus();
	await expect(results(page).getByRole('option').first()).toContainText('hou-dist-01');
	await page.getByRole('button', { name: 'Clear' }).click();
	await expect(results(page)).toBeHidden();
	await expect(page.getByText('Type a device, site, address')).toBeVisible();
});

test('runs commands from search, and lists them with their keys', async ({ page }) => {
	await box(page).fill('hierarchy');
	await expect(results(page).getByRole('option').first()).toContainText('Hierarchy view');
	await expect(results(page).getByRole('option').first().locator('kbd')).toHaveText('2');
	await page.keyboard.press('Enter');
	await expect(view(page, 'Hierarchy')).toHaveAttribute('aria-pressed', 'true');
});

test('keys switch views, toggle live, step through problems and time', async ({ page }) => {
	await page.keyboard.press('3');
	await expect(view(page, 'Topology')).toHaveAttribute('aria-pressed', 'true');
	await page.keyboard.press('1');
	await expect(view(page, 'Geographic')).toHaveAttribute('aria-pressed', 'true');

	// Keys are for typing while in a box.
	await box(page).fill('2');
	await expect(view(page, 'Geographic')).toHaveAttribute('aria-pressed', 'true');
	await page.keyboard.press('Escape');

	await page.keyboard.press('l');
	await expect(page.getByText(/simulated · as of/)).toBeVisible();
	// The simulated network always has a device down, so there is a problem to step to.
	await page.keyboard.press('j');
	const problems = page.getByRole('region', { name: 'Problems' });
	await expect(problems.locator('button[aria-pressed="true"]')).toHaveCount(1);
	await expect(page).toHaveURL(/problem=/);

	await page.keyboard.press('[');
	await expect(page.getByText(/simulated · replaying/)).toBeVisible();
	await page.keyboard.press(']');
	await expect(page.getByText(/simulated · as of/)).toBeVisible();
});

test('? lists every shortcut', async ({ page }) => {
	await page.keyboard.press('?');
	const help = page.getByRole('dialog', { name: 'Keyboard shortcuts' });
	await expect(help).toBeVisible();
	await expect(help).toContainText('Next problem');
	// Modal: keys do nothing else while it is open.
	await page.keyboard.press('2');
	await expect(view(page, 'Geographic')).toHaveAttribute('aria-pressed', 'true');
	await page.keyboard.press('Escape');
	await expect(help).toBeHidden();
	await page.getByRole('button', { name: 'Keyboard shortcuts' }).click();
	await expect(help).toBeVisible();
});

test('Back and Forward go between places, without reloading', async ({ page }) => {
	await page.evaluate(() => Object.assign(window, { stillHere: true }));
	await searchFor(page, 'hou-dist-01');
	await searchFor(page, 'dal-core-01');
	await page.keyboard.press('2');
	await expect(view(page, 'Hierarchy')).toHaveAttribute('aria-pressed', 'true');

	await page.goBack();
	await expect(view(page, 'Geographic')).toHaveAttribute('aria-pressed', 'true');
	await expect(heading(page)).toHaveText('dal-core-01');
	await page.goBack();
	await expect(heading(page)).toHaveText('hou-dist-01');
	await page.goForward();
	await expect(heading(page)).toHaveText('dal-core-01');
	expect(await page.evaluate(() => 'stillHere' in window)).toBe(true);

	// Clearing the selection stays in place: Back goes to what was before.
	await page.keyboard.press('Escape');
	await expect(heading(page)).toBeHidden();
	await page.goBack();
	await expect(heading(page)).toHaveText('hou-dist-01');
});

test('Back works after a reload too', async ({ page }) => {
	await searchFor(page, 'hou-dist-01');
	await searchFor(page, 'dal-core-01');
	await page.reload();
	await expect(heading(page)).toHaveText('dal-core-01');
	await page.goBack();
	await expect(heading(page)).toHaveText('hou-dist-01');
	await expect(page).toHaveURL(/select=device:hou-dist-01/);
});
