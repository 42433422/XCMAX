import { beforeEach, describe, expect, it } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { useIndustryStore } from '@/stores/industry';
import { useIndustryFieldSchema } from './useIndustryFieldSchema';

const COATING_SHIPMENT = {
  label: '出货记录',
  entity: '出货记录',
  fields: [
    { key: 'purchase_unit', label: '购买单位', semantic: 'foreign_ref' },
    { key: 'product_name', label: '产品名称', semantic: 'entity_name' },
    { key: 'model_number', label: '型号', semantic: 'model' },
    { key: 'quantity_tins', label: '数量 (桶)', type: 'number', unit: '桶', semantic: 'primary_qty' },
  ],
};

const ATTENDANCE_SHIPMENT = {
  label: '考勤记录',
  entity: '考勤记录',
  fields: [
    { key: 'purchase_unit', label: '部门', semantic: 'foreign_ref' },
    { key: 'product_name', label: '事项说明', semantic: 'entity_name' },
    { key: 'model_number', label: '关联编号', semantic: 'model' },
    { key: 'quantity_tins', label: '数量 (天/次)', type: 'number', unit: '天', semantic: 'primary_qty' },
  ],
};

beforeEach(() => {
  setActivePinia(createPinia());
});

describe('useIndustryFieldSchema', () => {
  it('涂料：从顶层形状 currentConfig.subsystems 取子系统字段表头', () => {
    const industry = useIndustryStore();
    industry.$patch({
      currentIndustry: { id: '涂料', name: '涂料', code: '涂料' },
      // mod 兜底形状：subsystems 在 currentConfig 顶层
      currentConfig: { id: '涂料', subsystems: { 'shipment-records': COATING_SHIPMENT } },
    });

    const s = useIndustryFieldSchema('shipment-records');
    expect(s.hasSchema.value).toBe(true);
    expect(s.entity.value).toBe('出货记录');
    expect(s.visible.value).toBe(true);
    expect(s.labelOf('purchase_unit', '购买单位')).toBe('购买单位');
    expect(s.labelOf('product_name')).toBe('产品名称');
    expect(s.labels.value.quantity_tins).toBe('数量 (桶)');
    expect(s.fields.value.map((f) => f.key)).toContain('model_number');
  });

  it('考勤：从 server 形状 currentConfig.config.subsystems 取子系统字段表头', () => {
    const industry = useIndustryStore();
    industry.$patch({
      currentIndustry: { id: '考勤', name: '考勤', code: '考勤' },
      // server 形状：subsystems 嵌在 config 内
      currentConfig: { id: '考勤', config: { subsystems: { 'shipment-records': ATTENDANCE_SHIPMENT } } },
    });

    const s = useIndustryFieldSchema('shipment-records');
    // 同一子系统键 'shipment-records'，标签随行业整体改变（取代 ===' 考勤' 硬编码三元）
    expect(s.labelOf('purchase_unit', '购买单位')).toBe('部门');
    expect(s.labelOf('product_name')).toBe('事项说明');
    expect(s.labels.value.quantity_tins).toBe('数量 (天/次)');
    expect(s.entity.value).toBe('考勤记录');
  });

  it('无 subsystems 声明：labelOf 回退到 fallback，hasSchema=false', () => {
    const industry = useIndustryStore();
    industry.$patch({
      currentIndustry: { id: '通用', name: '通用', code: '通用' },
      currentConfig: { id: '通用' },
    });

    const s = useIndustryFieldSchema('shipment-records');
    expect(s.hasSchema.value).toBe(false);
    expect(s.fields.value).toHaveLength(0);
    expect(s.labelOf('purchase_unit', '购买单位')).toBe('购买单位');
    expect(s.labelOf('unknown_key')).toBe('unknown_key');
    expect(s.visible.value).toBe(true);
  });

  it('visible=false 时如实反映（用于按行业隐藏子系统）', () => {
    const industry = useIndustryStore();
    industry.$patch({
      currentConfig: { config: { subsystems: { finance: { label: '财务', visible: false, fields: [] } } } },
    });
    const s = useIndustryFieldSchema('finance');
    expect(s.visible.value).toBe(false);
  });
});

describe('useIndustryFieldSchema.validate（行业规则·数据驱动）', () => {
  it('考勤 products：班次 oneOf 拦截非法值、放行合法值', () => {
    const industry = useIndustryStore();
    industry.$patch({
      currentConfig: {
        config: {
          subsystems: {
            products: {
              label: '人员管理',
              entity: '人员',
              fields: [
                { key: 'name', label: '姓名', required: true, semantic: 'entity_name' },
                { key: 'specification', label: '班次', type: 'enum', validators: [{ type: 'oneOf', params: ['早', '中', '晚'] }] },
              ],
            },
          },
        },
      },
    });
    const s = useIndustryFieldSchema('products');
    expect(s.validate({ name: '张三', specification: '早' })).toEqual([]);
    const errs = s.validate({ name: '张三', specification: '夜' });
    expect(errs).toHaveLength(1);
    expect(errs[0].field).toBe('specification');
    expect(errs[0].message).toContain('之一');
  });

  it('required 缺失被拦截', () => {
    const industry = useIndustryStore();
    industry.$patch({
      currentConfig: { config: { subsystems: { products: { fields: [{ key: 'name', label: '姓名', required: true }] } } } },
    });
    const s = useIndustryFieldSchema('products');
    expect(s.validate({})[0].field).toBe('name');
  });

  it('not_expired：过期日期拦截、未来/空放行', () => {
    const industry = useIndustryStore();
    industry.$patch({
      currentConfig: { config: { subsystems: { products: { fields: [{ key: 'expire_date', label: '保质期', validators: [{ type: 'not_expired' }] }] } } } },
    });
    const s = useIndustryFieldSchema('products');
    expect(s.validate({ expire_date: '2000-01-01' })).toHaveLength(1);
    expect(s.validate({ expire_date: '2099-12-31' })).toEqual([]);
    expect(s.validate({ expire_date: '' })).toEqual([]);
  });
});
