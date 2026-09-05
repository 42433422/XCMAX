import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import erp from '../../../mods/xcagi-erp-domain-bridge/manifest.json'
import planner from '../../../mods/xcagi-planner-bridge/manifest.json'
import approval from '../../../mods/xcagi-approval-bridge/manifest.json'
import qsm from '../../../mods/sz-qsm-pro/manifest.json'
import type { ModInfo } from '@/types/modInfo'

const state = vi.hoisted(() => ({ industry: '制造业' }))
vi.mock('@/stores/industry', () => ({ useIndustryStore: () => ({ get currentIndustryId() { return state.industry } }) }))

import { useModsStore } from '@/stores/mods'
import { useAccountProfileStore } from '@/stores/accountProfile'
import { useVisibleNavItems } from './useVisibleNavItems'
import { GENERIC_HOST_MOD_IDS, MINIMAL_HOST_MOD_IDS } from '@/constants/genericModPack'
import { INDUSTRY_NAVIGATION_PROFILES, resolveIndustryNavigationProfile } from '@/constants/industryNavigationProfiles'
import { markHostPackAcknowledged, resetProductFlowState } from '@/constants/productFlow'
import { CORE_ROUTES } from '@/router/routes/core'
import { BUSINESS_ROUTES } from '@/router/routes/business'
import { SHELL_ROUTES } from '@/router/routes/shell'

const router = createRouter({ history: createMemoryHistory(), routes: [...CORE_ROUTES, ...BUSINESS_ROUTES, ...SHELL_ROUTES] })
const manifests = new Map<string, { id: string; name: string; frontend?: { menu?: ModInfo['menu']; menu_overrides?: ModInfo['menu_overrides'] } }>(
  [erp, planner, approval, qsm].map((manifest) => [manifest.id, manifest]),
)

function approvedListing(ids: readonly string[]) {
  // This is the already-authorized /api/mods result boundary, not a fake
  // frontend entitlement grant. Actual store/menu/filter code consumes it.
  useModsStore().mods = ids.map((id): ModInfo => {
    const manifest = manifests.get(id)
    return {
      id, name: manifest?.name || id, version: 'test', author: '', description: '',
      menu: manifest?.frontend?.menu, menu_overrides: manifest?.frontend?.menu_overrides, frontend: manifest?.frontend,
    }
  })
}

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  vi.stubEnv('VITE_XCAGI_EDITION', 'generic')
  vi.stubEnv('VITE_XCAGI_PRODUCT_SKU', 'enterprise')
  vi.stubEnv('VITE_XCMAX_ADMIN_CONSOLE', '')
  setActivePinia(createPinia())
  resetProductFlowState()
  const account = useAccountProfileStore()
  account.accountKind = 'enterprise'
  account.marketIsEnterprise = true
  account.marketIsAdmin = false
  state.industry = '制造业'
})

afterEach(() => vi.unstubAllEnvs())

describe('industry menus with real Mod and role filtering', () => {
  it.each(Object.keys(INDUSTRY_NAVIGATION_PROFILES))('%s keeps the prepared profile and real bridge menus consistent', (industry) => {
    state.industry = industry
    approvedListing(GENERIC_HOST_MOD_IDS)
    markHostPackAcknowledged()
    const profile = resolveIndustryNavigationProfile(industry)
    const entries = useVisibleNavItems().visibleNavItems.value
    const businessKeys = new Set<string>(Object.values(INDUSTRY_NAVIGATION_PROFILES).flatMap((item) => item.businessMenuKeys))
    const business = entries.filter((entry) => businessKeys.has(entry.key))
    expect(business.map((entry) => entry.key)).toEqual(profile.businessMenuKeys)
    for (const entry of business) {
      expect(router.hasRoute(entry.routeName), `${industry}: ${entry.key}`).toBe(true)
      expect(router.resolve({ name: entry.routeName }).matched.at(-1)?.components?.default).toBeDefined()
    }
    expect(entries.some((entry) => entry.key.startsWith('mod-erp-'))).toBe(false)
    expect(entries.some((entry) => entry.key.includes('brain'))).toBe(false)
  })

  it('does not display business profile entries before the generic foundation is prepared', () => {
    approvedListing(MINIMAL_HOST_MOD_IDS)
    const keys = useVisibleNavItems().visibleNavItems.value.map((entry) => entry.key)
    expect(keys).not.toContain('products')
    expect(keys).not.toContain('orders')
    expect(keys).not.toContain('mod-erp-products')
    expect(keys.some((key) => key === 'chat' || key === 'mod-planner-chat')).toBe(true)
  })

  it('does not invent a private customer workspace absent from the approved listing', () => {
    approvedListing(GENERIC_HOST_MOD_IDS)
    markHostPackAcknowledged()
    const entries = useVisibleNavItems().visibleNavItems.value
    expect(entries.some((entry) => entry.modId === 'sz-qsm-pro')).toBe(false)
    expect(entries.some((entry) => entry.key.includes('qsm'))).toBe(false)
  })

  it('retains the real private customer menu when the server has supplied that installed package', () => {
    approvedListing([...GENERIC_HOST_MOD_IDS, 'sz-qsm-pro'])
    useModsStore().activeModId = 'sz-qsm-pro'
    const entries = useVisibleNavItems().visibleNavItems.value
    expect(entries.find((entry) => entry.modId === 'sz-qsm-pro')).toMatchObject({ key: 'mod-qsm-pro-home', modPath: '/qsm-pro' })
  })

  it('uses generic service labels for an unknown industry with only the approved host foundation', () => {
    state.industry = '智能硬件服务'
    approvedListing(GENERIC_HOST_MOD_IDS)
    markHostPackAcknowledged()
    const entries = useVisibleNavItems().visibleNavItems.value
    expect(entries.find((entry) => entry.key === 'orders')?.name).toBe('服务订单')
    expect(entries.map((entry) => entry.name)).not.toContain('原材料仓库')
    expect(entries.map((entry) => entry.name)).not.toContain('标签打印')
    expect(entries.map((entry) => entry.name)).not.toContain('出货单管理')
  })
})
