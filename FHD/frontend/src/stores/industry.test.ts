import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { ref } from 'vue';

const getIndustries = vi.fn();
const getCurrentIndustry = vi.fn();
const setIndustry = vi.fn();

vi.mock('@/api/system', () => ({
  systemApi: {
    getIndustries: () => getIndustries(),
    getCurrentIndustry: () => getCurrentIndustry(),
    setIndustry: (id: unknown) => setIndustry(id),
  },
}));

import { useIndustryStore } from './industry';
import { useModsStore } from './mods';

beforeEach(() => {
  setActivePinia(createPinia());
  getIndustries.mockReset();
  getCurrentIndustry.mockReset();
  setIndustry.mockReset();
});

describe('industry store', () => {
  it('loadIndustries merges mod manifest industries', async () => {
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
    expect(s.industries.map((i) => String(i.id))).toEqual(['通用', '涂料']);
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

  it('switchIndustry reloads current industry on success', async () => {
    setIndustry.mockResolvedValue({ success: true });
    getCurrentIndustry.mockResolvedValue({
      success: true,
      data: { id: '电商', name: '电商', code: '电商', units: { primary: '件' } },
    });
    const s = useIndustryStore();
    const ok = await s.switchIndustry('电商');
    expect(ok).toBe(true);
    expect(s.currentIndustryId).toBe('电商');
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
});
