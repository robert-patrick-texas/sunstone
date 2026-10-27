/**
 * Timings of the work that can make Sunstone slow, the frame rate, and how
 * long the page was blocked, for measuring on real hardware. Open the app
 * with `?perf` to see them in a corner, or read `window.sunstonePerf` from a
 * script (`make bench` does).
 */

export interface Timing {
	last: number;
	max: number;
	total: number;
	count: number;
}

// Not reactive state: work is often timed inside derived values, which must
// not change state. The panel reads these on a timer instead.
export const perf = {
	on: false,
	/** Frames drawn in the last second, and the longest gap between two of them. */
	fps: 0,
	worstFrameMs: 0,
	/** The longest stretch the main thread was busy (a long task), since the last reset. */
	longestTaskMs: 0,
	timings: {} as Record<string, Timing>
};

/**
 * Time some work and record it under a name.
 *
 * @param name - What the work is, such as `hierarchy layout`.
 * @param work - The work.
 * @returns What the work returns.
 */
export function timed<T>(name: string, work: () => T): T {
	const start = performance.now();
	try {
		return work();
	} finally {
		record(name, performance.now() - start);
	}
}

/**
 * Time some asynchronous work, from start until it settles.
 *
 * @param name - What the work is, such as `live fetch`.
 * @param work - The work.
 * @returns What the work resolves to.
 */
export async function timedAsync<T>(name: string, work: () => Promise<T>): Promise<T> {
	const start = performance.now();
	try {
		return await work();
	} finally {
		record(name, performance.now() - start);
	}
}

function record(name: string, ms: number): void {
	const t = perf.timings[name] ?? { last: 0, max: 0, total: 0, count: 0 };
	perf.timings[name] = {
		last: ms,
		max: Math.max(t.max, ms),
		total: t.total + ms,
		count: t.count + 1
	};
}

/** Forget what was measured so far, to measure one scenario. */
export function resetPerf(): void {
	perf.timings = {};
	perf.longestTaskMs = 0;
}

/**
 * Start measuring frames and long tasks, and expose the numbers to scripts.
 * Called once, when the page is opened with `?perf`.
 */
export function startPerf(): void {
	perf.on = true;
	(window as unknown as { sunstonePerf: typeof perf }).sunstonePerf = perf;
	let frames = 0;
	let worst = 0;
	let last = performance.now();
	let second = last;
	const tick = (now: number) => {
		frames++;
		worst = Math.max(worst, now - last);
		last = now;
		if (now - second >= 1000) {
			perf.fps = Math.round((frames * 1000) / (now - second));
			perf.worstFrameMs = Math.round(worst);
			frames = 0;
			worst = 0;
			second = now;
		}
		requestAnimationFrame(tick);
	};
	requestAnimationFrame(tick);
	if (PerformanceObserver.supportedEntryTypes.includes('longtask')) {
		new PerformanceObserver((list) => {
			for (const entry of list.getEntries()) {
				perf.longestTaskMs = Math.max(perf.longestTaskMs, Math.round(entry.duration));
			}
		}).observe({ type: 'longtask' });
	}
}
