import { expect, test } from '@playwright/test';

test('a problem becomes an incident, with notes, a timeline, and a postmortem', async ({
	page
}) => {
	await page.goto('/');
	await expect(page.getByText('5 sites · 52 devices · 106 links')).toBeVisible();
	await page.getByRole('button', { name: 'Live' }).click();
	// The last problem, so as not to share one with tests that acknowledge the first.
	const problems = page.getByRole('region', { name: 'Problems' });
	const last = problems.getByRole('button').last();
	const title = (await last.locator('.title').textContent()) ?? '';
	await last.click();
	const impact = page.getByRole('region', { name: 'Impact' });
	await expect(impact.getByLabel('Incident title')).toHaveValue(title);
	await impact.getByLabel('Incident title').fill('Branch circuits');
	await impact.getByLabel('Opened by').fill('Pat');
	await impact.getByRole('button', { name: 'Open incident' }).click();

	const report = page.getByLabel('Incident', { exact: true });
	await expect(report.getByRole('heading', { level: 1 })).toHaveText(/^Incident \d+$/);
	await expect(page).toHaveURL(/incident=\d+/);
	await expect(report.locator('.status')).toHaveText('Open');
	const timeline = report.getByRole('region', { name: 'Timeline' });
	await expect(timeline).toContainText('Pat opened the incident: Branch circuits');
	await expect(report.getByRole('region', { name: 'Problems' })).toContainText(title);
	const notes = report.getByRole('region', { name: 'Notes' });
	await notes.getByLabel('Note on the incident').fill('Carrier says fiber cut near the branch');
	await notes.getByRole('button', { name: 'Add note' }).click();
	await expect(timeline).toContainText('Carrier says fiber cut near the branch (Pat)');

	// Closed, the report leaves the problem marked as in the incident.
	await report.getByRole('button', { name: 'Close', exact: true }).click();
	await expect(report).toHaveCount(0);
	await expect(problems.getByRole('button').filter({ hasText: title })).toContainText(
		/Incident \d+/
	);
	await expect(impact.getByRole('button', { name: 'Show it' })).toBeVisible();

	// i opens it again; the postmortem closes it.
	await page.keyboard.press('i');
	await expect(report.getByRole('heading', { level: 1 })).toHaveText(/^Incident \d+$/);
	const postmortem = report.getByRole('region', { name: 'Postmortem', exact: true });
	await postmortem
		.getByLabel('Postmortem summary')
		.fill('Fiber cut by roadworks; the carrier is to add a diverse path.');
	await postmortem.getByRole('button', { name: 'Close incident' }).click();
	await expect(report.locator('.status')).toHaveText('Closed');
	await expect(postmortem).toContainText('Fiber cut by roadworks');
	await expect(timeline).toContainText('Pat closed the incident');
	await expect(report.getByLabel('Note on the incident')).toHaveCount(0);
	await report.getByRole('button', { name: 'Postmortem', exact: true }).click();
	const text = report.getByRole('region', { name: 'Postmortem text' }).locator('pre');
	await expect(text).toContainText('Summary (Pat,');
	await expect(text).toContainText(/In Sunstone: http\S+\?incident=\d+$/);
	await page.keyboard.press('Escape');
	await expect(report).toHaveCount(0);

	// The shift handover lists it.
	await page.keyboard.press('h');
	const incidents = page.getByLabel('Shift handover').getByRole('region', { name: 'Incidents' });
	await expect(incidents).toContainText('Branch circuits');
	await expect(incidents).toContainText('closed');
});
