import { describe, it, expect, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h, ref } from 'vue'
import { createRouter, createMemoryHistory, RouterView } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import ProductOnboardingView from './ProductOnboardingView.vue'
import { useChatViewHost, type UseChatViewHostDeps } from '@/composables/useChatViewHost'
import { fetchIndustryBaseline, fetchOnboardingIndustryCatalog, seedOnboardingDemo } from '@/utils/platformShellApi'
import { LS_PRODUCT_FLOW_COMPLETED, LS_PRODUCT_FLOW_FIRST_TASK_PENDING, LS_PRODUCT_FLOW_PENDING_PROMPT, queueFirstAiTaskPrompt, bindPendingFirstAiTaskRun, readPendingFirstAiTaskRunId } from '@/constants/productFlow'

import { appAlert } from '@/utils/appDialog'

vi.mock('@/api/auth', () => ({ authApi: { getSubscriptionStatus: vi.fn().mockResolvedValue({ data: null }) } }))
vi.mock('@/utils/authSessionCache', () => ({ validateEnterpriseSessionCached: vi.fn().mockResolvedValue(true), invalidateEnterpriseSessionCache: vi.fn() }))
vi.mock('@/api/system', () => ({ systemApi: {
  getIndustries: vi.fn().mockResolvedValue({ success: true, data: { industries: [] } }),
  getCurrentIndustry: vi.fn().mockResolvedValue({ success: true, data: { id: '涂料', name: '涂料' } }),
} }))
vi.mock('@/utils/workspacePrefsApi', () => ({
  patchWorkspacePrefs: vi.fn().mockResolvedValue({ success: true }),
  queueWorkspacePrefsSync: vi.fn(),
}))

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
      { path: '/attendance-industry/personnel', name: 'attendance-industry-personnel', component: { template: '<div>人员管理</div>' } },
      { path: '/onboarding', name: 'product-onboarding', component: ProductOnboardingView, props: true },
    ],
  })
}

