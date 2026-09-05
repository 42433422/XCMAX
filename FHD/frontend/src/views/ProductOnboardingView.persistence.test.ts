import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import ProductOnboardingView from './ProductOnboardingView.vue'
import { useIndustryStore } from '@/stores/industry'
import { LS_PRODUCT_FLOW_PENDING_PROMPT } from '@/constants/productFlow'

const backend = vi.hoisted(() => ({
  industry: '涂料',
  modId: 'coating-industry',
  completed: false,
  company: vi.fn(),
  patch: vi.fn(),
  readIndustry: vi.fn(),
  baseline: vi.fn(),
  seed: vi.fn(),
  install: vi.fn(),
  alert: vi.fn(),
  validate: vi.fn(),
}))
vi.mock('@/api/auth', () => ({ authApi: { getSubscriptionStatus: vi.fn().mockResolvedValue({}), updateCompanyBrand: backend.company } }))
vi.mock('@/api/system', () => ({
  systemApi: {
    getIndustries: vi.fn().mockResolvedValue({ success: true, data: { industries: [] } }),
    getCurrentIndustry: backend.readIndustry,
  },
}))
vi.mock('@/utils/authSessionCache', () => ({
  validateEnterpriseSessionCached: backend.validate,
  invalidateEnterpriseSessionCache: vi.fn(),
}))
vi.mock('@/utils/workspacePrefsApi', () => ({ patchWorkspacePrefs: backend.patch, queueWorkspacePrefsSync: vi.fn() }))
vi.mock('@/utils/productSku', () => ({ fetchProductSku: vi.fn().mockResolvedValue('generic'), isEnterpriseEdition: () => true }))
vi.mock('@/utils/platformShellApi', () => ({
  clearDeliverableStatusCache: vi.fn(),
  fetchIndustryBaseline: backend.baseline,
  fetchDeliverableStatus: vi.fn().mockResolvedValue({ deliverable: true }),
  fetchOnboardingIndustryCatalog: vi.fn(async () => ({
    selected_industry_id: backend.industry,
    open_industry_ids: ['涂料', '考勤'],
    preview_packages: [],
    open_packages: [
      { industry_id: '涂料', mod_id: 'coating-industry' },
      { industry_id: '考勤', mod_id: 'attendance-industry' },
    ],
  })),
  seedOnboardingDemo: backend.seed,
}))
vi.mock('@/api/modStore', () => ({
  installHostFoundation: backend.install,
  installIndustrySeed: vi.fn().mockResolvedValue({ success: true }),
  installMod: vi.fn(),
  installCustomerDeliverySeed: vi.fn(),
}))
vi.mock('@/utils/appDialog', () => ({ appAlert: backend.alert }))
vi.mock('@/utils/hostPackOnboardingGate', () => ({ invalidateHostPackCompletionCache: vi.fn(), markHostPackSkippedThisSession: vi.fn() }))
vi.mock('@/composables/useTutorialCatalog', () => ({ useTutorialCatalog: () => ({ buildContext: vi.fn(() => ({})) }) }))

let wrapper: ReturnType<typeof mount> | undefined
function readyPlan(industry = '软件信息', ready = true) {
  return { industry_id: industry, baseline_ready: ready, groups: [], missing_required_mod_ids: ready ? [] : ['xcagi-erp-domain-bridge'] }
}
async function configuration(industry = '软件信息') {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'chat', component: { template: '<div>workspace</div>' } },
      { path: '/onboarding', name: 'product-onboarding', component: ProductOnboardingView },
    ],
  })
  await router.push({ path: '/onboarding', query: { step: 'host-pack', industry, company: '测试公司' } })
  await router.isReady()
  wrapper = mount(ProductOnboardingView, { global: { plugins: [router] } })
  await flushPromises()
  return router
}
async function enterWorkspace() {
  await wrapper!.get('.configuration-step .actions .primary').trigger('click')
  await flushPromises()
}

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
  vi.clearAllMocks()
  backend.industry = '涂料'
  backend.modId = 'coating-industry'
  backend.completed = false
  backend.validate.mockResolvedValue(true)
  backend.company.mockImplementation(async (name: string) => ({
    success: true,
    company_brand: name,
    tenant_name: name,
    persistence_scope: 'account',
  }))
  backend.patch.mockImplementation(async (partial: Record<string, unknown>) => {
    if (typeof partial.selected_industry_id === 'string') backend.industry = partial.selected_industry_id
    if (typeof partial.industry_mod_id === 'string') backend.modId = partial.industry_mod_id
    if (partial.product_flow_completed === true) backend.completed = true
    return { success: true, data: partial }
  })
  backend.readIndustry.mockImplementation(async () => ({ success: true, data: { id: backend.industry, name: backend.industry } }))
  backend.baseline.mockImplementation(async (id: string) => readyPlan(id))
  backend.install.mockResolvedValue({ success: false, message: '功能尚未安装' })
})
afterEach(() => {
  wrapper?.unmount()
  wrapper = undefined
})

