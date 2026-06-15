import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { resolveCoreNavLabel } from '@/utils/coreNavLabel';
import { useResizablePane } from './useResizablePane';

describe('resolveCoreNavLabel mod override', () => {
  it('prefers mod menu_overrides label', () => {
    const mods = [{ menu_overrides: [{ key: 'products', label: '自定义产品' }] }];
    expect(resolveCoreNavLabel('products', '通用', mods)).toBe('自定义产品');
  });

  it('skips hidden overrides', () => {
    const mods = [{ menu_overrides: [{ key: 'products', label: '隐藏', hidden: true }] }];
    expect(resolveCoreNavLabel('products', '通用', mods)).toBe('业务对象');
  });

  it('empty menu key returns empty', () => {
    expect(resolveCoreNavLabel('', '通用', [])).toBe('');
  });

  it('unknown key returns empty string', () => {
    expect(resolveCoreNavLabel('no-such-menu-key', '通用', [])).toBe('');
  });
});

describe('useResizablePane', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    localStorage.clear();
    document.body.style.userSelect = '';
    document.body.style.cursor = '';
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('exposes paneSize and css var style', () => {
    const { paneSize, paneStyle } = useResizablePane({
      paneKey: 'left',
      cssVarName: '--left-w',
      defaultSize: 200,
      minSize: 100,
      maxSize: 400,
    });
    expect(paneSize.value).toBe(200);
    expect(paneStyle.value).toEqual({ '--left-w': '200px' });
  });

  it('startResize updates size on mousemove and cleans up on mouseup', () => {
    const onStart = vi.fn();
    const onEnd = vi.fn();
    const { startResize, paneSize } = useResizablePane({
      paneKey: 'chat',
      cssVarName: '--chat-w',
      defaultSize: 300,
      minSize: 200,
      maxSize: 500,
      onResizeStart: onStart,
      onResizeEnd: onEnd,
    });

    startResize({ clientX: 100, clientY: 0 } as MouseEvent);
    expect(onStart).toHaveBeenCalled();
    expect(document.body.style.userSelect).toBe('none');

    window.dispatchEvent(new MouseEvent('mousemove', { clientX: 150, clientY: 0 }));
    expect(paneSize.value).toBe(350);

    window.dispatchEvent(new MouseEvent('mouseup'));
    expect(onEnd).toHaveBeenCalled();
    expect(document.body.style.userSelect).toBe('');
  });

  it('horizontal orientation uses clientY', () => {
    const { startResize, paneSize } = useResizablePane({
      paneKey: 'top',
      cssVarName: '--top-h',
      defaultSize: 120,
      minSize: 80,
      maxSize: 300,
      orientation: 'horizontal',
    });
    startResize({ clientX: 0, clientY: 50 } as MouseEvent);
    window.dispatchEvent(new MouseEvent('mousemove', { clientX: 0, clientY: 80 }));
    expect(paneSize.value).toBe(150);
    window.dispatchEvent(new MouseEvent('mouseup'));
  });

  it('resetSize restores default', () => {
    const api = useResizablePane({
      paneKey: 'r',
      cssVarName: '--r',
      defaultSize: 240,
      minSize: 100,
      maxSize: 400,
    });
    api.startResize({ clientX: 0, clientY: 0 } as MouseEvent);
    window.dispatchEvent(new MouseEvent('mousemove', { clientX: 200, clientY: 0 }));
    window.dispatchEvent(new MouseEvent('mouseup'));
    expect(api.paneSize.value).toBeGreaterThan(240);
    api.resetSize();
    expect(api.paneSize.value).toBe(240);
  });

  it('does not start when enabled returns false', () => {
    const onStart = vi.fn();
    const { startResize } = useResizablePane({
      paneKey: 'off',
      cssVarName: '--off',
      defaultSize: 100,
      minSize: 50,
      maxSize: 200,
      enabled: () => false,
      onResizeStart: onStart,
    });
    startResize({ clientX: 0, clientY: 0 } as MouseEvent);
    expect(onStart).not.toHaveBeenCalled();
  });
});
