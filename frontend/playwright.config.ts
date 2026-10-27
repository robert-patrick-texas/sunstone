/**
 * End-to-end tests against the real backend serving the production build,
 * with the small sample topology.
 *
 * Set `PW_WS_ENDPOINT` to use a browser running elsewhere, such as the
 * Playwright container on a host without Chromium's system libraries (see
 * the README). The container's Playwright version must match this one.
 */
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { defineConfig, devices } from '@playwright/test';

const PORT = Number(process.env['SUNSTONE_E2E_PORT'] ?? 18940);
// Layouts, maintenance, and acknowledgements saved by the tests go to fresh
// files, never beside the sample data.
const LAYOUTS = join(tmpdir(), `sunstone-e2e-${process.pid}.layouts.json`);
const OPERATIONS = join(tmpdir(), `sunstone-e2e-${process.pid}.operations.json`);
const ws = process.env['PW_WS_ENDPOINT'];

export default defineConfig({
	testDir: 'e2e',
	outputDir: 'test-results',
	timeout: 30_000,
	reporter: [['list']],
	use: {
		baseURL: `http://127.0.0.1:${PORT}`,
		trace: 'retain-on-failure',
		// The map needs WebGL; headless Chromium only offers it through SwiftShader.
		launchOptions: { args: ['--enable-unsafe-swiftshader'] },
		...(ws ? { connectOptions: { wsEndpoint: ws } } : {})
	},
	projects: [
		{
			name: 'chromium',
			use: { ...devices['Desktop Chrome'], viewport: { width: 1400, height: 900 } }
		}
	],
	webServer: {
		command:
			'uv run sunstone --topology ../data/sample/small.yaml --web-dir ../frontend/build ' +
			`--layouts ${LAYOUTS} --operations ${OPERATIONS} --port ${PORT}`,
		cwd: '../backend',
		url: `http://127.0.0.1:${PORT}/api/topology`,
		reuseExistingServer: false,
		timeout: 60_000
	}
});
