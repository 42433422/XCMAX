import { beforeEach, describe, expect, it } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { useIndustryStore } from '@/stores/industry';
import { useIndustryUiText } from './useIndustryUiText';

beforeEach(() => {
  setActivePinia(createPinia());
});

describe('useIndustryUiText', () => {
  it('derives entity labels from industryStore.currentConfig', () => {
    const industry = useIndustryStore();
    industry.$patch({
      currentIndustry: { id: '涂料', name: '涂料', code: '涂料' },
      currentConfig: {
        id: '涂料',
        name: '涂料',
        product_fields: { name: '产品名称', model: '型号' },
        units: { primary: '桶' },
        quantity_fields: { primary_label: '数量' },
        order_types: { shipment: '出货单' },
        ui_labels: { entity: '产品', primary_unit: '桶' },
        ui_starter_pack: [{ label: '示例', hint: 'h', text: '查库存' }],
      },
    });

    const ui = useIndustryUiText();
    expect(ui.entityName.value).toBe('产品');
    expect(ui.modelLabel.value).toBe('型号');
    expect(ui.primaryUnit.value).toBe('桶');
    expect(ui.assistantSubtitle.value).toContain('涂料');
    expect(ui.starterPackPresets.value).toHaveLength(1);
  });

  it('falls back to industry preset when currentConfig has no starter pack', () => {
    const industry = useIndustryStore();
    industry.$patch({
      currentIndustry: { id: '考勤', name: '考勤', code: '考勤' },
      currentConfig: { id: '考勤', name: '考勤' },
    });
    const ui = useIndustryUiText();
    expect(ui.starterPackPresets.value.length).toBeGreaterThan(0);
    expect(ui.queryTitle.value).toContain('查询');
  });
});
