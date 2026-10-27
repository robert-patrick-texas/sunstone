import { expect, test, type Page } from '@playwright/test';

const details = (page: Page) => page.getByRole('complementary', { name: 'Details' });
const oncall = (page: Page) => page.getByRole('region', { name: 'On call' });
const paging = (page: Page) => details(page).getByRole('group', { name: 'Paging' });

async function searchFor(page: Page, text: string): Promise<void> {
	await page.getByRole('combobox', { name: 'Search' }).fill(text);
	await page.keyboard.press('Enter');
}

test.beforeEach(async ({ page }) => {
	await page.goto('/');
	await expect(page.getByText('5 sites · 52 devices · 106 links')).toBeVisible();
});

test('the on-call list shows every team, who is on, and the carriers', async ({ page }) => {
	await page.keyboard.press('o');
	const list = oncall(page);
	await expect(list.getByText('Teams (4)')).toBeVisible();
	for (const team of ['WAN and carriers', 'Data centers', 'Network Central', 'NOC']) {
		await expect(list.getByText(team, { exact: true })).toBeVisible();
	}
	await expect(list.getByText('WAN links')).toBeVisible();
	await expect(list.getByText('Mesa Carrier')).toBeVisible();
});

test('a device shows its team and who is on call, and a circuit its carrier', async ({ page }) => {
	await searchFor(page, 'hou-acc-01');
	await expect(details(page).getByRole('heading', { name: 'On call' })).toBeVisible();
	await details(page).getByRole('button', { name: 'Network Central' }).click();
	await expect(oncall(page).locator('[data-team="network-central"]')).toHaveClass(/shown/);

	await searchFor(page, 'ME-595185');
	await expect(details(page).getByText('Mesa Carrier · circuit ME-595185')).toBeVisible();
	await expect(details(page).getByRole('link', { name: '+1 800 555 0102' })).toBeVisible();
});

test('a team is found by search, and so is someone on it', async ({ page }) => {
	await page.getByRole('combobox', { name: 'Search' }).fill('data centers');
	await expect(page.getByRole('option').first()).toContainText('Data centers');
	await page.keyboard.press('Enter');
	await expect(oncall(page).locator('[data-team="datacenter"]')).toHaveClass(/shown/);
});

test('a problem is paged, escalates on paper, and stops when acknowledged', async ({ page }) => {
	await page.keyboard.press('l');
	await expect(page.getByText(/simulated · as of/)).toBeVisible();
	// The simulated network always has a device down, so there is a problem. The
	// last one, since another test acknowledges the first at the same time.
	await page.keyboard.press('k');
	await expect(paging(page).getByText(/A page would go to .* \(primary\) at once/)).toBeVisible();
	// Paging asks for a name only once: in the acknowledgement form above it.
	await details(page).getByRole('textbox', { name: 'Your name' }).fill('Sam');
	await paging(page)
		.getByRole('button', { name: /^Page / })
		.click();
	await expect(paging(page).getByText(/^Paged .* \(primary\) at /)).toBeVisible();
	await expect(
		paging(page).getByText(/unless\s+someone\s+acknowledges\s+it\s+first/)
	).toBeVisible();
	const problems = page.getByRole('region', { name: 'Problems' });
	await expect(problems.getByText(/^Paged: /)).toBeVisible();

	await details(page).getByRole('button', { name: 'Acknowledge' }).click();
	await expect(
		paging(page).getByText('Escalation stopped: someone acknowledged it.')
	).toBeVisible();
	// Withdrawn, the acknowledgement no longer stops the page; then withdraw that too.
	await details(page).getByRole('button', { name: 'Withdraw', exact: true }).click();
	await details(page).getByRole('button', { name: 'Withdraw page' }).click();
	await expect(paging(page).getByText(/A page would go to/)).toBeVisible();
});

test('someone covers a shift, then the cover is removed', async ({ page }) => {
	await page.keyboard.press('o');
	const team = oncall(page).locator('[data-team="network-central"]');
	await team.getByRole('button', { name: 'Cover…' }).click();
	const form = page.getByRole('form', { name: 'Cover Network Central' });
	await form.getByLabel('Who').selectOption({ label: 'Drew Varga' });
	await form.getByLabel('Your name').fill('Pat');
	await form.getByRole('button', { name: 'Save' }).click();
	await expect(
		team.getByRole('definition').filter({ hasText: /Drew Varga\s+\(covering\)/ })
	).toBeVisible();
	await team.getByRole('button', { name: 'Remove' }).click();
	await expect(team.getByText('(covering)')).toHaveCount(0);
});
