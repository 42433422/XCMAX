import { beforeEach, describe, expect, it } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { useIndustryStore } from '@/stores/industry';
import { useModsStore } from '@/stores/mods';
import { useCoreNavLabel } from './useCoreNavLabel';

beforeEach(() => {
  setActivePinia(createPinia());
});

describe('useCoreNavLabel', () => {
  it('resolves label from industry and mods', () => {
    const industry = useIndustryStore();
    industry.$patch({
      currentIndustry: { id: '涂料', name: '涂料', code: '涂料' },
    });
    const mods = useModsStore();
    mods.$patch({
      mods: [{ id: 'm1', industry: { id: '涂料' }, menu_overrides: { products: '产品库' } }],
    });
    const label = useCoreNavLabel('products');
    expect(label.value.length).toBeGreaterThan(0);
  });
});
