import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import ProductOnboardingView from './ProductOnboardingView.vue'

vi.mock('@/api/modStore', () => ({
  installHostFoundation: vi.fn().mockResolvedValue({ success: true }),
  installMod: vi.fn().mockResolvedValue({ success: true }),
  installOfficeEmployeePack: vi.fn().mockResolvedValue({ success: true }),
  installIndustrySeed: vi.fn().mockResolvedValue({ success: true }),
}))
vi.mock('@/utils/productSku', () => ({
  fetchProductSku: vi.fn().mockResolvedValue({ edition: 'personal' }),
  isEnterpriseEdition: vi.fn(() => false),
}))
vi.mock('@/utils/appDialog', () => ({ appAlert: vi.fn() }))
vi.mock('@/utils/platformShellApi', () => ({
  fetchOnboardingIndustryCatalog: vi.fn().mockResolvedValue({
    open_packages: [],
    preview_packages: [],
    open_industry_ids: [],
  }),
  fetchIndustryBaseline: vi.fn().mockResolvedValue({}),
  clearDeliverableStatusCache: vi.fn(),
  fetchDeliverableStatus: vi.fn().mockResolvedValue({ deliverable: true }),
}))
vi.mock('@/composables/useTutorialCatalog', () => ({
  useTutorialCatalog: () => ({ buildContext: vi.fn(() => ({})) }),
}))
vi.mock('@/utils/hostPackOnboardingGate', () => ({
  invalidateHostPackCompletionCache: vi.fn(),
  markHostPackSkippedThisSession: vi.fn(),
}))
vi.mock('@/tutorial/promptAdvancedTutorial', () => ({
  promptAdvancedTutorialAfterInstall: vi.fn(),
  resolveRouteNameFromPath: vi.fn(() => 'chat'),
}))

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/onboarding', name: 'onboarding', component: ProductOnboardingView, props: true }],
  })
}

describe('ProductOnboardingView.vue', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('mounts welcome hero', async () => {
    const router = makeRouter()
    await router.push({ path: '/onboarding', query: { step: 'welcome' } })
    await router.isReady()
    const wrapper = mount(ProductOnboardingView, {
      global: {
        plugins: [router],
        stubs: { RouterLink: true },
      },
    })
    expect(wrapper.find('.product-flow').exists()).toBe(true)
    expect(wrapper.text()).toContain('认识 XC')
  })
})
