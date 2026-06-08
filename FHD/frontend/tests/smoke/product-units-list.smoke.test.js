/**
 * 冒烟：购买单位列表 API 响应形状（不启 dev server）
 *
 * npm run test:smoke
 */
import { describe, it, expect } from 'vitest'
import { productUnitsArrayFromApi } from '@/utils/productUnitsList'

describe('productUnitsArrayFromApi (购买单位)', () => {
  it('识别 { success, data: string[] }', () => {
    expect(
      productUnitsArrayFromApi({
        success: true,
        data: ['成都客户', '惠州厂'],
        count: 2,
      })
    ).toEqual(['成都客户', '惠州厂'])
  })

  it('识别 { success, units: string[] }（部分网关/旧接口）', () => {
    expect(
      productUnitsArrayFromApi({
        success: true,
        units: ['单位甲', '单位乙'],
        count: 2,
      })
    ).toEqual(['单位甲', '单位乙'])
  })

  it('识别 { data: { units: [] } }', () => {
    expect(
      productUnitsArrayFromApi({
        success: true,
        data: { units: ['A', 'B'] },
      })
    ).toEqual(['A', 'B'])
  })

  it('无列表时返回空数组', () => {
    expect(productUnitsArrayFromApi({ success: true, message: 'ok' })).toEqual([])
    expect(productUnitsArrayFromApi(null)).toEqual([])
  })
})
