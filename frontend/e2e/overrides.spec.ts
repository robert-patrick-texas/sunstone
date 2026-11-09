/**
 * Overrides, on the layered sample: made from discovery and from details,
 * listed in their own tab, and withdrawn. Each test withdraws what it made.
 */
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

const details = (page: Page) => page.getByRole('complementary', { name: 'Details' });
const heading = (page: Page) => details(page).getByRole('heading', { level: 2 });
const discovery = (page: Page) => page.getByRole('region', { name: 'Discovery' });
const tab = (page: Page) => page.getByRole('region', { name: 'Overrides' });

async function searchFor(page: Page, text: string): Promise<void> {
	await page.getByRole('combobox', { name: 'Search' }).fill(text);
	await page.keyboard.press('Enter');
}

/** Make the override the form open shows, signed by Pat. */
async function override(page: Page): Promise<void> {
	const form = page.getByRole('form', { name: /^Override / });
	await form.getByLabel('Your name').fill('Pat');
	await form.getByRole('button', { name: 'Override', exact: true }).click();
	await expect(form).toHaveCount(0);
}

async function withdrawAll(request: APIRequestContext): Promise<void> {
	const listed = (await (await request.get('/api/overrides')).json()) as {
		overrides: { id: string }[];
	};
	for (const o of listed.overrides) {
		await request.post(`/api/overrides/${o.id}/withdraw`, { data: { by: 'e2e' } });
	}
}

test.beforeEach(async ({ page, request }) => {
	await withdrawAll(request);
	await page.goto('/');
	await expect(page.getByText(/^22 sites · 116 devices/)).toBeVisible();
});

test.afterEach(async ({ request }) => {
	await withdrawAll(request);
});

test("an alias from discovery settles a switch's old hostname at every port", async ({ page }) => {
	await page.keyboard.press('d');
	const findings = discovery(page).locator('button.finding');
	await expect(findings.filter({ hasText: 'Another device on bhm-wan-01 Gi0/0/1' })).toHaveCount(1);
	await expect(findings.filter({ hasText: 'Another device on bhm-wan-02 Gi0/0/1' })).toHaveCount(1);
	await discovery(page).getByRole('button', { name: 'bhm-sw-70 is bhm-acc-01…' }).first().click();
	await override(page);
	// Both of its uplinks' findings go: discovery matches the old name now.
	await expect(findings.filter({ hasText: /Another device on bhm-wan-0[12]/ })).toHaveCount(0);

	await page.getByRole('tab', { name: /^Overrides/ }).click();
	const item = tab(page).locator('[data-override]');
	await expect(item).toHaveCount(1);
	await expect(item).toContainText('bhm-acc-01');
	await expect(item).toContainText('Also known as bhm-sw-70');
	await item.getByRole('button', { name: /^Withdraw/ }).click();
	await expect(tab(page).getByText(/^No overrides/)).toBeVisible();
	await page.getByRole('tab', { name: /^Discovery/ }).click();
	await expect(findings.filter({ hasText: /Another device on bhm-wan-0[12]/ })).toHaveCount(2);
});

test('a customer-managed device renamed shows its new name and is found by it', async ({
	page
}) => {
	await searchFor(page, 'bravo-iad-1');
	await expect(heading(page)).toHaveText('bravo-iad-1');
	await details(page).getByRole('button', { name: 'Override…' }).click();
	const form = page.getByRole('form', { name: /^Override / });
	await form.getByLabel('Kind').selectOption({ label: 'Rename' });
	await form.getByLabel('New name').fill('BRV-IAD-ENC01');
	await override(page);
	await expect(heading(page)).toHaveText('BRV-IAD-ENC01');
	await expect(details(page).getByText('bravo-iad-1 in the topology')).toBeVisible();

	await page.keyboard.press('Escape');
	await page.getByRole('combobox', { name: 'Search' }).fill('BRV-IAD');
	await expect(page.getByRole('option').first()).toContainText('BRV-IAD-ENC01');
});

test('a lock keeps a field and says what the topology says', async ({ page }) => {
	await searchFor(page, 'bhm-acc-01');
	await expect(heading(page)).toHaveText('bhm-acc-01');
	await details(page).getByRole('button', { name: 'Override…' }).click();
	const form = page.getByRole('form', { name: /^Override / });
	await form.getByLabel('Kind').selectOption({ label: 'Lock a field' });
	await form.getByLabel('Field').selectOption({ label: 'Role' });
	await form.getByLabel('Value').selectOption('distribution');
	await form.getByLabel('Note').fill('Moved to the distribution tier, source not updated yet');
	await override(page);
	await expect(details(page).getByText(/Locked here · the topology says access/)).toBeVisible();

	await page.keyboard.press('Escape');
	await page.keyboard.press('x');
	await expect(tab(page).getByRole('heading', { name: /^Flagged/ })).toBeVisible();
	await expect(tab(page).locator('[data-override]')).toContainText('Role locked: distribution');
});

test('the handover lists the overrides made in it', async ({ page }) => {
	await searchFor(page, 'bhm-acc-01');
	await details(page).getByRole('button', { name: 'Override…' }).click();
	const form = page.getByRole('form', { name: /^Override / });
	await form.getByLabel('Kind').selectOption({ label: 'Tag' });
	await form.getByLabel('Value').fill('lab');
	await override(page);
	await expect(details(page).getByText('(added here)')).toBeVisible();

	await page.keyboard.press('Escape');
	await page.keyboard.press('h');
	const report = page.getByLabel('Shift handover');
	await expect(report.getByRole('heading', { name: /^Overrides/ })).toBeVisible();
	await expect(report.getByRole('button', { name: /^bhm-acc-01 · Tag lab/ })).toContainText(
		'Made by Pat'
	);
});

test('a site hidden from the map is counted in the legend and can be shown again', async ({
	page
}) => {
	await searchFor(page, 'BHM');
	await details(page).getByRole('button', { name: 'Override…' }).click();
	const form = page.getByRole('form', { name: /^Override / });
	await form.getByLabel('Kind').selectOption({ label: 'Hide from the map' });
	await override(page);
	await expect(
		details(page).getByText(/^Hidden from the map · still found by search/)
	).toBeVisible();
	await expect(page.getByText('1 hidden from the map')).toBeVisible();
	const show = page.getByRole('checkbox', { name: 'Show' });
	await show.check();
	await expect(show).toBeChecked();
	await show.uncheck();
});
