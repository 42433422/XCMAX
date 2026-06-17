import { describe, it, expect, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import ProductOnboardingView from './ProductOnboardingView.vue'
import { fetchOnboardingIndustryCatalog } from '@/utils/platformShellApi'

vi.mock('@/api/modStore', () => ({
  installHostFoundation: vi.fn().mockResolvedValue({ success: true }),
  installMod: vi.fn().mockResolvedValue({ success: true }),
  installCustomerDeliverySeed: vi.fn().mockResolvedValue({ success: true }),
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
    vi.mocked(fetchOnboardingIndustryCatalog).mockResolvedValue({
      open_packages: [],
      preview_packages: [],
      open_industry_ids: [],
    } as any)
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

  it('keeps enterprise-filtered SUNBIRD industries to attendance only', async () => {
    vi.mocked(fetchOnboardingIndustryCatalog).mockResolvedValue({
      enterprise_filter_applied: true,
      open_industry_ids: ['考勤'],
      selected_industry_id: '涂料',
      open_packages: [
        {
          industry_id: '考勤',
          name: '考勤/排班',
          scenario: '考勤排班',
          product_name: '考勤/排班行业包',
          mod_id: 'attendance-industry',
          selectable: true,
        },
      ],
      preview_packages: [
        {
          industry_id: '涂料',
          name: '涂料/油漆',
          scenario: '涂料化工批发',
          product_name: '涂料/油漆行业包',
          mod_id: 'coating-industry',
          selectable: false,
        },
      ],
    } as any)
    const router = makeRouter()
    await router.push({ path: '/onboarding', query: { step: 'industry' } })
    await router.isReady()
    const wrapper = mount(ProductOnboardingView, {
      global: {
        plugins: [router],
        stubs: { RouterLink: true },
      },
    })
    await flushPromises()

    const openChips = wrapper.findAll('.industry-pick--open .industry-chip')
    expect(openChips).toHaveLength(1)
    expect(openChips[0].text()).toContain('考勤/排班')
    expect(openChips[0].classes()).toContain('active')
    expect(wrapper.find('.industry-pick--preview').text()).toContain('涂料/油漆')
    expect(wrapper.text()).not.toContain('两套行业方向')
  })

  it('previews attendance sidebar labels on host-pack step', async () => {
    vi.mocked(fetchOnboardingIndustryCatalog).mockResolvedValue({
      enterprise_filter_applied: true,
      open_industry_ids: ['考勤'],
      selected_industry_id: '考勤',
      open_packages: [
        {
          industry_id: '考勤',
          name: '考勤/排班',
          scenario: '考勤排班',
          product_name: '考勤行业包',
          mod_id: 'attendance-industry',
          selectable: true,
        },
      ],
      preview_packages: [],
    } as any)
    const router = makeRouter()
    await router.push({ path: '/onboarding', query: { step: 'host-pack' } })
    await router.isReady()
    const wrapper = mount(ProductOnboardingView, {
      global: {
        plugins: [router],
        stubs: { RouterLink: true },
      },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('进入后侧栏将补齐')
    expect(wrapper.text()).toContain('考勤表转换')
    expect(wrapper.text()).toContain('人员管理')
    expect(wrapper.text()).toContain('考勤数据源')
    expect(wrapper.text()).toContain('考勤模板库')
  })
})
