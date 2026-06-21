import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';

const getIndustries = vi.fn();
const getCurrentIndustry = vi.fn();

vi.mock('@/api/system', () => ({
  systemApi: {
    getIndustries: () => getIndustries(),
    getCurrentIndustry: () => getCurrentIndustry(),
  },
}));

import { useIndustryStore } from './industry';
import { useModsStore } from './mods';

beforeEach(() => {
  setActivePinia(createPinia());
  getIndustries.mockReset();
  getCurrentIndustry.mockReset();
});

describe('industry store', () => {
  it('loadIndustries only loads server industries (no mod manifest merge)', async () => {
    getIndustries.mockResolvedValue({
      success: true,
      data: { industries: [{ id: '通用', name: '通用', code: '通用' }] },
    });
    const mods = useModsStore();
    mods.$patch({
      mods: [{ id: 'm1', industry: { id: '涂料', name: '涂料行业' } }],
    });
    const s = useIndustryStore();
    await s.loadIndustries();
    expect(s.industries.map((i) => String(i.id))).toEqual(['通用']);
  });

  it('loadCurrentIndustry falls back to active mod industry', async () => {
    getCurrentIndustry.mockResolvedValue({ success: false });
    const mods = useModsStore();
    mods.$patch({
      activeModId: 'm1',
      mods: [{ id: 'm1', industry: { id: '考勤', name: '考勤', units: { primary: '天' } } }],
    });
    const s = useIndustryStore();
    await s.loadCurrentIndustry();
    expect(s.currentIndustryId).toBe('考勤');
    expect(s.primaryUnit).toBe('天');
  });

  it('getIndustryById finds loaded industry', async () => {
    getIndustries.mockResolvedValue({
      success: true,
      data: { industries: [{ id: '物流', name: '物流', code: '物流' }] },
    });
    const s = useIndustryStore();
    await s.loadIndustries();
    expect(s.getIndustryById('物流')?.name).toBe('物流');
    expect(s.getIndustryById('missing')).toBeNull();
  });

  it('loadFromServer loads both current industry and industries list', async () => {
    getIndustries.mockResolvedValue({
      success: true,
      data: { industries: [{ id: '电商', name: '电商', code: '电商' }] },
    });
    getCurrentIndustry.mockResolvedValue({
      success: true,
      data: { id: '电商', name: '电商', code: '电商', units: { primary: '件' } },
    });
    const s = useIndustryStore();
    await s.loadFromServer();
    expect(s.currentIndustryId).toBe('电商');
    expect(s.industries.map((i) => String(i.id))).toEqual(['电商']);
  });

  it('termRules is defined and empty by default', () => {
    const s = useIndustryStore();
    expect(s.termRules).toBeDefined();
    expect(Object.keys(s.termRules || {}).length).toBe(0);
  });
});
