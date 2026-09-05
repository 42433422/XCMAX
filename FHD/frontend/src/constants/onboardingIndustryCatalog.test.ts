import { describe, expect, it } from 'vitest'
import {
  listOnboardingIndustryOptions,
  ONBOARDING_INDUSTRY_CATEGORIES,
  ONBOARDING_INDUSTRY_OPTIONS,
} from './onboardingIndustryCatalog'

describe('onboardingIndustryCatalog', () => {
  it('covers broad company industry categories without duplicate ids', () => {
    const categoryIds = new Set(ONBOARDING_INDUSTRY_CATEGORIES.map((item) => item.id))
    const optionIds = ONBOARDING_INDUSTRY_OPTIONS.map((item) => item.id)
    expect(categoryIds.size).toBeGreaterThanOrEqual(9)
    expect(optionIds.length).toBeGreaterThanOrEqual(50)
    expect(new Set(optionIds).size).toBe(optionIds.length)
    expect(ONBOARDING_INDUSTRY_OPTIONS.every((item) => categoryIds.has(item.categoryId))).toBe(true)
  })

  it('keeps a compact popular set and searchable aliases', () => {
    const popular = ONBOARDING_INDUSTRY_OPTIONS.filter((item) => item.popular)
    expect(popular.length).toBeGreaterThanOrEqual(8)
    expect(popular.length).toBeLessThanOrEqual(12)
    expect(ONBOARDING_INDUSTRY_OPTIONS.find((item) => item.id === '软件信息')?.aliases).toContain('SaaS')
    expect(ONBOARDING_INDUSTRY_OPTIONS.find((item) => item.id === '人力资源')?.aliases).toContain('考勤')
  })

  it('returns defensive copies for component-side merging', () => {
    const first = listOnboardingIndustryOptions()
    first[0].aliases.push('changed')
    expect(listOnboardingIndustryOptions()[0].aliases).not.toContain('changed')
  })
})
