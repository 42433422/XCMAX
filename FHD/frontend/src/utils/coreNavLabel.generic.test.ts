import { describe, expect, it } from 'vitest'
import { resolveCoreNavLabel } from '@/utils/coreNavLabel'

describe('resolveCoreNavLabel generic host defaults', () => {
  it('uses generic labels by default', () => {
    expect(resolveCoreNavLabel('products', '通用', [])).toBe('业务对象')
    expect(resolveCoreNavLabel('orders', '通用', [])).toBe('业务单据')
    expect(resolveCoreNavLabel('materials', '通用', [])).toBe('资源库')
  })

  it('keeps attendance labels scoped to the attendance industry', () => {
    expect(resolveCoreNavLabel('products', '考勤', [])).toBe('人员管理')
    expect(resolveCoreNavLabel('orders', '考勤', [])).toBe('考勤单管理')
    expect(resolveCoreNavLabel('materials', '考勤', [])).toBe('排班资源')
  })

  it('uses the nine-category skeleton for broader onboarding industries', () => {
    expect(resolveCoreNavLabel('products', '制造业', [])).toBe('产品管理')
    expect(resolveCoreNavLabel('materials', '制造业', [])).toBe('物料管理')
    expect(resolveCoreNavLabel('customers', '软件信息', [])).toBe('客户管理')
    expect(resolveCoreNavLabel('orders', '软件信息', [])).toBe('服务订单')
    expect(resolveCoreNavLabel('shipment-records', '软件信息', [])).toBe('交付记录')
  })
})
