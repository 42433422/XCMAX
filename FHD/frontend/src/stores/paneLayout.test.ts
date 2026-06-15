import { beforeEach, describe, expect, it } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { usePaneLayoutStore } from './paneLayout';

const OPTS = { defaultSize: 50, minSize: 20, maxSize: 80 };

beforeEach(() => {
  setActivePinia(createPinia());
  localStorage.clear();
});

describe('paneLayout store', () => {
  it('initializes pane to default and persists', () => {
    const s = usePaneLayoutStore();
    const size = s.initializePane('left', OPTS);
    expect(size).toBe(50);
    expect(s.paneSizes.left).toBe(50);
    expect(localStorage.getItem('xcagi.layout.paneSizes')).toContain('left');
  });

  it('clamps set value within min/max', () => {
    const s = usePaneLayoutStore();
    expect(s.setPaneSize('p', 999, OPTS)).toBe(80);
    expect(s.setPaneSize('p', -5, OPTS)).toBe(20);
    expect(s.setPaneSize('p', 33, OPTS)).toBe(33);
  });

  it('rounds fractional values', () => {
    const s = usePaneLayoutStore();
    expect(s.setPaneSize('p', 33.6, OPTS)).toBe(34);
  });

  it('getPaneSize returns clamped persisted value', () => {
    const s = usePaneLayoutStore();
    s.setPaneSize('p', 40, OPTS);
    expect(s.getPaneSize('p', OPTS)).toBe(40);
  });

  it('resetPaneSize restores default', () => {
    const s = usePaneLayoutStore();
    s.setPaneSize('p', 70, OPTS);
    expect(s.resetPaneSize('p', OPTS)).toBe(50);
  });

  it('setPaneSize returns same value without rewrite when unchanged', () => {
    const s = usePaneLayoutStore();
    s.setPaneSize('p', 40, OPTS);
    expect(s.setPaneSize('p', 40, OPTS)).toBe(40);
  });

  it('loads existing sizes from storage', () => {
    localStorage.setItem('xcagi.layout.paneSizes', JSON.stringify({ saved: 35 }));
    const s = usePaneLayoutStore();
    expect(s.getPaneSize('saved', OPTS)).toBe(35);
  });

  it('recovers from corrupt storage JSON', () => {
    localStorage.setItem('xcagi.layout.paneSizes', '{not-json');
    const s = usePaneLayoutStore();
    expect(s.getPaneSize('x', OPTS)).toBe(50);
  });
});
