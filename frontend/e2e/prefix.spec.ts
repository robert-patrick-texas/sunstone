/**
 * Sunstone behind a reverse proxy that serves it under a path, as
 * https://example.net/sunstone/ in front of the backend at `/`. The test plays
 * the proxy, and every request the page makes must stay under the path.
 */
import { expect, test } from '@playwright/test';

const PREFIX = '/sunstone';

test('works under a path, as behind a reverse proxy', async ({ page, baseURL }) => {
	const origin = new URL(baseURL ?? '').origin;
	const outside: string[] = [];
	// The proxy takes the path off and asks the backend; anything the page asks
	// for outside the path is refused and noted.
	await page.route(`${origin}/**`, async (route) => {
		const url = new URL(route.request().url());
		if (!url.pathname.startsWith(`${PREFIX}/`)) {
			outside.push(url.pathname);
			return route.abort();
		}
		url.pathname = url.pathname.slice(PREFIX.length);
		await route.fulfill({ response: await route.fetch({ url: url.href }) });
	});

	await page.goto(`${PREFIX}/`);
	await expect(page.getByText('5 sites · 52 devices · 106 links')).toBeVisible();
	await page.getByRole('combobox', { name: 'Search' }).fill('dal-core-01');
	await page.keyboard.press('Enter');
	const details = page.getByRole('complementary', { name: 'Details' });
	await expect(details.getByRole('heading', { name: 'dal-core-01' })).toBeVisible();
	await page.getByRole('button', { name: 'Live' }).click();
	await expect(page.getByText(/simulated · as of/)).toBeVisible();

	// Links to the selection keep the path too.
	expect(new URL(page.url()).pathname).toBe(`${PREFIX}/`);

	// The wall display has its own copy of the logo.
	await page.goto(`${PREFIX}/?wall=1`);
	await expect(page.getByText('Network map')).toBeVisible();
	await page.keyboard.press('Escape');
	await expect(page.getByRole('button', { name: 'Wall display' })).toBeVisible();
	expect(outside).toEqual([]);
});
