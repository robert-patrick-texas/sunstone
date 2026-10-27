import { expect, test } from '@playwright/test';

test.beforeEach(async ({ page }) => {
	await page.goto('/');
	await expect(page.getByText('5 sites · 52 devices · 106 links')).toBeVisible();
});

test('the shift handover opens with h, covers 12 or 8 hours, and closes again', async ({
	page
}) => {
	await page.keyboard.press('h');
	const report = page.getByLabel('Shift handover');
	await expect(report.getByRole('heading', { name: 'Shift handover' })).toBeVisible();
	await expect(page).toHaveURL(/handover=12/);
	await expect(report.getByText(/· the last 12 h$/)).toBeVisible();
	for (const section of ['Open now', 'On call now', 'Outages', 'Maintenance', 'Documentation']) {
		await expect(report.getByRole('region', { name: section })).toBeVisible();
	}
	// The simulator has something go down in any 8 hours.
	await expect(report.getByText(/^Began or ended in these hours:/)).toBeVisible();

	await report.getByRole('button', { name: '8 h' }).click();
	await expect(page).toHaveURL(/handover=8/);
	await expect(report.getByText(/· the last 8 h$/)).toBeVisible();
	await page.keyboard.press('Escape');
	await expect(report).toHaveCount(0);
	await expect(page).not.toHaveURL(/handover/);

	// A link opens it again, and so does search.
	await page.goto('/?handover=12');
	await expect(report.getByRole('heading', { name: 'Shift handover' })).toBeVisible();
	await report.getByRole('button', { name: 'Close' }).click();
	await page.getByRole('combobox', { name: 'Search' }).fill('handover');
	await expect(page.getByRole('option').first()).toContainText('Shift handover');
	await page.keyboard.press('Enter');
	await expect(report).toBeVisible();
});

test('an outage in the handover replays the moment it began', async ({ page }) => {
	await page.goto('/?handover=12');
	const outages = page.getByLabel('Shift handover').getByRole('region', { name: 'Outages' });
	const first = outages.locator('button.row').first();
	const what = (await first.locator('.what').textContent()) ?? '';
	await first.click();
	await expect(page.getByLabel('Shift handover')).toHaveCount(0);
	await expect(page).toHaveURL(/live=1&at=/);
	await expect(page.getByText(/simulated · replaying/)).toBeVisible();
	const name = what.replace(/ down$/, '').replace(/:.*$/, '');
	await expect(page.getByRole('complementary', { name: 'Details' })).toContainText(name);
});

test('notes go with the next handover, and each shift change is saved with its message', async ({
	page
}) => {
	await page.goto('/?handover=12');
	const report = page.getByLabel('Shift handover');
	const notes = report.getByRole('region', { name: 'Notes for the next shift' });
	await expect(notes.getByText(/^handed over at /)).toBeVisible();
	await notes.getByLabel('Note for the next shift').fill('Bluebonnet expects HOU back by 10:00');
	await notes.getByLabel('Your name').fill('Pat');
	await notes.getByRole('button', { name: 'Add note' }).click();
	const written = notes.locator('li', { hasText: 'Bluebonnet expects HOU back by 10:00' });
	await expect(written).toContainText('Pat');

	await report.getByRole('button', { name: 'Message' }).click();
	const message = report.getByRole('region', { name: 'Message' });
	await expect(message.locator('pre')).toContainText('Bluebonnet expects HOU back by 10:00 (Pat,');
	await expect(message.locator('pre')).toContainText(/In Sunstone: http\S+\?handover=12$/);
	await message.getByRole('button', { name: 'Copy message' }).click();
	await expect(message.getByRole('button')).toHaveText(
		/^(Message copied|Select it below to copy it)$/
	);

	await written.getByRole('button', { name: 'Withdraw' }).click();
	await expect(written).toHaveCount(0);

	// History has the last shift change, so its handover is saved.
	const which = report.getByRole('combobox', { name: 'Which handover' });
	await expect(which.locator('option')).not.toHaveCount(1);
	const id = await which.locator('option').nth(1).getAttribute('value');
	await which.selectOption(id ?? '');
	await expect(page).toHaveURL(new RegExp(`handover=${id}`));
	await expect(report.locator('header .span')).toContainText(/^Handed over /);
	for (const section of ['Notes from the outgoing shift', 'Open at handover', 'Outages']) {
		await expect(report.getByRole('region', { name: section })).toBeVisible();
	}
	await expect(report.getByRole('group', { name: 'Covering' })).toHaveCount(0);
	await expect(report.getByLabel('Note for the next shift')).toHaveCount(0);

	await which.selectOption('');
	await expect(page).toHaveURL(/handover=12/);
	await expect(report.getByRole('region', { name: 'Notes for the next shift' })).toBeVisible();
});
