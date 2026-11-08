/**
 * Named networks, transports, tunnels, and fabrics, on the layered sample.
 */
import { expect, test, type Locator, type Page } from '@playwright/test';

const details = (page: Page) => page.getByRole('complementary', { name: 'Details' });
const heading = (page: Page) => details(page).getByRole('heading', { level: 2 });
/** A network's row in a "what if" answer, by its name alone: others' notes name it too. */
const networkRow = (impact: Locator, name: string) =>
	impact.getByRole('row').filter({ has: impact.page().getByRole('cell', { name, exact: true }) });

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

test('with live state, networks say whether they work, and why', async ({ page }) => {
	await page.goto('/?live=1&network=grey&select=network:grey');
	await expect(details(page).getByText(/\d+ of 10 sites reached/)).toBeVisible();
	// Some network always has something down in the simulation, though not
	// always the whole: a device down inside a site stays the site's.
	await expect(page.getByRole('heading', { name: /^Networks \(\d+\)$/ })).toBeVisible();
	await expect(
		page.getByRole('button', { name: /^[\w-]+ (degraded|offline|operational\*)/ }).first()
	).toBeVisible();
	await page.getByRole('button', { name: /^grey/ }).first().click();
	const menu = page.getByRole('dialog', { name: 'Networks' });
	await expect(menu.getByText(/^(Operational\*?|Degraded|Offline)$/).first()).toBeVisible();
});

test('what if a WAN switch fails, through every network it reaches', async ({ page }) => {
	await page.goto('/?select=device:hou-wsw-01');
	await details(page).getByRole('button', { name: 'What if it fails?' }).click();
	const impact = details(page).getByRole('region', { name: 'Impact' });
	await expect(networkRow(impact, 'black')).toContainText('2 of 4 circuits at HOU');
	await expect(networkRow(impact, 'blue')).toContainText('Stays up, over black degraded at HOU');
	await expect(networkRow(impact, 'grey')).toContainText('Operational*');
});

test('a carrier failing takes all its circuits, and the tunnels over them', async ({ page }) => {
	const circuit = 'links:dal-wan-02:GigabitEthernet0/0/0--transport:Mesa MPLS';
	await page.goto(`/?select=${encodeURIComponent(circuit)}`);
	await details(page).getByRole('button', { name: 'What if Mesa Carrier fails?' }).click();
	const impact = details(page).getByRole('region', { name: 'Impact' });
	await expect(impact.getByText('Mesa Carrier (20 circuits)')).toBeVisible();
	await expect(networkRow(impact, 'corp')).toContainText(
		'28 of 58 tunnels · BNA, FTW, and MEM cut off'
	);
	await expect(networkRow(impact, 'blue2')).toContainText('Offline');
	await expect(page).toHaveURL(/fail=provider:Mesa\+Carrier/);
	// Showing the networks that lose tunnels draws them lost on the map.
	await impact.getByRole('button', { name: 'Show their tunnels' }).click();
	await expect(page).toHaveURL(/network=/);
});

test("a network's shared risks, and what one of them failing does", async ({ page }) => {
	await searchFor(page, 'grey');
	await expect(heading(page)).toHaveText('grey');
	await expect(details(page).getByRole('heading', { name: 'Shared risk (15)' })).toBeVisible();
	const first = details(page).locator('table.risks tr').first();
	await expect(first).toContainText('Northwind Fiber');
	await expect(first).toContainText('6 of 15 tunnels · cuts off ATL, CLT, and RDU');
	await first.getByRole('button', { name: 'What if Northwind Fiber fails' }).click();
	const impact = details(page).getByRole('region', { name: 'Impact' });
	await expect(impact.getByText('Northwind Fiber (8 circuits)')).toBeVisible();
	await expect(networkRow(impact, 'grey')).toContainText('6 of 15 tunnels');
	// A tunnel's details name what it shares with which others.
	await page.goto('/?select=tunnel:GREY-HOU-DAL');
	const shared = details(page).locator('table.risks tr').filter({ hasText: 'hou-blu-01' });
	await expect(shared).toContainText('with GREY-HOU-IAD · cuts off HOU');
});
