/**
 * Rules, on the layered sample: overrides on everything that matches, made
 * from a discovery offer, from the Overrides tab, and like an override on
 * one object; previewed, taken out of one object, and withdrawn. Each test
 * withdraws what it made.
 */
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

const details = (page: Page) => page.getByRole('complementary', { name: 'Details' });
const heading = (page: Page) => details(page).getByRole('heading', { level: 2 });
const discovery = (page: Page) => page.getByRole('region', { name: 'Discovery' });
const tab = (page: Page) => page.getByRole('region', { name: 'Overrides' });
const form = (page: Page) => page.getByRole('form', { name: 'New rule' });
const preview = (page: Page) => form(page).getByRole('region', { name: 'Preview' });
const field = (page: Page, label: string) => form(page).getByLabel(label, { exact: true });

const CHAIN = 'Undocumented link elp-acc-01 – elp-acc-02';
const UPLINK = 'iad-gry-01 – iad-gsw-01 on another port';

async function searchFor(page: Page, text: string): Promise<void> {
	await page.getByRole('combobox', { name: 'Search' }).fill(text);
	await page.keyboard.press('Enter');
}

/** Make the rule the open form shows, signed by Pat. */
async function makeRule(page: Page): Promise<void> {
	await field(page, 'Your name').fill('Pat');
	await form(page).getByRole('button', { name: 'Make rule' }).click();
	await expect(form(page)).toHaveCount(0);
}

