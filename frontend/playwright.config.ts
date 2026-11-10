/**
 * End-to-end tests against the real backend serving the production build,
 * with the small sample topology, and the layered sample for the tests of
 * named networks, transports, tunnels, and fabrics.
 *
 * Set `PW_WS_ENDPOINT` to use a browser running elsewhere, such as the
 * Playwright container on a host without Chromium's system libraries (see
 * the README). The container's Playwright version must match this one.
 */
import { mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { defineConfig, devices } from '@playwright/test';

const PORT = Number(process.env['SUNSTONE_E2E_PORT'] ?? 18940);
const LAYERS_PORT = PORT + 1;
// Layouts, maintenance, acknowledgements, notes, fixes, overrides, handovers, and incidents
// saved by the tests go to fresh files, never beside the sample data.
const LAYOUTS = join(tmpdir(), `sunstone-e2e-${process.pid}.layouts.json`);
const OPERATIONS = join(tmpdir(), `sunstone-e2e-${process.pid}.operations.json`);
const CHANGES = join(tmpdir(), `sunstone-e2e-${process.pid}.changes.json`);
const OVERRIDES = join(tmpdir(), `sunstone-e2e-${process.pid}.overrides.json`);
const HANDOVERS = join(tmpdir(), `sunstone-e2e-${process.pid}.handovers.json`);
const INCIDENTS = join(tmpdir(), `sunstone-e2e-${process.pid}.incidents.json`);
const LAYERS_STATE = join(tmpdir(), `sunstone-e2e-${process.pid}-layers`);
mkdirSync(LAYERS_STATE, { recursive: true });
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
			testIgnore: ['fixes.spec.ts', 'layers.spec.ts', 'overrides.spec.ts', 'rules.spec.ts'],
			use: { ...devices['Desktop Chrome'], viewport: { width: 1400, height: 900 } }
		},
		{
			name: 'layers',
			testMatch: 'layers.spec.ts',
			use: {
				...devices['Desktop Chrome'],
				viewport: { width: 1400, height: 900 },
				baseURL: `http://127.0.0.1:${LAYERS_PORT}`
			}
		},
		// Overrides change what the layered sample shows, so after its own tests.
		{
			name: 'overrides',
			testMatch: 'overrides.spec.ts',
			dependencies: ['layers'],
			use: {
				...devices['Desktop Chrome'],
				viewport: { width: 1400, height: 900 },
				baseURL: `http://127.0.0.1:${LAYERS_PORT}`
			}
		},
		// Rules too, after overrides, as each withdraws what the other made.
		{
			name: 'rules',
			testMatch: 'rules.spec.ts',
			dependencies: ['overrides'],
			use: {
				...devices['Desktop Chrome'],
				viewport: { width: 1400, height: 900 },
				baseURL: `http://127.0.0.1:${LAYERS_PORT}`
			}
		},
		// Fixing the documentation changes it for every test, so last, on its own.
		{
			name: 'fixes',
			testMatch: 'fixes.spec.ts',
			dependencies: ['chromium'],
			use: { ...devices['Desktop Chrome'], viewport: { width: 1400, height: 900 } }
		}
	],
	webServer: [
		{
			command:
				'uv run sunstone serve --topology ../data/sample/small.yaml --web-dir ../frontend/build ' +
				`--layouts ${LAYOUTS} --operations ${OPERATIONS} --changes ${CHANGES} ` +
				`--overrides ${OVERRIDES} ` +
				`--handovers ${HANDOVERS} --incidents ${INCIDENTS} --port ${PORT}`,
			cwd: '../backend',
			url: `http://127.0.0.1:${PORT}/api/topology`,
			reuseExistingServer: false,
			timeout: 60_000
		},
		{
			command:
				'uv run sunstone serve --topology ../data/sample/layers.yaml --web-dir ../frontend/build ' +
				`--state-dir ${LAYERS_STATE} --port ${LAYERS_PORT}`,
			cwd: '../backend',
			url: `http://127.0.0.1:${LAYERS_PORT}/api/topology`,
			reuseExistingServer: false,
			timeout: 60_000
		}
	]
});
