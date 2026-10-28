/**
 * Benchmarks against the real backend serving the production build, with
 * the large sample topology (about 3,000 devices). Run with `make bench`;
 * see "Measuring speed" in the README.
 *
 * Numbers depend on the machine: the Playwright container draws without a
 * GPU, so run this on the hardware people will use. `PW_WS_ENDPOINT` uses a
 * browser running elsewhere, as for the end-to-end tests; `BENCH_HEADED=1`
 * opens a visible browser window.
 */
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { defineConfig, devices } from '@playwright/test';

const PORT = Number(process.env['SUNSTONE_BENCH_PORT'] ?? 18941);
const LAYOUTS = join(tmpdir(), `sunstone-bench-${process.pid}.layouts.json`);
const OPERATIONS = join(tmpdir(), `sunstone-bench-${process.pid}.operations.json`);
const ws = process.env['PW_WS_ENDPOINT'];

export default defineConfig({
	testDir: 'bench',
	testMatch: '*.bench.ts',
	outputDir: 'test-results/bench',
	timeout: 300_000,
	workers: 1,
	reporter: [['list']],
	use: {
		baseURL: `http://127.0.0.1:${PORT}`,
		headless: !process.env['BENCH_HEADED'],
		launchOptions: { args: ['--enable-unsafe-swiftshader'] },
		...(ws ? { connectOptions: { wsEndpoint: ws } } : {})
	},
	projects: [
		{
			name: 'chromium',
			use: { ...devices['Desktop Chrome'], viewport: { width: 1600, height: 950 } }
		}
	],
	webServer: {
		command:
			'uv run sunstone serve --topology ../data/sample/large.yaml --web-dir ../frontend/build ' +
			`--layouts ${LAYOUTS} --operations ${OPERATIONS} --port ${PORT}`,
		cwd: '../backend',
		url: `http://127.0.0.1:${PORT}/api/topology`,
		reuseExistingServer: false,
		timeout: 60_000
	}
});
