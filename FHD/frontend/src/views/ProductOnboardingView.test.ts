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

  it('mounts company identity step', async () => {
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
    expect(wrapper.text()).toContain('您的公司叫什么？')
    expect(wrapper.find('.company-name-input').exists()).toBe(true)
  })

  it('keeps industry exploration open while marking entitled direction', async () => {
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
    expect(openChips.length).toBeGreaterThan(5)
    expect(openChips.find((chip) => chip.text().includes('考勤/排班'))?.text()).toContain('专属方案')
    expect(openChips.find((chip) => chip.text().includes('涂料/油漆'))?.text()).toContain('通用能力可用')
    expect(wrapper.find('.industry-search').exists()).toBe(true)
  })

  it('offers a broad categorized catalog while keeping the default set compact', async () => {
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

    expect(wrapper.findAll('.industry-category-rail button').length).toBeGreaterThan(9)
    expect(wrapper.findAll('.industry-chip').length).toBeLessThanOrEqual(12)
    expect(wrapper.find('.industry-open-hint').text()).toContain('覆盖')

    const manufacturing = wrapper.findAll('.industry-category-rail button').find((item) => item.text().includes('制造工业'))!
    await manufacturing.trigger('click')
    expect(wrapper.text()).toContain('机械与设备制造')
    expect(wrapper.text()).toContain('电子与电器制造')

    const all = wrapper.findAll('.industry-category-rail button').find((item) => item.text().includes('全部'))!
    await all.trigger('click')
    expect(wrapper.findAll('.industry-chip').length).toBeLessThanOrEqual(10)
    expect(wrapper.find('.industry-more-button').text()).toContain('查看另外')
    await wrapper.find('.industry-more-button').trigger('click')
    expect(wrapper.findAll('.industry-chip').length).toBeGreaterThan(50)
  })

  it('searches the full catalog through natural aliases', async () => {
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

    await wrapper.find('.industry-search input').setValue('SaaS')
    const chips = wrapper.findAll('.industry-chip')
    expect(chips).toHaveLength(1)
    expect(chips[0].text()).toContain('软件与信息技术')
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

    expect(wrapper.text()).toContain('可用行业侧栏')
    expect(wrapper.text()).toContain('以上入口均有可用页面')
    expect(wrapper.text()).toContain('人员管理')
    expect(wrapper.text()).toContain('考勤数据源')
    expect(wrapper.text()).toContain('部门管理')
  })
})
