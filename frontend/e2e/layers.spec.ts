/**
 * Named networks, transports, tunnels, and fabrics, on the layered sample.
 */
import { expect, test, type Page } from '@playwright/test';

const details = (page: Page) => page.getByRole('complementary', { name: 'Details' });
const heading = (page: Page) => details(page).getByRole('heading', { level: 2 });

async function searchFor(page: Page, text: string): Promise<void> {
	await page.getByRole('combobox', { name: 'Search' }).fill(text);
	await page.keyboard.press('Enter');
}

test.beforeEach(async ({ page }) => {
	await page.goto('/');
	await expect(page.getByText(/^22 sites · 116 devices/)).toBeVisible();
});

test('a network found by search is shown in every view and in the link', async ({ page }) => {
	await searchFor(page, 'grey');
	await expect(heading(page)).toHaveText('grey');
	await expect(details(page).getByText('Rides')).toBeVisible();
	await expect(details(page).getByRole('button', { name: 'blue2' })).toBeVisible();
	await expect(details(page).getByRole('button', { name: 'red-alpha' })).toBeVisible();
	// The header shows which networks are shown, and the link carries them.
	await expect(page.getByRole('button', { name: 'grey', exact: true })).toBeVisible();
	await expect(page).toHaveURL(/network=grey/);
	await expect(page).toHaveURL(/select=network:grey/);
	await expect(page.getByText('Over another')).toBeVisible();
});

test('the logical view shows a network over what it rides', async ({ page }) => {
	await page.getByRole('button', { name: 'Logical' }).click();
	await expect(page.getByRole('status')).toHaveText(/All networks · \d+ sites/);
	await page.getByRole('button', { name: 'Networks', exact: true }).click();
	const menu = page.getByRole('dialog', { name: 'Networks' });
	await menu.getByRole('listitem').filter({ hasText: 'red-alpha' }).getByRole('checkbox').check();
	await expect(page.getByRole('status')).toHaveText(
		'red-alpha · over grey, blue, blue2, black, faintly · 5 sites'
	);
	await page.getByLabel('Show what they ride').uncheck();
	await expect(page.getByRole('status')).toHaveText('red-alpha · 5 sites');
	await expect(page).toHaveURL(/view=logical/);
	await expect(page).toHaveURL(/network=red-alpha/);
});

test('a transport lists its circuits, and a circuit names its transport', async ({ page }) => {
	await searchFor(page, 'INET');
	await expect(heading(page)).toHaveText('INET');
	await expect(details(page).getByText('Outside the boundary')).toBeVisible();
	await expect(details(page).getByText(/from 19 sites/)).toBeVisible();
	await details(page).getByRole('row').filter({ hasText: 'hou-wsw-02 Gi0/0/1' }).click();
	await expect(heading(page)).toHaveText('Link');
	// A circuit's ends are its A and Z sides, as carriers name them.
	await expect(details(page).getByRole('columnheader', { name: 'A side' })).toBeVisible();
	await expect(details(page).getByRole('columnheader', { name: 'Z side' })).toBeVisible();
	await expect(
		details(page).getByText('discovery does not compare circuits into a transport yet')
	).toBeVisible();
	await expect(details(page).getByRole('button', { name: 'INET' })).toBeVisible();
	await details(page).getByRole('button', { name: 'INET' }).click();
	await expect(heading(page)).toHaveText('INET');
});

test("a tenant's encryptor is outside the boundary, at a grey site", async ({ page }) => {
	await searchFor(page, 'alpha-tpa-1');
	await expect(heading(page)).toHaveText('alpha-tpa-1');
	await expect(details(page).getByText('known from our end only')).toBeVisible();
	await expect(details(page).getByRole('button', { name: 'tpa-gsw-01' })).toBeVisible();
	await details(page).getByRole('button', { name: 'Alpha', exact: true }).click();
	await expect(heading(page)).toHaveText('Alpha');
	await expect(details(page).getByRole('button', { name: 'red-alpha' })).toBeVisible();
});

test('a fabric lists its hubs and spokes', async ({ page }) => {
	await searchFor(page, 'DMVPN-INET');
	await expect(heading(page)).toHaveText('DMVPN-INET');
	await expect(details(page).getByText('Hubs and spokes, spoke to spoke on demand')).toBeVisible();
	await expect(details(page).getByRole('row').filter({ hasText: 'hub' })).toHaveCount(2);
});

test("a cable's ends are its A and B ends", async ({ page }) => {
	await searchFor(page, 'tpa-wsw-01');
	await details(page).getByRole('row').filter({ hasText: 'tpa-gry-01' }).click();
	await expect(heading(page)).toHaveText('Link');
	await expect(details(page).getByRole('columnheader', { name: 'A end' })).toBeVisible();
	await expect(details(page).getByRole('columnheader', { name: 'B end' })).toBeVisible();
});
