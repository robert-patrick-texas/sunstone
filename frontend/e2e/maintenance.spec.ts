import { expect, test, type Page } from '@playwright/test';

const details = (page: Page) => page.getByRole('complementary', { name: 'Details' });
const impact = (page: Page) => page.getByRole('region', { name: 'Impact' });
const problems = (page: Page) => page.getByRole('region', { name: 'Problems' });

async function open(page: Page): Promise<void> {
	await page.goto('/');
	await expect(page.getByText('5 sites · 52 devices · 106 links')).toBeVisible();
}

/** A datetime-local value some minutes from now, in the browser's time zone. */
function minutesFromNow(page: Page, minutes: number): Promise<string> {
	return page.evaluate((m) => {
		const at = new Date(Date.now() + m * 60_000);
		return new Date(at.getTime() - at.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
	}, minutes);
}

test('maintenance on a switch is checked first, then shown as planned work', async ({ page }) => {
	await open(page);
	await page.getByRole('searchbox', { name: 'Search sites and devices' }).fill('dal-dist-01');
	await page.keyboard.press('Enter');
	await details(page).getByRole('button', { name: 'Plan maintenance…' }).click();

	const form = page.getByRole('form', { name: 'Plan maintenance' });
	await form.getByLabel('What').fill('Replace line card');
	// Opened ten minutes ago, so the work is under way now.
	await form.getByLabel('Starts').fill(await minutesFromNow(page, -10));
	await form.getByLabel('Ends').fill(await minutesFromNow(page, 50));
	await form.getByLabel('Your name').fill('Pat');
	await form.getByRole('button', { name: 'Check impact' }).click();
	await expect(impact(page).getByText('6 devices at DAL depend on dal-dist-02')).toBeVisible();
	await form.getByRole('button', { name: 'Save' }).click();

	const maintenance = page.getByRole('region', { name: 'Maintenance' });
	await expect(maintenance.getByText('Open now (1)')).toBeVisible();
	await expect(maintenance.getByText('Replace line card')).toBeVisible();
	await expect(details(page).getByText('Open now')).toBeVisible();

	// Live, the simulator takes the switch down, and the problem says why.
	await page.getByRole('button', { name: 'Live' }).click();
	await page.getByRole('tab', { name: /^Problems/ }).click();
	await expect(problems(page).getByRole('button', { name: /dal-dist-01 down/ })).toContainText(
		'Planned: Replace line card'
	);

	// Deleting asks once more.
	await page.getByRole('tab', { name: /^Maintenance/ }).click();
	await maintenance.getByRole('button', { name: 'Delete' }).click();
	await maintenance.getByRole('button', { name: 'Really delete?' }).click();
	await expect(maintenance.getByText('Replace line card')).toHaveCount(0);
});

test('a problem is acknowledged with a note, then the acknowledgement withdrawn', async ({
	page
}) => {
	await open(page);
	await page.getByRole('button', { name: 'Live' }).click();
	const first = problems(page).getByRole('button').first();
	const title = (await first.locator('.title').textContent()) ?? '';
	await first.click();
	await impact(page).getByLabel('Note').fill('Carrier ticket 4411');
	await impact(page).getByLabel('Your name').fill('Pat');
	await impact(page).getByRole('button', { name: 'Acknowledge' }).click();

	await expect(impact(page).getByText(/Pat since .*: Carrier ticket 4411/)).toBeVisible();
	const acked = problems(page).getByRole('button', { name: new RegExp(title) });
	await expect(acked).toContainText('On it: Pat · Carrier ticket 4411');

	await impact(page).getByRole('button', { name: 'Withdraw' }).click();
	await expect(acked).not.toContainText('On it');
	await expect(impact(page).getByRole('button', { name: 'Acknowledge' })).toBeVisible();
});
