import { afterEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import { CORE_ROUTES } from '@/router/routes/core'
import { BUSINESS_ROUTES } from '@/router/routes/business'
import { SHELL_ROUTES } from '@/router/routes/shell'
import { resolveNavRouteName } from './navRouteAliases'
import { INDUSTRY_NAVIGATION_PROFILES, resolveIndustryNavigationProfile } from './industryNavigationProfiles'
import { resolveCoreNavLabel } from '@/utils/coreNavLabel'

// Resolve the production route records, including the actual approval alias.
// No fake route is added to make a proposed business capability look available.
const router = createRouter({ history: createMemoryHistory(), routes: [...CORE_ROUTES, ...BUSINESS_ROUTES, ...SHELL_ROUTES] })

afterEach(() => vi.unstubAllEnvs())

describe('industry profiles against the real host route registry', () => {
  it.each(Object.keys(INDUSTRY_NAVIGATION_PROFILES))('%s resolves every business and preview entry to a real component', (id) => {
    const profile = resolveIndustryNavigationProfile(id)
    const keys = new Set([...profile.businessMenuKeys, ...profile.previewMenuKeys])
    for (const key of keys) {
      const name = resolveNavRouteName(key)
      expect(router.hasRoute(name), `${id}: ${key} -> ${name}`).toBe(true)
      const target = router.resolve({ name })
      expect(target.matched.length, `${id}: ${key}`).toBeGreaterThan(0)
      expect(target.matched.at(-1)?.components?.default, `${id}: ${key}`).toBeDefined()
      expect(target.path).not.toMatch(/(?:brain|mod-store|onboarding)/)
    }
    const emittedNames = [...keys].map((key) => resolveCoreNavLabel(key, id, null))
    for (const unavailable of profile.deferredCapabilities) expect(emittedNames).not.toContain(unavailable)
  })

  it.each(['任意自定义行业', '软件信息', 'manufacturing'])('%s does not inherit coating-only terms', (industry) => {
    expect(resolveCoreNavLabel('products', industry, null)).not.toBe('涂料产品')
    expect(resolveCoreNavLabel('materials', industry, null)).not.toBe('原材料仓库')
    expect(resolveCoreNavLabel('print', industry, null)).not.toBe('标签打印')
    expect(resolveCoreNavLabel('orders', industry, null)).not.toBe('出货单管理')
    expect(resolveIndustryNavigationProfile(industry).id).toBe(industry)
  })

  it('keeps retired Brain bookmarks redirected and out of every industry profile', () => {
    expect(router.resolve('/brain').matched.at(-1)?.redirect).toBeDefined()
    expect(router.resolve('/mod/xcagi-planner-bridge/brain').matched.at(-1)?.redirect).toBeDefined()
    for (const profile of Object.values(INDUSTRY_NAVIGATION_PROFILES)) {
      expect([...profile.businessMenuKeys, ...profile.previewMenuKeys]).not.toContain('brain')
    }
  })
})
