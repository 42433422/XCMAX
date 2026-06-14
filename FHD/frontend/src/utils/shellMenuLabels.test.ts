import { describe, expect, it } from 'vitest';
import {
  effectiveShellMenuIndustryId,
  getActiveShellMod,
  mergeShellViewTitles,
  readShellMenuPreset,
  readShellTagline,
  SHELL_VIEW_TITLE_BASE,
} from './shellMenuLabels';

describe('shellMenuLabels', () => {
  it('readShellMenuPreset prefers snake_case and frontend nesting', () => {
    expect(readShellMenuPreset({ shell_menu_preset: '涂料' })).toBe('涂料');
    expect(readShellMenuPreset({ shellMenuPreset: '电商' })).toBe('电商');
    expect(readShellMenuPreset({ frontend: { shell_menu_preset: '餐饮' } })).toBe('餐饮');
  });

  it('readShellTagline reads tagline fields', () => {
    expect(readShellTagline({ shell_tagline: '副标题' })).toBe('副标题');
    expect(readShellTagline({ frontend: { shellTagline: 'A' } })).toBe('A');
  });

  it('getActiveShellMod prefers active id then primary', () => {
    const mods = [
      { id: 'a', primary: false },
      { id: 'b', primary: true },
    ];
    expect(getActiveShellMod(mods, 'a')?.id).toBe('a');
    expect(getActiveShellMod(mods, '')?.id).toBe('b');
    expect(getActiveShellMod([], '')?.id).toBeUndefined();
  });

  it('effectiveShellMenuIndustryId uses preset override', () => {
    const mods = [{ id: 'm1', shell_menu_preset: '涂料' }];
    expect(effectiveShellMenuIndustryId('通用', mods, 'm1')).toBe('涂料');
    expect(effectiveShellMenuIndustryId('通用', [], '')).toBe('通用');
  });

  it('mergeShellViewTitles layers industry overrides', () => {
    const mods = [{ id: 'm1', shell_menu_preset: '涂料' }];
    const titles = mergeShellViewTitles('通用', mods, 'm1');
    expect(titles.products).toBe('产品管理');
    expect(titles.chat).toBe(SHELL_VIEW_TITLE_BASE.chat);
  });
});
