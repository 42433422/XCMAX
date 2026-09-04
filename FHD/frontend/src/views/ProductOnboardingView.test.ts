import { describe, it, expect, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import ProductOnboardingView from './ProductOnboardingView.vue'
import { fetchIndustryBaseline, fetchOnboardingIndustryCatalog, seedOnboardingDemo } from '@/utils/platformShellApi'
import { LS_PRODUCT_FLOW_COMPLETED, LS_PRODUCT_FLOW_FIRST_TASK_PENDING, LS_PRODUCT_FLOW_PENDING_PROMPT } from '@/constants/productFlow'

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
  seedOnboardingDemo: vi.fn().mockResolvedValue({
    industry_id: '涂料',
    customer: { id: 1, name: '新手演示客户' },
    product: { id: 1, name: '新手演示商品' },
  }),
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
    routes: [
      { path: '/', name: 'chat', component: { template: '<div>chat</div>' } },
      { path: '/onboarding', name: 'product-onboarding', component: ProductOnboardingView, props: true },
    ],
  })
}

describe('ProductOnboardingView.vue', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    setActivePinia(createPinia())
    vi.mocked(fetchOnboardingIndustryCatalog).mockResolvedValue({
      open_packages: [],
      preview_packages: [],
      open_industry_ids: [],
    } as any)
    vi.mocked(fetchIndustryBaseline).mockResolvedValue({} as any)
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

    await wrapper.get('button.btn.primary').trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.query.step).toBe('industry')
    expect(wrapper.text()).toContain('先定行业')
  })

  it('seeds demo data before presenting the first AI order', async () => {
    const router = makeRouter()
    await router.push({ path: '/onboarding', query: { step: 'seed-demo' } })
    await router.isReady()
    const wrapper = mount(ProductOnboardingView, {
      global: { plugins: [router], stubs: { RouterLink: true } },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('先给您一套可以动手的数据')
    await wrapper.get('button.btn.primary').trigger('click')
    await flushPromises()

    expect(seedOnboardingDemo).toHaveBeenCalled()
    expect(router.currentRoute.value.query.step).toBe('first-ai-task')
    expect(wrapper.text()).toContain('跟着 AI 员工完成第一单')
    expect(wrapper.text()).toContain('新手演示客户')
  })

  it('re-reads the idempotent demo seed after reload and does not complete before the run', async () => {
    const router = makeRouter()
    await router.push({ path: '/onboarding', query: { step: 'first-ai-task' } })
    await router.isReady()
    const wrapper = mount(ProductOnboardingView, {
      global: { plugins: [router], stubs: { RouterLink: true } },
    })
    await flushPromises()

    await wrapper.get('button.btn.primary').trigger('click')
    await flushPromises()

    expect(seedOnboardingDemo).toHaveBeenCalled()
    expect(localStorage.getItem(LS_PRODUCT_FLOW_PENDING_PROMPT)).toContain('新手演示客户')
    expect(localStorage.getItem(LS_PRODUCT_FLOW_FIRST_TASK_PENDING)).toBe('1')
    expect(localStorage.getItem(LS_PRODUCT_FLOW_COMPLETED)).not.toBe('1')
    expect(router.currentRoute.value.name).toBe('chat')
  })

  it('keeps enterprise-filtered SUNBIRD industry as accessories packaging', async () => {
    vi.mocked(fetchOnboardingIndustryCatalog).mockResolvedValue({
      enterprise_filter_applied: true,
      open_industry_ids: ['饰品包装'],
      selected_industry_id: '饰品包装',
      open_packages: [
        {
          industry_id: '饰品包装',
          name: '饰品包装',
          scenario: '饰品与包装制品的产品、订单、库存和标签管理',
          product_name: '饰品包装行业包',
          mod_id: 'accessories-packaging-industry',
          selectable: true,
        },
      ],
      preview_packages: [
        {
          industry_id: '考勤',
          name: '考勤/排班',
          scenario: '考勤排班',
          product_name: '通用考勤模块',
          mod_id: 'attendance-industry',
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
    expect(openChips[0].text()).toContain('饰品包装')
    expect(openChips[0].classes()).toContain('active')
    expect(wrapper.find('.industry-pick--preview').text()).toContain('考勤/排班')
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
          product_name: '通用考勤模块',
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

    expect(wrapper.text()).toContain('装好后侧栏会出现')
    expect(wrapper.text()).toContain('考勤表转换')
    expect(wrapper.text()).toContain('人员管理')
    expect(wrapper.text()).toContain('考勤数据源')
    expect(wrapper.text()).toContain('考勤模板库')
  })

  it('keeps packaging shell labels while showing unified attendance capability', async () => {
    vi.mocked(fetchOnboardingIndustryCatalog).mockResolvedValue({
      enterprise_filter_applied: true,
      open_industry_ids: ['饰品包装'],
      selected_industry_id: '饰品包装',
      open_packages: [
        {
          industry_id: '饰品包装',
          name: '饰品包装',
          scenario: '饰品包装',
          product_name: '饰品包装行业包',
          mod_id: 'accessories-packaging-industry',
          selectable: true,
        },
      ],
      preview_packages: [],
    } as any)
    vi.mocked(fetchIndustryBaseline).mockResolvedValue({
      capability_mod_ids: ['attendance-industry'],
      groups: [],
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

    expect(wrapper.text()).toContain('饰品包装品管理')
    expect(wrapper.text()).toContain('包装标签打印')
    expect(wrapper.text()).toContain('考勤表转换')
  })
})
