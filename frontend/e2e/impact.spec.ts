import { expect, test, type Page } from '@playwright/test';

const details = (page: Page) => page.getByRole('complementary', { name: 'Details' });
const impact = (page: Page) => page.getByRole('region', { name: 'Impact' });
const legend = (page: Page) => page.getByLabel('Legend');

async function searchFor(page: Page, text: string): Promise<void> {
	await page.getByRole('combobox', { name: 'Search' }).fill(text);
	await page.keyboard.press('Enter');
}

test('what if one distribution switch fails, then its pair', async ({ page }) => {
	await page.goto('/');
	await expect(page.getByText('5 sites · 52 devices · 106 links')).toBeVisible();
	await searchFor(page, 'dal-dist-01');
	await expect(
		details(page).getByText('Failing it would leave 6 devices without redundancy.')
	).toBeVisible();

	await details(page).getByRole('button', { name: 'What if it fails?' }).click();
	await expect(impact(page).getByRole('heading', { name: 'What if this fails' })).toBeVisible();
	await expect(impact(page).getByText('No redundancy left (6)')).toBeVisible();
	await expect(impact(page).getByText('6 devices at DAL depend on dal-dist-02')).toBeVisible();
	await expect(legend(page).getByText('Cut off')).toBeVisible();
	await expect(details(page).getByRole('button', { name: 'In what if' })).toBeDisabled();

	await searchFor(page, 'dal-dist-02');
	await details(page).getByRole('button', { name: 'Add to what if' }).click();
	await expect(impact(page).getByRole('heading', { name: 'What if these fail' })).toBeVisible();
	await expect(impact(page).getByText('Cut off (6)')).toBeVisible();
	await expect(impact(page).getByText('No redundancy left')).toHaveCount(0);

	await impact(page).getByRole('button', { name: 'Remove dal-dist-01' }).click();
	await expect(impact(page).getByText('6 devices at DAL depend on dal-dist-01')).toBeVisible();

	await page.getByRole('button', { name: 'Clear what if' }).click();
	await expect(impact(page)).toHaveCount(0);
	await expect(legend(page).getByText('WAN link')).toBeVisible();
});

test('live problems are listed, and one shows what it affects', async ({ page }) => {
	await page.goto('/');
	await expect(page.getByText('5 sites · 52 devices · 106 links')).toBeVisible();
	await page.getByRole('button', { name: 'Live' }).click();
	const side = page.getByRole('complementary', {
		name: 'Problems, events, maintenance, and on call'
	});
	const problems = side.getByRole('region', { name: 'Problems' });
	await expect(side.getByRole('tab', { name: /^Problems \d+$/ })).toBeVisible();

	// A few devices are always down, so an unreachable device heads the list.
	await expect(problems.getByRole('heading', { name: /^Unreachable/ })).toBeVisible();
	const first = problems.getByRole('button').first();
	await first.click();
	await expect(first).toHaveAttribute('aria-pressed', 'true');
	// Outages read "x down", "SITE cut off", or "N devices unreachable at SITE".
	await expect(
		impact(page).getByRole('heading', { name: / down$|cut off$|unreachable/ })
	).toBeVisible();
	await expect(legend(page).getByText('Failed')).toBeVisible();

	await first.click();
	await expect(first).toHaveAttribute('aria-pressed', 'false');
	await expect(impact(page)).toHaveCount(0);

	await page.getByRole('button', { name: /^Problems \d+$/ }).click();
	await expect(side).toHaveCount(0);
});