async function withdrawAll(request: APIRequestContext): Promise<void> {
	const listed = (await (await request.get('/api/overrides')).json()) as {
		overrides: { id: string }[];
		rules: { id: string }[];
	};
	for (const o of listed.overrides) {
		await request.post(`/api/overrides/${o.id}/withdraw`, { data: { by: 'e2e' } });
	}
	for (const r of listed.rules) {
		await request.post(`/api/rules/${r.id}/withdraw`, { data: { by: 'e2e' } });
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

test('a rule discovery offers sets aside daisy chains on port 48, as its preview says', async ({
	page
}) => {
	await page.keyboard.press('d');
	const findings = discovery(page).locator('button.finding');
	await expect(findings.filter({ hasText: CHAIN })).toHaveCount(1);
	await discovery(page)
		.getByRole('button', { name: /^Rule: ignore \*-acc-\* on Gi1\/0\/48 of every access device…/ })
		.first()
		.click();
	await expect(field(page, 'Interface')).toHaveValue('Gi1/0/48');
	await expect(field(page, 'Role')).toHaveValue('access');
	await expect(field(page, 'Neighbors named')).toHaveValue('*-acc-*');
	await expect(preview(page)).toContainText('Matches 53 devices');
	await expect(preview(page)).toContainText(/Would set aside 1 finding/);
	await expect(preview(page)).toContainText(CHAIN);
	await expect(preview(page)).not.toContainText(UPLINK);

	// Any neighbor on any port 48 would set aside a real uplink finding too.
	await field(page, 'Interface').fill('*/0/48');
	await field(page, 'Neighbors named').fill('*');
	await expect(preview(page)).toContainText(UPLINK);
	await field(page, 'Interface').fill('Gi1/0/48');
	await field(page, 'Neighbors named').fill('*-acc-*');
	await expect(preview(page)).not.toContainText(UPLINK);
	await makeRule(page);
	await expect(findings.filter({ hasText: CHAIN })).toHaveCount(0);
	await expect(findings.filter({ hasText: UPLINK })).toHaveCount(1);

	await page.getByRole('tab', { name: /^Overrides/ }).click();
	await expect(tab(page)).toContainText('Port Gi1/0/48 on every device with role access');
	await expect(tab(page)).toContainText('Applies on 53 devices');
	await tab(page)
		.getByRole('button', { name: /^Withdraw/ })
		.first()
		.click();
	await expect(tab(page).getByText(/^No overrides/)).toBeVisible();
	await page.getByRole('tab', { name: /^Discovery/ }).click();
	await expect(findings.filter({ hasText: CHAIN })).toHaveCount(1);
});

test('a label on two platforms, from the Overrides tab, shows in details and search', async ({
	page
}) => {
	await page.keyboard.press('x');
	await tab(page).getByRole('button', { name: 'New rule…' }).click();
	await field(page, 'On').selectOption({ label: 'Devices' });
	await field(page, 'Platform').fill('ISR4431, C9200-24T');
	await field(page, 'Does').selectOption({ label: 'Label' });
	await field(page, 'Key').fill('lifecycle');
	await field(page, 'Value').fill('EoL 2027');
	await field(page, 'Rule name').fill('EoL 2027');
	await expect(preview(page)).toContainText('Matches 20 devices');
	await makeRule(page);
	await expect(tab(page)).toContainText('Applies on 20 devices');

	await searchFor(page, 'iad-gsw-01');
	await expect(heading(page)).toHaveText('iad-gsw-01');
	await expect(details(page).getByTitle(/From rule EoL 2027/)).toHaveText('lifecycle');
	const rules = details(page).getByText(/^From rule EoL 2027/);
	await expect(rules).toBeVisible();

	// Taken out of the rule here, and put back.
	await details(page).getByRole('button', { name: 'Not here' }).click();
	await expect(details(page).getByText(/Rule EoL 2027 does not apply here/)).toBeVisible();
	await expect(details(page).getByTitle(/From rule EoL 2027/)).toHaveCount(0);
	await page.getByRole('tab', { name: /^Overrides/ }).click();
	await expect(tab(page)).toContainText('Applies on 19 devices');
	await expect(tab(page)).toContainText(/Not on iad-gsw-01/);
	await tab(page).getByRole('button', { name: 'Apply here again' }).click();
	await expect(tab(page)).toContainText('Applies on 20 devices');
});

test('an override on the object wins over a rule, and details say so', async ({
	page,
	request
}) => {
	const own = await request.post('/api/overrides', {
		data: {
			target: { kind: 'device', id: 'iad-gsw-01' },
			kind: 'label',
			key: 'lifecycle',
			value: 'Keep',
			by: 'Sam'
		}
	});
	expect(own.ok()).toBeTruthy();
	const made = await request.post('/api/rules', {
		data: {
			name: 'EoL 2027',
			match: { of: 'device', platform: ['C9200-24T'] },
			kind: 'label',
			key: 'lifecycle',
			value: 'EoL 2027',
			by: 'Pat'
		}
	});
	expect(made.ok()).toBeTruthy();
	await page.reload();
	await searchFor(page, 'iad-gsw-01');
	await expect(heading(page)).toHaveText('iad-gsw-01');
	await expect(details(page).getByText(/From rule EoL 2027.*overridden here/)).toBeVisible();
	await expect(details(page).getByTitle('A label given here')).toHaveText('lifecycle');
});

test('a rule like an override on one port starts from its device and port', async ({
	page,
	request
}) => {
	const own = await request.post('/api/overrides', {
		data: {
			target: { kind: 'port', id: 'elp-acc-01', interface: 'GigabitEthernet1/0/48' },
			kind: 'ignore-neighbor',
			value: 'elp-acc-02',
			by: 'Sam'
		}
	});
	expect(own.ok()).toBeTruthy();
	await page.reload();
	await searchFor(page, 'elp-acc-01');
	await expect(heading(page)).toHaveText('elp-acc-01');
	await details(page)
		.getByRole('button', { name: /^Make a rule like this/ })
		.click();
	await expect(field(page, 'On')).toHaveValue('port');
	await expect(field(page, 'Interface')).toHaveValue('Gi1/0/48');
	await expect(field(page, 'Role')).toHaveValue('access');
	await expect(field(page, 'Neighbors named')).toHaveValue('elp-acc-02');
	await expect(preview(page)).toContainText(/Matches \d+ devices/);
	await form(page).getByRole('button', { name: 'Cancel' }).click();
	await expect(form(page)).toHaveCount(0);
});

test('IP phones that say they are bridges are set aside by one rule', async ({ page }) => {
	await page.keyboard.press('d');
	const phones = discovery(page)
		.locator('button.finding')
		.filter({ hasText: /neighbor SEP/ });
	await expect(phones).toHaveCount(2);
	await page.keyboard.press('x');
	await tab(page).getByRole('button', { name: 'New rule…' }).click();
	await field(page, 'On').selectOption({ label: 'Ports' });
	await field(page, 'Role').fill('access');
	await field(page, 'Interface').fill('*');
	await field(page, 'Does').selectOption({ label: 'Ignore neighbors' });
	await field(page, 'Neighbors named').fill('SEP*');
	await field(page, 'Rule name').fill('IP phones');
	await expect(preview(page)).toContainText(/Would set aside 2 findings/);
	await makeRule(page);
	await page.getByRole('tab', { name: /^Discovery/ }).click();
	await expect(phones).toHaveCount(0);
});