describe('configuration resumes with the displayed persisted industry', () => {
  it('binds a deep-linked new industry and clears its old package before completion', async () => {
    const router = await configuration()
    expect(wrapper!.text()).toContain('软件与信息技术')
    await enterWorkspace()
    expect(backend.industry).toBe('软件信息')
    expect(backend.modId).toBe('')
    expect(useIndustryStore().currentIndustryId).toBe('软件信息')
    expect(backend.baseline).toHaveBeenCalledWith('软件信息', true)
    expect(backend.completed).toBe(true)
    expect(router.currentRoute.value.path).toBe('/')
    expect(backend.seed).not.toHaveBeenCalled()
    expect(localStorage.getItem(LS_PRODUCT_FLOW_PENDING_PROMPT)).toBeNull()
  })

  it.each(['company', 'industry', 'refresh', 'completion'])('does not leave configuration when %s fails', async (stage) => {
    const router = await configuration()
    if (stage === 'company') backend.company.mockRejectedValue(new Error('公司保存失败'))
    if (stage === 'industry') backend.patch.mockResolvedValue({ success: false })
    if (stage === 'refresh') backend.readIndustry.mockResolvedValue({ success: true, data: { id: '涂料', name: '涂料' } })
    if (stage === 'completion')
      backend.patch.mockImplementation(async (partial) => {
        if (partial.selected_industry_id) {
          backend.industry = partial.selected_industry_id
          return { success: true }
        }
        return { success: false }
      })
    await enterWorkspace()
    expect(backend.completed).toBe(false)
    expect(router.currentRoute.value.path).toBe('/onboarding')
    expect(backend.alert).toHaveBeenCalled()
    expect(backend.seed).not.toHaveBeenCalled()
  })

  it('rechecks readiness after binding instead of trusting the mounted ready state', async () => {
    const router = await configuration()
    backend.baseline.mockResolvedValue(readyPlan('软件信息', false))
    await enterWorkspace()
    expect(backend.industry).toBe('软件信息')
    expect(backend.install).toHaveBeenCalled()
    expect(backend.completed).toBe(false)
    expect(router.currentRoute.value.path).toBe('/onboarding')
  })

  it('binds attendance with its real package without creating or queuing demo data', async () => {
    const router = await configuration('考勤')
    await enterWorkspace()
    expect(backend.industry).toBe('考勤')
    expect(backend.modId).toBe('attendance-industry')
    expect(backend.completed).toBe(true)
    expect(router.currentRoute.value.path).toBe('/')
    expect(backend.seed).not.toHaveBeenCalled()
    expect(localStorage.getItem(LS_PRODUCT_FLOW_PENDING_PROMPT)).toBeNull()
  })

  it('requires an active session before company, industry or completion writes', async () => {
    const router = await configuration()
    backend.validate.mockResolvedValue(false)
    await enterWorkspace()
    expect(backend.company).not.toHaveBeenCalled()
    expect(backend.patch).not.toHaveBeenCalled()
    expect(backend.completed).toBe(false)
    expect(router.currentRoute.value.path).toBe('/onboarding')
  })
})