function makeFirstTaskRouter() {
  const router = makeRouter()
  const messageInput = ref('')
  const sendMessage = vi.fn(async () => messageInput.value)
  const ChatHost = defineComponent({
    setup() {
      useChatViewHost({
        modsStore: { initialize: vi.fn().mockResolvedValue(undefined), isLoaded: true } as UseChatViewHostDeps['modsStore'],
        modsFromStore: ref([{ id: 'xcagi-planner-bridge' }]),
        autoRefreshStarredWechat: ref(false),
        isTaskPaneResizable: ref(true),
        messageInput,
        latestAssistantPush: ref(null),
        syncSessionMessages: vi.fn().mockResolvedValue(undefined),
        chatHandleAutoAction: vi.fn(),
        sendMessage: async () => { await sendMessage() },
        batchCalculateHeights: vi.fn(),
        stopMessageTts: vi.fn(),
        cleanupVoiceInput: vi.fn(),
        stopTaskPaneResize: vi.fn(),
      })
      return () => h('div', { 'data-testid': 'chat-host' }, messageInput.value)
    },
  })
  router.addRoute({ path: '/', name: 'chat', component: ChatHost })
  router.addRoute({ path: '/data-sources', name: 'data-sources', component: { template: '<div>数据来源</div>' } })
  return { router, sendMessage }
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
    expect(wrapper.text()).toContain('您的公司叫什么')

    await wrapper.get('#onboarding-company').setValue('新公司')
    await wrapper.get('button.btn.primary').trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.query.step).toBe('industry')
    expect(wrapper.text()).toContain('属于什么行业')
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

  it('runs the tutorial first order in chat instead of returning to its data-source page', async () => {
    vi.mocked(fetchIndustryBaseline).mockResolvedValue({ baseline_ready: true, groups: [] } as any)
    const { router, sendMessage } = makeFirstTaskRouter()
    await router.push({ path: '/onboarding', query: { step: 'host-pack', from: 'tutorial', redirect: '/data-sources' } })
    await router.isReady()
    const wrapper = mount(RouterView, { global: { plugins: [router] } })
    try {
      await flushPromises()
      expect(wrapper.get('button.btn.primary').text()).toContain('进入我的工作空间')
      expect(seedOnboardingDemo).not.toHaveBeenCalled()
      const optionalExample = wrapper.findAll('button').find((button) => button.text() === '查看演示业务体验')
      expect(optionalExample).toBeDefined()
      await optionalExample!.trigger('click')
      await flushPromises()
      expect(router.currentRoute.value.query.step).toBe('seed-demo')
      expect(seedOnboardingDemo).not.toHaveBeenCalled()
      await wrapper.get('button.btn.primary').trigger('click')
      await flushPromises()
      expect(router.currentRoute.value.query).toMatchObject({ step: 'first-ai-task', from: 'tutorial', redirect: '/data-sources' })

      await wrapper.get('button.btn.primary').trigger('click')
      await flushPromises()

      expect(router.currentRoute.value.name).toBe('chat')
      expect(wrapper.get('[data-testid="chat-host"]').text()).toContain('新手演示客户')
      expect(wrapper.text()).toContain('新手演示商品')
      expect(sendMessage).toHaveBeenCalledTimes(1)
      expect(localStorage.getItem(LS_PRODUCT_FLOW_PENDING_PROMPT)).toBeNull()
      expect(localStorage.getItem(LS_PRODUCT_FLOW_FIRST_TASK_PENDING)).toBe('1')
      expect(localStorage.getItem(LS_PRODUCT_FLOW_COMPLETED)).not.toBe('1')

      await router.push('/data-sources')
      await router.push('/')
      await flushPromises()
      expect(sendMessage).toHaveBeenCalledTimes(1)
    } finally {
      wrapper.unmount()
    }
  })

  it('keeps the tutorial return button on its source page without starting a first order', async () => {
    const { router, sendMessage } = makeFirstTaskRouter()
    await router.push({ path: '/onboarding', query: { step: 'first-ai-task', from: 'tutorial', redirect: '/data-sources' } })
    await router.isReady()
    const wrapper = mount(RouterView, { global: { plugins: [router] } })
    try {
      await flushPromises()
      const returnButton = wrapper.get('.product-flow-footer button.btn.text')
      expect(returnButton.text()).toBe('返回上一页')
      await returnButton.trigger('click')
      await flushPromises()

      expect(router.currentRoute.value.name).toBe('data-sources')
      expect(wrapper.text()).toBe('数据来源')
      expect(sendMessage).not.toHaveBeenCalled()
      expect(localStorage.getItem(LS_PRODUCT_FLOW_PENDING_PROMPT)).toBeNull()
      expect(localStorage.getItem(LS_PRODUCT_FLOW_FIRST_TASK_PENDING)).toBeNull()
    } finally {
      wrapper.unmount()
    }
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

    const selected = wrapper.get('[role="option"][aria-selected="true"]')
    expect(selected.text()).toContain('饰品包装')
    expect(selected.classes()).toContain('active')
    expect(wrapper.text()).not.toContain('即将开放')
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

    expect(wrapper.text()).toContain('准备完成后可使用')
    expect(wrapper.text()).toContain('考勤工作区')
    expect(wrapper.text()).toContain('人员管理')
    expect(wrapper.text()).not.toContain('再用演示数据体验操作')
    expect(wrapper.text()).toContain('部门管理')
    expect(wrapper.text()).toContain('考勤查询')
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
    expect(wrapper.text()).toContain('考勤工作区')
  })

  describe('attendance roster onboarding', () => {
    beforeEach(() => {
      vi.mocked(fetchOnboardingIndustryCatalog).mockResolvedValue({
        open_industry_ids: ['考勤'],
        selected_industry_id: '考勤',
        open_packages: [{ industry_id: '考勤', name: '考勤/排班', mod_id: 'attendance-industry', selectable: true }],
        preview_packages: [],
      } as any)
    })

    it.each(['seed-demo', 'first-ai-task'])('opens the real roster from %s without ERP seed, shipment or completion', async (step) => {
      const oldPrompt = '新手第一单，请创建演示出货单'
      queueFirstAiTaskPrompt(oldPrompt)
      expect(bindPendingFirstAiTaskRun('old-shipment-run', oldPrompt)).toBe(true)
      const router = makeRouter()
      await router.push({ path: '/onboarding', query: { step } })
      await router.isReady()
      const wrapper = mount(ProductOnboardingView, { global: { plugins: [router] } })
      await flushPromises()

      expect(wrapper.text()).toContain('先到考勤工作区确认名单')
      expect(wrapper.text()).toContain('已有名单')
      expect(wrapper.text()).toContain('尚无名单')
      expect(wrapper.text()).toContain('按账号开通')
      expect(wrapper.text()).not.toContain('演示出货单')
      expect(wrapper.text()).not.toContain('新手演示客户')
      expect(localStorage.getItem(LS_PRODUCT_FLOW_PENDING_PROMPT)).toBeNull()
      expect(localStorage.getItem(LS_PRODUCT_FLOW_FIRST_TASK_PENDING)).toBeNull()
      expect(readPendingFirstAiTaskRunId()).toBe('')

      await wrapper.get('button.btn.primary').trigger('click')
      await flushPromises()
      expect(router.currentRoute.value.name).toBe('attendance-industry-personnel')
      expect(seedOnboardingDemo).not.toHaveBeenCalled()
      expect(localStorage.getItem(LS_PRODUCT_FLOW_COMPLETED)).not.toBe('1')
      expect(localStorage.getItem(LS_PRODUCT_FLOW_FIRST_TASK_PENDING)).toBeNull()
      wrapper.unmount()
    })

    it('returns to installation when the attendance workspace is unavailable', async () => {
      const router = makeRouter()
      router.removeRoute('attendance-industry-personnel')
      await router.push({ path: '/onboarding', query: { step: 'first-ai-task' } })
      await router.isReady()
      const wrapper = mount(ProductOnboardingView, { global: { plugins: [router] } })
      await flushPromises()
      await wrapper.get('button.btn.primary').trigger('click')
      await flushPromises()
      expect(appAlert).toHaveBeenCalledWith('考勤工作区尚未准备好，请先安装考勤功能并重新检测。')
      expect(router.currentRoute.value.query.step).toBe('host-pack')
      expect(seedOnboardingDemo).not.toHaveBeenCalled()
      expect(localStorage.getItem(LS_PRODUCT_FLOW_COMPLETED)).not.toBe('1')
      expect(localStorage.getItem(LS_PRODUCT_FLOW_PENDING_PROMPT)).toBeNull()
      wrapper.unmount()
    })

    it('continues from prepared attendance functions without generating demo ERP data', async () => {
      vi.mocked(fetchIndustryBaseline).mockResolvedValue({ baseline_ready: true, groups: [] } as any)
      const router = makeRouter()
      await router.push({ path: '/onboarding', query: { step: 'host-pack' } })
      await router.isReady()
      const wrapper = mount(ProductOnboardingView, { global: { plugins: [router] } })
      await flushPromises()
      const next = wrapper.findAll('button').find((button) => button.text() === '核对考勤名单')
      expect(next).toBeDefined()
      await next!.trigger('click')
      await flushPromises()
      expect(router.currentRoute.value.query.step).toBe('first-ai-task')
      expect(wrapper.text()).toContain('先到考勤工作区确认名单')
      expect(seedOnboardingDemo).not.toHaveBeenCalled()
      expect(localStorage.getItem(LS_PRODUCT_FLOW_COMPLETED)).not.toBe('1')
      wrapper.unmount()
    })
  })
})
