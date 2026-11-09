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
	await expect(details(page).getByText('Rides', { exact: true })).toBeVisible();
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
	// What it is for at the edge, and what LLDP and CDP show across it.
	await expect(details(page).getByText('Transit, Egress')).toBeVisible();
	await expect(details(page).getByText("The provider's equipment")).toBeVisible();
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
	// Its E-LAN and E-Lines too: corp's MACsec over the E-LAN goes with its MPLS.
	await expect(impact.getByText('Mesa Carrier (24 circuits)')).toBeVisible();
	await expect(networkRow(impact, 'corp')).toContainText(
		'32 of 62 tunnels · BNA, FTW, and MEM cut off'
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

/** A recent moment, every 15 minutes back over the day, where `wanted` finds something. */
async function momentWith<A, T>(
	page: Page,
	ask: (at: string) => string,
	wanted: (answer: A) => T | undefined
): Promise<{ at: string; found: T }> {
	const now = Date.parse((await (await page.request.get('/api/state')).json()).generated_at);
	for (let minutes = 0; minutes < 24 * 60; minutes += 15) {
		const at = new Date(now - minutes * 60_000).toISOString();
		const found = wanted((await (await page.request.get(ask(at))).json()) as A);
		if (found !== undefined) return { at, found };
	}
	throw new Error('no moment in the day has it');
}

interface Lost {
	network: string | null;
	tunnels_lost: string[];
	sites_lost: string[];
}

test('a problem says what fixing it would bring back to each network', async ({ page }) => {
	const { at, found } = await momentWith(
		page,
		(at) => `/api/problems?at=${encodeURIComponent(at)}`,
		(answer: { problems: { title: string; networks: Lost[] }[] }) =>
			answer.problems.find((p) =>
				p.networks.some((n) => n.tunnels_lost.length || n.sites_lost.length)
			)?.title
	);
	await page.goto(`/?live=1&at=${encodeURIComponent(at)}`);
	const problem = page
		.getByRole('region', { name: 'Problems' })
		.getByRole('button', { name: found });
	// The list names each network it takes something from, and what.
	await expect(problem).toContainText(/[\w-]+: .*(tunnel|cut off)/);
	await problem.click();
	const impact = details(page).getByRole('region', { name: 'Impact' });
	await expect(impact.getByRole('heading', { name: /^Networks \(\d+\)$/ })).toBeVisible();
	await expect(impact.getByText('What fixing it would bring back to each network')).toBeVisible();
});

test('with live state, shared risk counts what is down, new risks first', async ({ page }) => {
	const { at, found } = await momentWith(
		page,
		(at) => `/api/risks?at=${encodeURIComponent(at)}`,
		(answer: { networks: { network: string; risks: { new: boolean }[] }[] }) =>
			answer.networks.find((n) => n.risks.some((r) => r.new))?.network
	);
	await page.goto(`/?live=1&at=${encodeURIComponent(at)}&select=network:${found}`);
	await expect(heading(page)).toHaveText(found);
	await expect(
		details(page).getByText(/^With what is down at .*, only what is still up counts/)
	).toBeVisible();
	await expect(
		details(page).locator('table.risks tr').first().getByText('New', { exact: true })
	).toBeVisible();
});

test('problems follow the networks chosen, by kind or by region', async ({ page }) => {
	const { at, found: total } = await momentWith(
		page,
		(at) => `/api/problems?at=${encodeURIComponent(at)}`,
		(answer: { problems: unknown[] }) =>
			answer.problems.length >= 2 ? answer.problems.length : undefined
	);
	await page.goto(`/?live=1&at=${encodeURIComponent(at)}&network=grey`);
	const panel = page.getByRole('region', { name: 'Problems' });
	await panel.getByRole('button', { name: 'By region' }).click();
	await expect(panel.getByRole('button', { name: 'By region' })).toHaveAttribute(
		'aria-pressed',
		'true'
	);
	// Grey's own regions, after any high-priority problems on their own; every
	// problem is listed under one, or counted as elsewhere.
	const regions = panel.getByRole('heading', {
		name: /^(High priority|grey-west|grey-east|No region) \(\d+\)$/
	});
	await expect(regions.first()).toBeVisible();
	const listed = (await regions.allTextContents()).reduce(
		(n, h) => n + Number(/\((\d+)\)$/.exec(h)?.[1]),
		0
	);
	const note = await panel.getByText(/^\d+ not in grey\.$/).allTextContents();
	expect(listed + Number(/^\d+/.exec(note[0] ?? '0')?.[0])).toBe(total);
	// Only grey, and what it rides (blue, blue2, black), among the networks.
	await expect(
		panel.getByRole('button', { name: /^(corp|dci|red-alpha|red-bravo|partners) / })
	).toHaveCount(0);
	// The next problem is the first listed.
	await page.keyboard.press('j');
	const first = regions.first().locator('xpath=following-sibling::ul[1]//button').first();
	await expect(first).toHaveAttribute('aria-pressed', 'true');
});

test('events keep to the networks chosen, and to a region', async ({ page }) => {
	await page.goto('/?live=1&network=grey');
	await page.getByRole('tab', { name: /^Events/ }).click();
	const events = page.getByRole('region', { name: 'Events' });
	const region = events.getByRole('combobox', { name: 'Region' });
	await expect(region.locator('option')).toHaveText(['All regions', 'grey-west', 'grey-east']);
	await region.selectOption('grey-west');
	const titles = events.locator('li button > span');
	await expect(titles.first()).toBeVisible();
	// Rows of a device or a site name it first: each must be in the west.
	const west = ['DAL', 'HOU', 'OKC', 'TPA'];
	for (const title of await titles.allTextContents()) {
		const site =
			/^([a-z]{3})-[a-z]/.exec(title)?.[1]?.toUpperCase() ?? /^([A-Z]{3}): /.exec(title)?.[1];
		if (site) expect(west, title).toContain(site);
	}
});

test("a site's details give its status in each network there", async ({ page }) => {
	await page.goto('/?live=1&select=site:DAL');
	await expect(details(page).getByRole('heading', { name: /^Networks \(\d+\)$/ })).toBeVisible();
	const table = details(page).locator('table.site-networks');
	await expect(table.getByRole('row').first()).toContainText('Enterprise');
	const grey = networkRow(table, 'grey');
	await expect(grey).toContainText(/Operational\*?|Degraded|Offline/);
	await grey.click();
	await expect(heading(page)).toHaveText('grey');
});

test('the logical view draws the tunnels spokes have built to each other', async ({ page }) => {
	const { at, found } = await momentWith(
		page,
		(at) => `/api/state?at=${encodeURIComponent(at)}`,
		(state: { tunnels: { network: string; dynamic: boolean; status: string }[] }) => {
			const built = state.tunnels.filter(
				(t) => t.network === 'corp' && t.dynamic && t.status === 'up'
			);
			return built.length ? built.length : undefined;
		}
	);
	await page.goto(`/?live=1&at=${encodeURIComponent(at)}&view=logical&network=corp`);
	await expect(page.getByRole('status').filter({ hasText: 'corp' })).toContainText(
		`· ${found} spoke to spoke now`
	);
});

test("a network's details say what kind of place is not working", async ({ page }) => {
	const { at, found } = await momentWith(
		page,
		(at) => `/api/status?at=${encodeURIComponent(at)}`,
		(report: { networks: { network: string; groups: { kind: string; name: string }[] }[] }) => {
			for (const n of report.networks) {
				const place = n.groups.find((g) => g.kind === 'location');
				if (place) return { network: n.network, name: place.name };
			}
			return undefined;
		}
	);
	await page.goto(`/?live=1&at=${encodeURIComponent(at)}&select=network:${found.network}`);
	await expect(
		details(page)
			.getByRole('cell', { name: `${found.name} location`, exact: true })
			.first()
	).toBeVisible();
});

test('a circuit says what it is for at the edge, and the IDs it goes by', async ({ page }) => {
	// A circuit each of whose sides has its own IDs, the carrier's with the LEC's.
	await searchFor(page, 'AUS-SAT-01');
	await expect(heading(page)).toHaveText('Link');
	const facts = details(page).locator('dd');
	await expect(facts.filter({ hasText: 'AUS-SAT-01 (A) · SAT-AUS-01 (Z)' })).toBeVisible();
	await expect(facts.filter({ hasText: /Pecos Bell 12\/KXFU\/204411 \(A\)/ })).toBeVisible();
	await expect(details(page).getByText('Carrier circuit · Mesa Carrier')).toBeVisible();
	await expect(details(page).getByText('implied by the far end')).toBeVisible();
	// The research network: peering at IAD, with what that does to the boundary.
	await searchFor(page, 'IAD-REN-01');
	await expect(
		details(page).getByText('Crosses it both ways with a known community')
	).toBeVisible();
	// A circuit no one has given roles yet.
	await page.getByRole('combobox', { name: 'Search' }).fill('tbd');
	await expect(page.getByRole('option').first()).toContainText('Circuit TPA-INET-01');
	await page.keyboard.press('Enter');
	await expect(details(page).getByText('TBD', { exact: true })).toBeVisible();
	// Cross-connects join IAD's halls, each with its cable ID.
	await searchFor(page, 'IAD-C0006');
	await expect(details(page).getByText('Cross-connect · Granite Colo')).toBeVisible();
});

interface Comparison {
	findings: { kind: string; title: string; fix: { summary: string } | null }[];
}

test('discovery finds our own devices seeing each other across a peering edge', async ({
	page
}) => {
	const { at } = await momentWith(
		page,
		(at) => `/api/discovery?at=${encodeURIComponent(at)}`,
		(answer: Comparison) =>
			answer.findings.filter((f) => f.kind === 'boundary').length === 2 ? true : undefined
	);
	await page.goto(`/?at=${encodeURIComponent(at)}`);
	await page.keyboard.press('d');
	const list = page.getByRole('region', { name: 'Discovery' });
	await expect(
		list.getByRole('heading', { name: 'Our own devices across the boundary (2)' })
	).toBeVisible();
	await expect(list.getByText('dal-wan-01 sees iad-wan-01 across Prairie REN')).toBeVisible();
	await expect(list.getByText(/Circuit IAD-REN-01 is a peering edge/)).toBeVisible();
	await expect(list.getByText(/endpoints on access ports/)).toBeVisible();
});

test('a circuit that does not say what it shows is offered what discovery sees', async ({
	page
}) => {
	const now = (await (await page.request.get('/api/discovery')).json()) as Comparison;
	const title = "Circuit TPA-INET-01 shows the provider's equipment";
	test.skip(
		!now.findings.some((f) => f.title === title),
		'tpa-wsw-01 is not answering discovery now'
	);
	await page.keyboard.press('d');
	const list = page.getByRole('region', { name: 'Discovery' });
	await expect(
		list.getByRole('heading', { name: /^Circuits showing other than they say/ })
	).toBeVisible();
	await list
		.getByRole('button', {
			name: "Fix: Document that Circuit TPA-INET-01 shows the provider's equipment"
		})
		.click();
	const review = page.getByRole('form', { name: 'Review fix' });
	await expect(review.getByText('Does not say what it shows', { exact: true })).toBeVisible();
	await expect(review.getByText("Shows the provider's equipment", { exact: true })).toBeVisible();
});

test("an E-Tree's leaves reach each other only through a root", async ({ page }) => {
	await searchFor(page, 'Harbor E-Tree');
	await expect(heading(page)).toHaveText('Harbor E-Tree');
	await expect(details(page).getByText('E-Tree · MPLS EVPN')).toBeVisible();
	const circuits = details(page).getByRole('row');
	await expect(circuits.filter({ hasText: 'dal-wan-02' })).toContainText('Root');
	await expect(circuits.filter({ hasText: 'mem-wan-01' })).toContainText('Leaf');
	// Memphis and Tulsa are both leaves: the path between them turns at a root.
	await page.goto('/?view=logical&from=mem-wan-01&to=tul-wan-01');
	await expect(heading(page)).toHaveText('Path');
	await expect(
		details(page).getByText('Path 1 via Harbor E-Tree › dal-wan-02 › Harbor E-Tree')
	).toBeVisible();
});

test('a port channel has a CID of its own, and MACsec on each member', async ({ page }) => {
	await page.getByRole('combobox', { name: 'Search' }).fill('DAL-IAD-PO01');
	await expect(page.getByRole('option').first()).toContainText('Port channel DAL-IAD-PO01');
	await page.keyboard.press('Enter');
	await expect(heading(page)).toHaveText('2 links');
	await expect(details(page).getByRole('heading', { name: 'Port channel' })).toBeVisible();
	const members = details(page).getByRole('table').filter({ hasText: 'Member' });
	await expect(members.getByRole('row')).toHaveCount(3);
	await members.getByRole('row').filter({ hasText: 'DAL-IAD-01' }).click();
	await expect(heading(page)).toHaveText('Link');
	const facts = details(page).locator('dd');
	await expect(facts.filter({ hasText: 'E-Line · VPWS' })).toBeVisible();
	await expect(facts.filter({ hasText: 'DAL-IAD-PO01 · 2 members' })).toBeVisible();
	// The carrier passes nothing of ours, but LLDP and CDP run inside the MACsec.
	await expect(facts.filter({ hasText: 'LLDP and CDP inside it' })).toBeVisible();
	await expect(facts.filter({ hasText: /^The far end$/ })).toBeVisible();
	await details(page).getByRole('button', { name: 'DCI-MACSEC-1' }).click();
	await expect(heading(page)).toHaveText('DCI-MACSEC-1');
	await expect(details(page).getByText('encrypted on the physical ports')).toBeVisible();
	await expect(
		details(page).getByText('its far end seen proves the encryption works')
	).toBeVisible();
	await expect(details(page).getByRole('button', { name: 'Circuit DAL-IAD-01' })).toBeVisible();
});

interface Checked extends Comparison {
	tunnels: Record<string, string>;
}

test('discovery finds E-Tree leaves that see each other, and a tunnel on another interface', async ({
	page
}) => {
	const { at } = await momentWith(
		page,
		(at) => `/api/discovery?at=${encodeURIComponent(at)}`,
		(answer: Checked) =>
			answer.findings.some((f) => f.kind === 'leaf') &&
			answer.tunnels['BLUE-HOU-IAD'] === 'mismatch'
				? true
				: undefined
	);
	// Replayed, so the run in effect then is the one shown.
	await page.goto(`/?live=1&at=${encodeURIComponent(at)}`);
	await page.keyboard.press('d');
	const list = page.getByRole('region', { name: 'Discovery' });
	await expect(
		list.getByRole('heading', { name: 'E-Tree leaves that see each other (1)' })
	).toBeVisible();
	await expect(list.getByText('mem-wan-01 sees okc-wan-02 across Harbor E-Tree')).toBeVisible();
	await expect(list.getByText('BLUE-HOU-IAD on another tunnel interface')).toBeVisible();
	await expect(list.getByText(/tunnels confirmed over CDP or inside MACsec/)).toBeVisible();
	// The tunnel's details say what CDP over it shows.
	await page.goto(`/?live=1&at=${encodeURIComponent(at)}&select=tunnel:BLUE-HOU-IAD&discovery=1`);
	await expect(heading(page)).toHaveText('BLUE-HOU-IAD');
	await expect(details(page).getByText('Not as documented')).toBeVisible();
	await expect(details(page).getByText(/sees iad-blu-01 Tunnel112 over CDP/)).toBeVisible();
});

test('a resource lists its members, and a circuit its priority and resources', async ({ page }) => {
	await searchFor(page, 'Global Access');
	await expect(heading(page)).toHaveText('Global Access');
	await expect(details(page).getByText('Ways out to the world at the TIC gateways')).toBeVisible();
	await expect(details(page).getByRole('heading', { name: 'Members (5)' })).toBeVisible();
	// A resource inside another says what it is part of.
	await page.goto('/?select=resource:Nimbus%20Cloud%20access');
	await expect(details(page).getByRole('button', { name: 'Global Access' })).toBeVisible();
	await details(page).getByRole('button', { name: 'Global Access' }).click();
	await expect(heading(page)).toHaveText('Global Access');
	// A member circuit: the enterprise's to answer for, at the default for its role.
	await details(page).getByRole('button', { name: 'DAL-REN-01' }).click();
	await expect(heading(page)).toHaveText('Link');
	await expect(details(page).getByText('Medium · open, by default')).toBeVisible();
	await expect(details(page).getByRole('button', { name: 'Global Access' })).toBeVisible();
});

test("high is the admins' to set; access is low, its tenant's first", async ({ page }) => {
	await searchFor(page, 'DAL-IAD-01');
	await expect(heading(page)).toHaveText('Link');
	await expect(details(page).getByText('High · set on the link')).toBeVisible();
	await searchFor(page, 'DAL-C0022');
	await expect(heading(page)).toHaveText('Link');
	await expect(details(page).getByText('Low · access, by default')).toBeVisible();
	await expect(details(page).getByText('Alpha (tenant)')).toBeVisible();
});

test('resources not operational are listed with the networks in Problems', async ({ page }) => {
	const { at, found } = await momentWith(
		page,
		(at) => `/api/status?at=${encodeURIComponent(at)}`,
		(answer: { resources: { name: string; status: string }[] }) =>
			answer.resources.find((r) => r.status !== 'operational')?.name
	);
	await page.goto(`/?live=1&at=${encodeURIComponent(at)}`);
	const panel = page.getByRole('region', { name: 'Problems' });
	await expect(panel.getByRole('heading', { name: /^Resources \(\d+\)$/ })).toBeVisible();
	await panel.getByRole('button', { name: new RegExp(`^\\W*${found} (degraded|offline)`) }).click();
	await expect(heading(page)).toHaveText(found);
	await expect(
		details(page)
			.getByText(/^(Degraded|Offline)$/)
			.first()
	).toBeVisible();
});

test('high-priority problems come first, marked High', async ({ page }) => {
	const { at, found } = await momentWith(
		page,
		(at) => `/api/problems?at=${encodeURIComponent(at)}`,
		(answer: { problems: { title: string; priority: string }[] }) =>
			answer.problems.find((p) => p.priority === 'high')?.title
	);
	await page.goto(`/?live=1&at=${encodeURIComponent(at)}`);
	const panel = page.getByRole('region', { name: 'Problems' });
	// After the networks and resources not as they should be, the problems.
	const first = panel.getByRole('heading', { name: /^(?!Networks |Resources ).*\(\d+\)$/ }).first();
	await expect(first).toHaveText(/^High priority \(\d+\)$/);
	const problem = panel.getByRole('button', { name: found }).first();
	await expect(problem.getByText('High', { exact: true })).toBeVisible();
});
