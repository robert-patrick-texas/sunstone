import { expect, test, type Page } from '@playwright/test';

const status = (page: Page) => page.getByRole('status');

async function openTopology(page: Page): Promise<void> {
	await page.goto('/');
	await expect(page.getByText('5 sites · 52 devices · 106 links')).toBeVisible();
	await page.getByRole('button', { name: 'Topology' }).click();
	await expect(status(page)).toHaveText('5 sites, 5 expanded');
}

test('a saved layout opens again after reloading the page', async ({ page }) => {
	const name = `e2e ${Date.now()}`;
	await openTopology(page);
	await page.getByRole('combobox', { name: 'Search' }).fill('hou-dist-01');
	await page.keyboard.press('Enter');
	await page.getByRole('button', { name: 'Neighborhood', exact: true }).click();
	await page.getByLabel('Hops').selectOption('1');
	await page.getByRole('button', { name: 'Radial' }).click();
	await expect(status(page)).toHaveText('hou-dist-01 · 1 hop · 8 devices');

	await page.getByRole('button', { name: 'Saved layouts' }).click();
	await page.getByLabel('Layout name').fill(name);
	await page.getByRole('button', { name: 'Save', exact: true }).click();
	await expect(page.getByText(`Saved "${name}".`)).toBeVisible();

	await openTopology(page);
	await page.getByRole('button', { name: 'Saved layouts' }).click();
	const menu = page.getByRole('dialog', { name: 'Saved layouts' });
	await menu.getByRole('button', { name: new RegExp(`^${name}`) }).click();
	await expect(status(page)).toHaveText('hou-dist-01 · 1 hop · 8 devices');
	await expect(page.getByRole('button', { name: 'Radial' })).toHaveAttribute(
		'aria-pressed',
		'true'
	);

	await page.getByRole('button', { name: 'Saved layouts' }).click();
	await menu.getByRole('button', { name: `Delete ${name}` }).click();
	await expect(menu.getByRole('button', { name: new RegExp(`^${name}`) })).toHaveCount(0);
});
