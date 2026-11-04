import { describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useIndustryStore } from '@/stores/industry'
import { useCoreNavLabel } from '@/composables/useCoreNavLabel'
import { systemApi } from '@/api/system'
vi.mock('@/api/system', () => ({ systemApi: { getCurrentIndustry: vi.fn() } }))
import { resolveCoreNavLabel } from '@/utils/coreNavLabel'

describe('resolveCoreNavLabel generic host defaults', () => {
  it('names the actual product and customer entities by default', () => {
    expect(resolveCoreNavLabel('products', '通用', [])).toBe('产品管理')
    expect(resolveCoreNavLabel('customers', '通用', [])).toBe('客户管理')
    expect(resolveCoreNavLabel('orders', '通用', [])).toBe('业务单据')
    expect(resolveCoreNavLabel('materials', '通用', [])).toBe('资源库')
  })

  it('updates existing product and customer labels after a verified industry change', async () => {
    setActivePinia(createPinia())
    const store = useIndustryStore()
    const products = useCoreNavLabel('products')
    const customers = useCoreNavLabel('customers')
    for (const [id, productLabel, customerLabel] of [
      ['通用', '产品管理', '客户管理'], ['考勤', '人员管理', '部门管理'], ['通用', '产品管理', '客户管理'],
    ]) {
      vi.mocked(systemApi.getCurrentIndustry).mockResolvedValue({ success: true, data: { id, name: id, code: id } } as any)
      await store.loadCurrentIndustry()
      expect(products.value).toBe(productLabel)
      expect(customers.value).toBe(customerLabel)
    }
  })

  it('keeps attendance labels scoped to the attendance industry', () => {
    expect(resolveCoreNavLabel('products', '考勤', [])).toBe('人员管理')
    expect(resolveCoreNavLabel('orders', '考勤', [])).toBe('考勤单管理')
    expect(resolveCoreNavLabel('materials', '考勤', [])).toBe('排班资源')
  })
})
