import { afterEach, describe, expect, it, vi } from 'vitest';
import { loadRecent, MAX_RECENT, saveRecent, withRecent } from './recent.ts';

describe('withRecent', () => {
	it('puts what was just looked at first, once', () => {
		const list = withRecent(['device:a', 'site:B'], { kind: 'site', id: 'B' });
		expect(list).toEqual(['site:B', 'device:a']);
	});

	it('keeps only the latest few', () => {
		let list: string[] = [];
		for (let i = 0; i < 20; i++) list = withRecent(list, { kind: 'device', id: `d${i}` });
		expect(list).toHaveLength(MAX_RECENT);
		expect(list[0]).toBe('device:d19');
	});
});

describe('loadRecent and saveRecent', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
	});

	function storage(initial: Record<string, string> = {}) {
		const items = new Map(Object.entries(initial));
		return {
			getItem: (k: string) => items.get(k) ?? null,
			setItem: (k: string, v: string) => void items.set(k, v)
		};
	}

	it('keep the list in the browser', () => {
		vi.stubGlobal('localStorage', storage());
		saveRecent(['device:a', 'site:B']);
		expect(loadRecent()).toEqual(['device:a', 'site:B']);
	});

	it('start afresh from anything damaged, or without storage', () => {
		vi.stubGlobal('localStorage', storage({ 'sunstone.recent': '{not json' }));
		expect(loadRecent()).toEqual([]);
		vi.stubGlobal('localStorage', storage({ 'sunstone.recent': '["device:a", 3, null]' }));
		expect(loadRecent()).toEqual(['device:a']);
		vi.stubGlobal('localStorage', {
			getItem: () => {
				throw new DOMException('blocked', 'SecurityError');
			},
			setItem: () => {
				throw new DOMException('blocked', 'SecurityError');
			}
		});
		expect(loadRecent()).toEqual([]);
		expect(() => saveRecent(['device:a'])).not.toThrow();
	});
});
