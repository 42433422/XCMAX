import { beforeEach, describe, expect, it } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { useIndustryStore } from '@/stores/industry';
import { useModsStore } from '@/stores/mods';
import { useIndustryUiText } from './useIndustryUiText';

beforeEach(() => {
  setActivePinia(createPinia());
});

describe('useIndustryUiText', () => {
  it('derives entity labels from active mod manifest', () => {
    const mods = useModsStore();
    mods.$patch({
      activeModId: 'coat',
      mods: [
        {
          id: 'coat',
          name: '涂料包',
          industry: {
            id: '涂料',
            product_fields: { name: '产品名称', model: '型号' },
            units: { primary: '桶' },
            quantity_fields: { primary_label: '数量' },
            order_types: { shipment: '出货单' },
          },
          ui_labels: { entity: '产品', primary_unit: '桶' },
          ui_starter_pack: [{ label: '示例', hint: 'h', text: '查库存' }],
        },
      ],
    });
    const industry = useIndustryStore();
    industry.$patch({
      currentIndustry: { id: '涂料', name: '涂料', code: '涂料' },
      currentConfig: { units: { primary: '天' } },
    });

    const ui = useIndustryUiText();
    expect(ui.activeMod.value?.id).toBe('coat');
    expect(ui.entityName.value).toBe('产品');
    expect(ui.modelLabel.value).toBe('型号');
    expect(ui.primaryUnit.value).toBe('桶');
    expect(ui.assistantSubtitle.value).toContain('涂料包');
    expect(ui.starterPackPresets.value).toHaveLength(1);
  });

  it('falls back to industry preset when mod has no starter pack', () => {
    const mods = useModsStore();
    mods.$patch({
      activeModId: '',
      mods: [{ id: 'x', industry: { id: '考勤' } }],
    });
    const industry = useIndustryStore();
    industry.$patch({
      currentIndustry: { id: '考勤', name: '考勤', code: '考勤' },
      currentConfig: {},
    });
    const ui = useIndustryUiText();
    expect(ui.starterPackPresets.value.length).toBeGreaterThan(0);
    expect(ui.queryTitle.value).toContain('查询');
  });
});
