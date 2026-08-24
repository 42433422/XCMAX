import { describe, expect, it } from 'vitest'
import { ONBOARDING_INDUSTRY_CATEGORIES, ONBOARDING_INDUSTRY_OPTIONS } from './onboardingIndustryCatalog'
import {
  INDUSTRY_NAVIGATION_PROFILES,
  resolveIndustryNavigationLabel,
  resolveIndustryNavigationProfile,
} from './industryNavigationProfiles'

describe('industry navigation profiles', () => {
  it('provides exactly one real sidebar skeleton for every top-level category', () => {
    expect(Object.keys(INDUSTRY_NAVIGATION_PROFILES)).toHaveLength(9)
    expect(Object.keys(INDUSTRY_NAVIGATION_PROFILES).sort()).toEqual(
      ONBOARDING_INDUSTRY_CATEGORIES.map((item) => item.id).sort(),
    )
    for (const profile of Object.values(INDUSTRY_NAVIGATION_PROFILES)) {
      expect(profile.businessMenuKeys.length).toBeGreaterThanOrEqual(5)
      expect(new Set(profile.businessMenuKeys).size).toBe(profile.businessMenuKeys.length)
      expect(profile.businessMenuKeys).toContain('template-preview')
      expect(profile.previewMenuKeys).toContain('template-preview')
      expect(profile.deferredCapabilities.length).toBeGreaterThan(0)
    }
  })

  it('resolves every onboarding direction through its category skeleton', () => {
    for (const option of ONBOARDING_INDUSTRY_OPTIONS) {
      const resolved = resolveIndustryNavigationProfile(option.id)
      expect(resolved.categoryId).toBe(option.categoryId)
      expect(resolved.businessMenuKeys).toContain('template-preview')
      expect(resolved.previewMenuKeys).toContain('template-preview')
    }
  })

  it('keeps unavailable concepts out of real menu keys', () => {
    const manufacturing = resolveIndustryNavigationProfile('制造业')
    expect(manufacturing.businessMenuKeys).toEqual(
      expect.arrayContaining(['products', 'materials', 'inventory', 'orders', 'shipment-records']),
    )
    expect(manufacturing.deferredCapabilities).toEqual(expect.arrayContaining(['生产工单', '质检', 'BOM']))
    expect(manufacturing.businessMenuKeys).not.toEqual(expect.arrayContaining(['quality', 'bom', 'production-orders']))

    const software = resolveIndustryNavigationProfile('软件信息')
    expect(software.previewMenuKeys).toEqual(
      expect.arrayContaining(['customers', 'products', 'orders', 'shipment-records', 'persy-knowledge']),
    )
    expect(software.deferredCapabilities).toEqual(expect.arrayContaining(['项目管理', '合同管理']))
    expect(resolveIndustryNavigationLabel('软件信息', 'orders')).toBe('服务订单')
  })

  it('applies coating and attendance fine-grained overrides without mutating category defaults', () => {
    const coating = resolveIndustryNavigationProfile('涂料')
    expect(coating.menuLabels.materials).toBe('原材料仓库')
    expect(coating.menuLabels.print).toBe('标签打印')
    expect(coating.businessMenuKeys).toContain('template-preview')
    expect(coating.previewMenuKeys).toContain('template-preview')
    expect(coating.deferredCapabilities).toContain('批次质检')

    const attendance = resolveIndustryNavigationProfile('考勤')
    expect(attendance.menuLabels.products).toBe('人员管理')
    expect(attendance.businessMenuKeys).not.toContain('inventory')
    expect(attendance.businessMenuKeys).toContain('template-preview')
    expect(attendance.previewMenuKeys).toContain('template-preview')

    for (const industryId of ['餐饮', '物流']) {
      const resolved = resolveIndustryNavigationProfile(industryId)
      expect(resolved.businessMenuKeys).toContain('template-preview')
      expect(resolved.previewMenuKeys).toContain('template-preview')
    }

    expect(INDUSTRY_NAVIGATION_PROFILES.manufacturing.menuLabels.materials).toBe('物料管理')
  })
})
