import { expect, test, type Page } from '@playwright/test';

const details = (page: Page) => page.getByRole('complementary', { name: 'Details' });
const discovery = (page: Page) => page.getByRole('region', { name: 'Discovery' });
const review = (page: Page) => page.getByRole('form', { name: 'Review fix' });

test.describe.configure({ mode: 'serial' });

test.beforeEach(async ({ page }) => {
	await page.goto('/');
	await expect(page.getByText('5 sites · 52 devices · 106 links')).toBeVisible();
	await page.keyboard.press('d');
	await expect(discovery(page).getByText(/of 106 documented links confirmed/)).toBeVisible();
});

test('a fix is reviewed, accepted into the documentation, and reverted', async ({ page }) => {
	// The simulator seeds a cable on the other switch of a pair, and one on
	// another port; whichever discovery can see now.
	const offered = discovery(page).getByRole('button', { name: /^Fix: Move the end at/ });
	test.skip((await offered.count()) === 0, 'No cable on another port or switch is seen now');
	const fix = offered.first();
	const summary = ((await fix.textContent()) ?? '').replace(/^Fix: /, '');
	await fix.click();
	await expect(review(page).getByText(summary)).toBeVisible();
	await expect(review(page).getByText(/^seen.*: up · \d+% in, \d+% out$/)).toBeVisible();
	await expect(review(page).getByRole('heading', { name: 'What it changes' })).toBeVisible();
	// Documented on both switches of the pair, both uplinks really go to one.
	if (summary.includes('dal-dist-01')) {
		await expect(
			review(page).getByText('dal-acc-05 would depend on dal-dist-02 alone')
		).toBeVisible();
	}
	await review(page).getByLabel('Note').fill('Traced the cable');
	await review(page).getByLabel('Your name').fill('Pat');
	await review(page).getByRole('button', { name: 'Accept fix' }).click();

	await expect(review(page)).toHaveCount(0);
	await expect(discovery(page).getByRole('heading', { name: 'Fixed here (1)' })).toBeVisible();
	await expect(discovery(page).getByText(/· Traced the cable$/)).toBeVisible();
	await expect(discovery(page).getByRole('button', { name: `Fix: ${summary}` })).toHaveCount(0);
	// The fixed link is selected, and says where its documentation comes from.
	await expect(details(page).getByText(/Fixed here by Pat at/)).toBeVisible();
	await expect(page.getByText('5 sites · 52 devices · 106 links')).toBeVisible();

	// Everyone else sees it too.
	await page.reload();
	await expect(page.getByText('5 sites · 52 devices · 106 links')).toBeVisible();
	await page.keyboard.press('d');
	await expect(discovery(page).getByRole('heading', { name: 'Fixed here (1)' })).toBeVisible();
	await discovery(page).getByRole('button', { name: 'Revert' }).click();
	await expect(discovery(page).getByRole('heading', { name: /^Fixed here/ })).toHaveCount(0);
	await expect(discovery(page).getByRole('button', { name: `Fix: ${summary}` })).toBeVisible();
});

test('retiring a link Live shows carrying traffic is warned against', async ({ page }) => {
	const offered = discovery(page).getByRole('button', { name: /^Fix: Retire the link/ });
	test.skip((await offered.count()) === 0, 'The link hidden from LLDP is not checked now');
	await offered.first().click();
	await expect(review(page).getByText(/^Live shows it up and carrying traffic at/)).toBeVisible();
	await review(page).getByRole('button', { name: 'Cancel' }).click();
	await expect(review(page)).toHaveCount(0);
	await expect(discovery(page).getByRole('heading', { name: /^Fixed here/ })).toHaveCount(0);
});

test('a finding with no fix says what people must do instead', async ({ page }) => {
	// Only while the switch with LLDP off answers discovery at all.
	const silent = discovery(page).locator('button.finding:not(.gone)', {
		hasText: 'reports no neighbors'
	});
	test.skip((await silent.count()) === 0, 'The switch with LLDP off does not answer now');
	await silent.click();
	await expect(
		details(page).getByText('Turn LLDP or CDP on, and its links can be checked.')
	).toBeVisible();
});

test('a link LLDP cannot see is marked expected with a note, then withdrawn', async ({ page }) => {
	const retire = discovery(page).getByRole('button', { name: /^Fix: Retire the link/ });
	test.skip((await retire.count()) === 0, 'The link hidden from LLDP is not checked now');
	const offered = await retire.count();
	const item = discovery(page)
		.locator('li')
		.filter({ has: page.getByRole('button', { name: /^Fix: Retire the link/ }) })
		.first();
	const title = (await item.locator('.title').textContent()) ?? '';
	await item.getByRole('button', { name: 'Mark expected…' }).click();
	const form = page.getByRole('form', { name: 'Mark expected' });
	await expect(form.getByText(/: up · \d+% in, \d+% out$/).first()).toBeVisible();
	await form.getByLabel('Note').fill('Media converter in rack 4');
	await form.getByLabel('Your name').fill('Pat');
	await form.getByRole('button', { name: 'Mark expected', exact: true }).click();

	await expect(form).toHaveCount(0);
	await expect(discovery(page).getByRole('heading', { name: 'Expected (1)' })).toBeVisible();
	await expect(discovery(page).getByText(/· Media converter in rack 4$/)).toBeVisible();
	await expect(retire).toHaveCount(offered - 1);
	await expect(discovery(page).getByText(/1 not seen, expected/)).toBeVisible();
	// Nothing to fix in the documentation, so nothing listed as fixed.
	await expect(discovery(page).getByRole('heading', { name: /^Fixed here/ })).toHaveCount(0);
	await expect(details(page).getByText('Not seen, expected')).toBeVisible();
	await expect(details(page).getByText(`Expected: ${title}`)).toBeVisible();

	await discovery(page).getByRole('button', { name: 'Withdraw' }).click();
	await expect(discovery(page).getByRole('heading', { name: /^Expected/ })).toHaveCount(0);
	await expect(retire).toHaveCount(offered);
});
