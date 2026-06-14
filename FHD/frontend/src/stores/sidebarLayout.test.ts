import { beforeEach, describe, expect, it } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import {
  DEFAULT_SIDEBAR_WIDTH,
  MAX_SIDEBAR_WIDTH,
  MIN_SIDEBAR_WIDTH,
  useSidebarLayoutStore,
} from './sidebarLayout';

beforeEach(() => {
  setActivePinia(createPinia());
  localStorage.clear();
});

describe('sidebarLayout store', () => {
  it('initializes with defaults', () => {
    const s = useSidebarLayoutStore();
    expect(s.menuOrder).toEqual([]);
    expect(s.reorderEnabled).toBe(true);
    expect(s.sidebarWidth).toBe(DEFAULT_SIDEBAR_WIDTH);
    expect(s.hasCustomOrder).toBe(false);
  });

  it('loads and persists menu order from storage', () => {
    localStorage.setItem('xcagi.sidebar.menuOrder', JSON.stringify(['b', 'a']));
    const s = useSidebarLayoutStore();
    s.initialize(['a', 'b', 'c']);
    expect(s.menuOrder).toEqual(['b', 'a', 'c']);
    expect(s.hasCustomOrder).toBe(true);
    expect(JSON.parse(localStorage.getItem('xcagi.sidebar.menuOrder') || '[]')).toEqual([
      'b',
      'a',
      'c',
    ]);
  });

  it('normalizes invalid stored order', () => {
    localStorage.setItem('xcagi.sidebar.menuOrder', 'not-json');
    const s = useSidebarLayoutStore();
    s.initialize(['x', 'y']);
    expect(s.menuOrder).toEqual(['x', 'y']);
  });

  it('disables reorder when storage flag is 0', () => {
    localStorage.setItem('xcagi.sidebar.reorderEnabled', '0');
    const s = useSidebarLayoutStore();
    s.initialize(['a']);
    expect(s.reorderEnabled).toBe(false);
    s.setReorderEnabled(true);
    expect(localStorage.getItem('xcagi.sidebar.reorderEnabled')).toBe('1');
  });

  it('clamps sidebar width within bounds', () => {
    const s = useSidebarLayoutStore();
    s.setSidebarWidth(999);
    expect(s.sidebarWidth).toBe(MAX_SIDEBAR_WIDTH);
    s.setSidebarWidth(10);
    expect(s.sidebarWidth).toBe(MIN_SIDEBAR_WIDTH);
    expect(localStorage.getItem('xcagi.sidebar.width')).toBe(String(MIN_SIDEBAR_WIDTH));
  });

  it('applyOrder sorts items by persisted rank', () => {
    const s = useSidebarLayoutStore();
    s.menuOrder = ['c', 'a', 'b'];
    const items = [
      { key: 'a', label: 'A' },
      { key: 'b', label: 'B' },
      { key: 'c', label: 'C' },
    ];
    const sorted = s.applyOrder(items);
    expect(sorted.map((i) => i.key)).toEqual(['c', 'a', 'b']);
  });

  it('moveItem reorders when enabled', () => {
    const s = useSidebarLayoutStore();
    s.initialize(['a', 'b', 'c']);
    s.moveItem('c', 'a', ['a', 'b', 'c']);
    expect(s.menuOrder).toEqual(['c', 'a', 'b']);
  });

  it('moveItem is no-op when reorder disabled', () => {
    const s = useSidebarLayoutStore();
    s.setReorderEnabled(false);
    s.menuOrder = ['a', 'b'];
    s.moveItem('b', 'a', ['a', 'b']);
    expect(s.menuOrder).toEqual(['a', 'b']);
  });

  it('resetOrder restores defaults', () => {
    const s = useSidebarLayoutStore();
    s.menuOrder = ['z'];
    s.resetOrder(['a', 'b']);
    expect(s.menuOrder).toEqual(['a', 'b']);
  });
});
