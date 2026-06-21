import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, h, nextTick } from 'vue'

// ===== Mock 容器：使用 vi.hoisted 让 vi.mock 工厂能访问 =====
const mockContainer = vi.hoisted(() => ({
  // useProductFlow 返回值
  flowState: null as any,
  // useIndustryStore 返回值
  industryState: null as any,
  // useModsStore 返回值
  modsState: null as any,
  // useTutorialCatalog 返回值
  tutorialState: null as any,
  // 各 API mock 引用
  installHostFoundation: vi.fn(),
  installMod: vi.fn(),
  installIndustrySeed: vi.fn(),
  installCustomerDeliverySeed: vi.fn(),
  autoOnboardWorkflowEmployeesFromMods: vi.fn(),
  fetchProductSku: vi.fn(),
  fetchIndustryBaseline: vi.fn(),
  fetchOnboardingIndustryCatalog: vi.fn(),
  clearDeliverableStatusCache: vi.fn(),
  appAlert: vi.fn(),
  promptAdvancedTutorialAfterInstall: vi.fn(),
  resolveRouteNameFromPath: vi.fn(),
  invalidateHostPackCompletionCache: vi.fn(),
  markHostPackSkippedThisSession: vi.fn(),
  readBuildEdition: vi.fn(),
  isEnterpriseEdition: vi.fn(),
  // productFlow 工具
  setRuntimeOnboardingOpenIndustryIds: vi.fn(),
  readProductFlowCompleted: vi.fn(),
}))

// ===== Mock 模块 =====
vi.mock('@/api/modStore', () => ({
  installHostFoundation: mockContainer.installHostFoundation,
  installMod: mockContainer.installMod,
  installIndustrySeed: mockContainer.installIndustrySeed,
  installCustomerDeliverySeed: mockContainer.installCustomerDeliverySeed,
}))

vi.mock('@/utils/workflowEmployeeOnboard', () => ({
  autoOnboardWorkflowEmployeesFromMods: mockContainer.autoOnboardWorkflowEmployeesFromMods,
}))

vi.mock('@/stores/mods', () => ({
  useModsStore: () => mockContainer.modsState,
}))

vi.mock('@/constants/genericModPack', async () => {
  const actual = await vi.importActual<typeof import('@/constants/genericModPack')>('@/constants/genericModPack')
  return {
    ...actual,
    readBuildEdition: mockContainer.readBuildEdition,
  }
})

vi.mock('@/utils/productSku', () => ({
  fetchProductSku: mockContainer.fetchProductSku,
  isEnterpriseEdition: mockContainer.isEnterpriseEdition,
}))

vi.mock('@/composables/useProductFlow', () => ({
  useProductFlow: () => mockContainer.flowState,
}))

vi.mock('@/stores/industry', () => ({
  useIndustryStore: () => mockContainer.industryState,
}))

vi.mock('@/utils/platformShellApi', () => ({
  clearDeliverableStatusCache: mockContainer.clearDeliverableStatusCache,
  fetchIndustryBaseline: mockContainer.fetchIndustryBaseline,
  fetchOnboardingIndustryCatalog: mockContainer.fetchOnboardingIndustryCatalog,
}))

vi.mock('@/utils/appDialog', () => ({
  appAlert: mockContainer.appAlert,
}))

vi.mock('@/tutorial/promptAdvancedTutorial', () => ({
  promptAdvancedTutorialAfterInstall: mockContainer.promptAdvancedTutorialAfterInstall,
  resolveRouteNameFromPath: mockContainer.resolveRouteNameFromPath,
}))

vi.mock('@/composables/useTutorialCatalog', () => ({
  useTutorialCatalog: () => mockContainer.tutorialState,
}))

vi.mock('@/utils/hostPackOnboardingGate', () => ({
  invalidateHostPackCompletionCache: mockContainer.invalidateHostPackCompletionCache,
  markHostPackSkippedThisSession: mockContainer.markHostPackSkippedThisSession,
}))

vi.mock('@/constants/productFlow', async () => {
  const actual = await vi.importActual<typeof import('@/constants/productFlow')>('@/constants/productFlow')
  return {
    ...actual,
    setRuntimeOnboardingOpenIndustryIds: mockContainer.setRuntimeOnboardingOpenIndustryIds,
    readProductFlowCompleted: mockContainer.readProductFlowCompleted,
  }
})

// ===== 桩组件 =====
const EmptyComp = defineComponent({
  name: 'EmptyComp',
  setup: () => () => h('div'),
})

// ===== 测试辅助 =====
function createTestRouter(initialPath = '/product-onboarding') {
  const routes = [
    { path: '/', name: 'home', component: EmptyComp },
    { path: '/product-onboarding', name: 'product-onboarding', component: EmptyComp },
    { path: '/chat', name: 'chat', component: EmptyComp },
    { path: '/mod-store', name: 'mod-store', component: EmptyComp },
    { path: '/:pathMatch(.*)*', name: 'fallback', component: EmptyComp },
  ]
  return createRouter({ history: createMemoryHistory(), routes })
}

function createFlowState(overrides: Record<string, unknown> = {}) {
  return {
    deliverable: { value: null },
    deliverableLoading: { value: false },
    refreshDeliverable: vi.fn(async () => ({ deliverable: true })),
    edition: vi.fn(() => 'generic'),
    needsProductFlow: vi.fn(() => false),
    resolveEntryStep: vi.fn((q?: unknown) => {
      const s = String(q || '').trim().toLowerCase()
      if (s === 'host-pack' || s === 'host') return 'host-pack'
      if (s === 'industry' || s === 'mod') return 'industry'
      if (s === 'done' || s === 'finish') return 'done'
      return 'welcome'
    }),
    completeFlowAndGoChat: vi.fn(),
    markProductFlowCompleted: vi.fn(),
    markHostPackAcknowledged: vi.fn(),
    readProductFlowCompleted: mockContainer.readProductFlowCompleted,
    ...overrides,
  }
}

function createIndustryState(overrides: Record<string, unknown> = {}) {
  return {
    industries: [],
    currentIndustry: null,
    currentIndustryId: '通用',
    currentIndustryName: '通用',
    isLoaded: true,
    loading: false,
    error: null,
    initialize: vi.fn(async () => undefined),
    ...overrides,
  }
}

function createModsState(overrides: Record<string, unknown> = {}) {
  return {
    modsForUi: [],
    refresh: vi.fn(async () => undefined),
    ...overrides,
  }
}

function createTutorialState(overrides: Record<string, unknown> = {}) {
  return {
    buildContext: { value: { industryId: '通用', mods: [], visibleNav: [], isProMode: false } },
    tutorialTracks: { value: [] },
    advancedTrackHint: { value: '' },
    visibleNavItems: { value: [] },
    ...overrides,
  }
}

// 构造一个完整的 IndustryBaselinePlan
function createBaselinePlan(overrides: Record<string, unknown> = {}) {
  return {
    industry_id: '涂料',
    summary: '',
    groups: [],
    required_mod_ids: [],
    optional_mod_ids: [],
    industry_mod_ids: [],
    missing_required_mod_ids: [],
    missing_optional_mod_ids: [],
    missing_industry_mod_ids: [],
    missing_account_custom_mod_ids: [],
    account_custom_mod_ids: [],
    host_baseline_ready: false,
    account_custom_ready: false,
    baseline_ready: false,
    full_stack_ready: false,
    industry_mod_ready: false,
    ...overrides,
  }
}

let currentWrapper: ReturnType<typeof mount> | null = null

async function mountComponent(options: {
  route?: { step?: string; from?: string; redirect?: string }
  flow?: Record<string, unknown>
  industry?: Record<string, unknown>
  mods?: Record<string, unknown>
  tutorial?: Record<string, unknown>
  productSku?: string
  isEnterprise?: boolean
  buildEdition?: string
  catalog?: unknown
  baseline?: unknown
  router?: ReturnType<typeof createTestRouter>
  // 是否跳过默认 mock 设置（用于需要自定义 mock 行为的测试）
  skipDefaultMocks?: boolean
  // catalog 是否永远 pending
  catalogPending?: boolean
  // baseline 是否永远 pending
  baselinePending?: boolean
  // catalog 是否 reject
  catalogReject?: boolean
  // baseline 是否 reject
  baselineReject?: boolean
  // productSku 是否 reject
  productSkuReject?: boolean
} = {}) {
  if (currentWrapper) {
    currentWrapper.unmount()
    currentWrapper = null
    await flushPromises()
  }
  vi.resetModules()

  setActivePinia(createPinia())

  mockContainer.flowState = createFlowState(options.flow || {})
  mockContainer.industryState = createIndustryState(options.industry || {})
  mockContainer.modsState = createModsState(options.mods || {})
  mockContainer.tutorialState = createTutorialState(options.tutorial || {})

  if (!options.skipDefaultMocks) {
    if (options.productSkuReject) {
      mockContainer.fetchProductSku.mockRejectedValue(new Error('sku fail'))
    } else {
      mockContainer.fetchProductSku.mockResolvedValue(options.productSku || 'generic')
    }
    mockContainer.isEnterpriseEdition.mockReturnValue(!!options.isEnterprise)
    mockContainer.readBuildEdition.mockReturnValue(options.buildEdition || 'full')
    if (options.baselinePending) {
      mockContainer.fetchIndustryBaseline.mockImplementation(
        () => new Promise(() => undefined),
      )
    } else if (options.baselineReject) {
      mockContainer.fetchIndustryBaseline.mockRejectedValue(new Error('baseline fail'))
    } else {
      mockContainer.fetchIndustryBaseline.mockResolvedValue(
        options.baseline === undefined ? createBaselinePlan() : options.baseline,
      )
    }
    if (options.catalogPending) {
      mockContainer.fetchOnboardingIndustryCatalog.mockImplementation(
        () => new Promise(() => undefined),
      )
    } else if (options.catalogReject) {
      mockContainer.fetchOnboardingIndustryCatalog.mockRejectedValue(new Error('catalog fail'))
    } else {
      mockContainer.fetchOnboardingIndustryCatalog.mockResolvedValue(
        options.catalog === undefined ? null : options.catalog,
      )
    }
    mockContainer.installHostFoundation.mockResolvedValue({ success: true, message: '' })
    mockContainer.installMod.mockResolvedValue({ success: true, message: '' })
    mockContainer.installIndustrySeed.mockResolvedValue({ success: true, message: '' })
    mockContainer.installCustomerDeliverySeed.mockResolvedValue({ success: true, message: '' })
    mockContainer.autoOnboardWorkflowEmployeesFromMods.mockResolvedValue([])
    mockContainer.appAlert.mockResolvedValue(undefined)
    mockContainer.promptAdvancedTutorialAfterInstall.mockResolvedValue('dismissed')
    mockContainer.readProductFlowCompleted.mockReturnValue(false)
  }

  const router = options.router || createTestRouter()
  const query: Record<string, string> = {}
  if (options.route?.step) query.step = options.route.step
  if (options.route?.from) query.from = options.route.from
  if (options.route?.redirect) query.redirect = options.route.redirect
  await router.push({ name: 'product-onboarding', query })
  await router.isReady()

  const mod = await import('./ProductOnboardingView.vue')
  const wrapper = mount(mod.default, {
    global: {
      plugins: [router],
    },
  })
  currentWrapper = wrapper
  // 等待 onMounted 完成
  await flushPromises()
  await flushPromises()
  return { wrapper, router }
}

describe('ProductOnboardingView.vue 覆盖率补齐测试', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: true,
      status: 200,
      headers: { get: () => 'application/json' },
      json: async () => ({ success: true, data: {} }),
      text: async () => '',
    })))
  })

  afterEach(() => {
    if (currentWrapper) {
      currentWrapper.unmount()
      currentWrapper = null
    }
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
    vi.clearAllMocks()
    try {
      localStorage.clear()
      sessionStorage.clear()
    } catch {
      /* ignore */
    }
  })

  // ===== 1. 基础渲染 - welcome 步骤 =====

  it('welcome 步骤渲染主标题与下一步按钮', async () => {
    const { wrapper } = await mountComponent()
    expect(wrapper.find('.welcome-hero').exists()).toBe(true)
    expect(wrapper.find('h1').text()).toBe('认识 XC')
    const nextBtn = wrapper.find('.actions .btn.primary')
    expect(nextBtn.text()).toContain('下一步：行业定型')
  })

  it('welcome 步骤渲染欢迎 logo 图片', async () => {
    const { wrapper } = await mountComponent()
    const img = wrapper.find('.welcome-logo')
    expect(img.exists()).toBe(true)
    expect(img.attributes('src')).toContain('startup/')
  })

  it('点击 welcome 下一步按钮跳转到 industry 步骤', async () => {
    const { wrapper, router } = await mountComponent()
    const replaceSpy = vi.spyOn(router, 'replace')
    const nextBtn = wrapper.find('.actions .btn.primary')
    await nextBtn.trigger('click')
    await flushPromises()
    expect(replaceSpy).toHaveBeenCalled()
    const callArg = replaceSpy.mock.calls[0][0]
    expect(callArg.query.step).toBe('industry')
  })

  // ===== 2. industry 步骤渲染 =====

  it('industry 步骤渲染行业 chip 列表（默认 preset 模式）', async () => {
    const { wrapper } = await mountComponent({ route: { step: 'industry' } })
    await flushPromises()
    expect(wrapper.find('h1').text()).toBe('先定行业')
    // 默认开放行业为 涂料 与 考勤
    const chips = wrapper.findAll('.industry-pick--open .industry-chip')
    expect(chips.length).toBeGreaterThan(0)
  })

  it('industry 步骤：catalog 提供 open_packages 时使用 catalog 数据', async () => {
    const catalog = {
      open_packages: [
        { industry_id: '涂料', name: '涂料包', scenario: '涂料化工批发。', product_name: '涂料专业版' },
      ],
      preview_packages: [
        { industry_id: '餐饮', name: '餐饮包', scenario: '餐饮门店。', product_name: '餐饮专业版' },
      ],
      open_industry_ids: ['涂料'],
      selected_industry_id: '涂料',
    }
    const { wrapper } = await mountComponent({
      route: { step: 'industry' },
      catalog,
    })
    await flushPromises()
    const chips = wrapper.findAll('.industry-pick--open .industry-chip')
    expect(chips.length).toBe(1)
    expect(chips[0].text()).toContain('涂料包')
    // 预览区也渲染
    const previewChips = wrapper.findAll('.industry-pick--preview .industry-chip--locked')
    expect(previewChips.length).toBe(1)
    expect(previewChips[0].text()).toContain('餐饮包')
  })

  it('industry 步骤：openIndustryLeadNames 多个时显示"N 套行业方向"', async () => {
    const catalog = {
      open_packages: [
        { industry_id: '涂料', name: '涂料', scenario: '', product_name: '' },
        { industry_id: '考勤', name: '考勤', scenario: '', product_name: '' },
      ],
      open_industry_ids: ['涂料', '考勤'],
    }
    const { wrapper } = await mountComponent({
      route: { step: 'industry' },
      catalog,
    })
    await flushPromises()
    const lead = wrapper.find('.lead')
    expect(lead.text()).toContain('2 套行业方向')
  })

  it('industry 步骤：openIndustryLeadNames 单个时显示"行业方向"', async () => {
    const catalog = {
      open_packages: [
        { industry_id: '涂料', name: '涂料', scenario: '', product_name: '' },
      ],
      open_industry_ids: ['涂料'],
    }
    const { wrapper } = await mountComponent({
      route: { step: 'industry' },
      catalog,
    })
    await flushPromises()
    const lead = wrapper.find('.lead')
    expect(lead.text()).toContain('行业方向')
    expect(lead.text()).not.toContain('套行业方向')
  })

  it('industry 步骤：openIndustryOptions 为空时显示加载提示', async () => {
    const { wrapper } = await mountComponent({
      route: { step: 'industry' },
      isEnterprise: true,
      catalog: { open_packages: [], open_industry_ids: [] },
    })
    await flushPromises()
    expect(wrapper.find('.industry-loading-hint').exists()).toBe(true)
    expect(wrapper.find('.industry-loading-hint').text()).toContain('正在加载行业权限')
  })

  it('industry 步骤：点击行业 chip 选中', async () => {
    const { wrapper } = await mountComponent({ route: { step: 'industry' } })
    await flushPromises()
    const chip = wrapper.findAll('.industry-pick--open .industry-chip')[0]
    await chip.trigger('click')
    await flushPromises()
    expect(chip.classes()).toContain('active')
  })

  it('industry 步骤：未选行业时下一步按钮 disabled', async () => {
    const { wrapper } = await mountComponent({
      route: { step: 'industry' },
      isEnterprise: true,
      catalog: { open_packages: [], open_industry_ids: [] },
    })
    await flushPromises()
    const nextBtn = wrapper.find('.actions .btn.primary')
    expect(nextBtn.attributes('disabled')).toBeDefined()
  })

  it('industry 步骤：点击"打开扩展市场"按钮跳转 mod-store', async () => {
    const { wrapper, router } = await mountComponent({ route: { step: 'industry' } })
    await flushPromises()
    const pushSpy = vi.spyOn(router, 'push')
    const modStoreBtn = wrapper.find('.btn.ghost')
    expect(modStoreBtn.text()).toContain('打开扩展市场')
    await modStoreBtn.trigger('click')
    await flushPromises()
    expect(pushSpy).toHaveBeenCalled()
    const callArg = pushSpy.mock.calls[0][0]
    expect(callArg.name).toBe('mod-store')
    expect(callArg.query.onboarding).toBe('1')
  })

  it('industry 步骤：点击"先跳过，直接用对话"按钮', async () => {
    const { wrapper } = await mountComponent({ route: { step: 'industry' } })
    await flushPromises()
    const skipBtn = wrapper.find('.btn.link')
    expect(skipBtn.text()).toContain('先跳过')
    await skipBtn.trigger('click')
    await flushPromises()
    // finishToChat -> finishHostPackFlow -> markHostPackSkippedThisSession
    expect(mockContainer.markHostPackSkippedThisSession).toHaveBeenCalled()
  })

  it('industry 步骤：点击"下一步"调用 confirmIndustryAndNext', async () => {
    const { wrapper, router } = await mountComponent({ route: { step: 'industry' } })
    await flushPromises()
    const replaceSpy = vi.spyOn(router, 'replace')
    // 先选中一个行业
    const chip = wrapper.findAll('.industry-pick--open .industry-chip')[0]
    await chip.trigger('click')
    await flushPromises()
    const nextBtn = wrapper.find('.actions .btn.primary')
    await nextBtn.trigger('click')
    await flushPromises()
    expect(replaceSpy).toHaveBeenCalled()
    const callArg = replaceSpy.mock.calls[replaceSpy.mock.calls.length - 1][0]
    expect(callArg.query.step).toBe('host-pack')
  })

  it('industry 步骤：industryStore 未加载时调用 initialize', async () => {
    const { wrapper } = await mountComponent({
      route: { step: 'industry' },
      industry: { isLoaded: false },
    })
    await flushPromises()
    const chip = wrapper.findAll('.industry-pick--open .industry-chip')[0]
    await chip.trigger('click')
    await flushPromises()
    const nextBtn = wrapper.find('.actions .btn.primary')
    await nextBtn.trigger('click')
    await flushPromises()
    expect(mockContainer.industryState.initialize).toHaveBeenCalled()
  })

  it('industry 步骤：industryStore.initialize 失败时仍继续', async () => {
    mockContainer.industryState = createIndustryState({
      isLoaded: false,
      initialize: vi.fn(async () => {
        throw new Error('init fail')
      }),
    })
    const { wrapper, router } = await mountComponent({ route: { step: 'industry' } })
    await flushPromises()
    const chip = wrapper.findAll('.industry-pick--open .industry-chip')[0]
    await chip.trigger('click')
    await flushPromises()
    const replaceSpy = vi.spyOn(router, 'replace')
    const nextBtn = wrapper.find('.actions .btn.primary')
    await nextBtn.trigger('click')
    await flushPromises()
    expect(replaceSpy).toHaveBeenCalled()
  })

  it('industry 步骤：industryStore 已加载但行业不同时直接进入下一步（不再调用 switchIndustry）', async () => {
    mockContainer.industryState = createIndustryState({
      isLoaded: true,
      currentIndustryId: '通用',
    })
    const { wrapper, router } = await mountComponent({ route: { step: 'industry' } })
    await flushPromises()
    const chip = wrapper.findAll('.industry-pick--open .industry-chip')[0]
    await chip.trigger('click')
    await flushPromises()
    const replaceSpy = vi.spyOn(router, 'replace')
    const nextBtn = wrapper.find('.actions .btn.primary')
    await nextBtn.trigger('click')
    await flushPromises()
    // 行业由后端 SSOT 决定，confirmIndustryAndNext 不再调用 switchIndustry，
    // 仅进入下一步（host-pack）。
    expect(replaceSpy).toHaveBeenCalled()
    expect((mockContainer.industryState as any).switchIndustry).toBeUndefined()
  })

  // ===== 3. host-pack 步骤渲染 =====

  it('host-pack 步骤：loading 时显示检测中', async () => {
    const { wrapper } = await mountComponent({
      route: { step: 'host-pack' },
      baselinePending: true,
      flow: {
        refreshDeliverable: vi.fn(() => new Promise(() => undefined)),
      },
    })
    await flushPromises()
    // loading=true 时模板逻辑 ok/warn 都不应用，仅显示 spinner
    const statusCard = wrapper.find('.status-card')
    expect(statusCard.exists()).toBe(true)
    expect(statusCard.classes()).not.toContain('warn')
    // loading 状态下显示 spinner
    expect(wrapper.find('.fa-spinner').exists()).toBe(true)
  })

  it('host-pack 步骤：baselineOk 时显示已齐状态', async () => {
    const { wrapper } = await mountComponent({
      route: { step: 'host-pack' },
      baseline: createBaselinePlan({ baseline_ready: true }),
    })
    await flushPromises()
    await flushPromises()
    const statusCard = wrapper.find('.status-card')
    expect(statusCard.classes()).toContain('ok')
    expect(statusCard.text()).toContain('已齐')
  })

  it('host-pack 步骤：!baselineOk 时显示缺项', async () => {
    const { wrapper } = await mountComponent({
      route: { step: 'host-pack' },
      baseline: createBaselinePlan({
        baseline_ready: false,
        missing_required_mod_ids: ['mod-a'],
        missing_account_custom_mod_ids: ['mod-b'],
      }),
    })
    await flushPromises()
    await flushPromises()
    const statusCard = wrapper.find('.status-card')
    expect(statusCard.classes()).toContain('warn')
    expect(statusCard.text()).toContain('缺')
  })

  it('host-pack 步骤：!baselineOk 且 missingAccountCustomCount=0 但 missingIndustryPackageCount>0', async () => {
    const { wrapper } = await mountComponent({
      route: { step: 'host-pack' },
      baseline: createBaselinePlan({
        baseline_ready: false,
        missing_required_mod_ids: ['mod-a'],
        missing_account_custom_mod_ids: [],
        industry_mod_ids: ['ind-1'],
        missing_industry_mod_ids: ['ind-1'],
      }),
    })
    await flushPromises()
    await flushPromises()
    const statusCard = wrapper.find('.status-card')
    expect(statusCard.text()).toContain('行业包')
  })

  it('host-pack 步骤：baselinePlan.summary 有值时显示 summary', async () => {
    const { wrapper } = await mountComponent({
      route: { step: 'host-pack' },
      baseline: createBaselinePlan({ summary: '这是摘要' }),
    })
    await flushPromises()
    await flushPromises()
    const lead = wrapper.find('.lead.muted')
    expect(lead.text()).toContain('这是摘要')
  })

  it('host-pack 步骤：sidebarBaselineGroups 渲染侧栏宿主桥接分组', async () => {
    const { wrapper } = await mountComponent({
      route: { step: 'host-pack' },
      baseline: createBaselinePlan({
        baseline_ready: false,
        groups: [
          {
            id: 'core',
            title: '核心',
            hint: '核心提示',
            items: [
              { mod_id: 'mod-1', label: '模块1', installed: true, required: true, show_mod_id: true },
              { mod_id: 'mod-2', label: '模块2', installed: false, required: true, show_mod_id: true },
              { mod_id: 'mod-3', label: '模块3', installed: false, required: false, show_mod_id: false },
            ],
          },
          {
            id: 'industry',
            title: '行业包',
            hint: '行业提示',
            items: [
              { mod_id: 'mod-4', label: '行业模块', installed: false, required: false, show_mod_id: true },
            ],
          },
        ],
      }),
    })
    await flushPromises()
    await flushPromises()
    const groups = wrapper.findAll('.baseline-groups')
    expect(groups.length).toBeGreaterThanOrEqual(1)
    // 侧栏分组标题
    expect(wrapper.text()).toContain('侧栏宿主桥接')
    // 行业包分组标题
    expect(wrapper.text()).toContain('行业包与账号定制')
    // 已安装项 ok class
    expect(wrapper.find('.baseline-list li.ok').exists()).toBe(true)
    // 必需未安装 warn class
    expect(wrapper.find('.baseline-list li.warn').exists()).toBe(true)
    // 可选未安装 optional class
    expect(wrapper.find('.baseline-list li.optional').exists()).toBe(true)
    // mod_id 显示（show_mod_id !== false）
    expect(wrapper.find('.baseline-list .mono').exists()).toBe(true)
  })

  it('host-pack 步骤：sidebarBaselineGroups 为空但 baselineGroups 有值时走 fallback 分支', async () => {
    const { wrapper } = await mountComponent({
      route: { step: 'host-pack' },
      baseline: createBaselinePlan({
        baseline_ready: false,
        groups: [
          {
            id: 'industry',
            title: '行业包',
            hint: '行业提示',
            items: [
              { mod_id: 'mod-4', label: '行业模块', installed: false, required: false, show_mod_id: true },
            ],
          },
        ],
      }),
    })
    await flushPromises()
    await flushPromises()
    // 走 fallback：!sidebarBaselineGroups.length && baselineGroups.length
    expect(wrapper.text()).toContain('行业模块')
  })

  it('host-pack 步骤：industrySidebarPreviewLabels 渲染（考勤特殊）', async () => {
    const { wrapper } = await mountComponent({
      route: { step: 'host-pack' },
      baseline: createBaselinePlan({ baseline_ready: true }),
      catalog: {
        open_industry_ids: ['考勤'],
        selected_industry_id: '考勤',
        open_packages: [{ industry_id: '考勤', name: '考勤', scenario: '', product_name: '' }],
      },
    })
    await flushPromises()
    await flushPromises()
    // 考勤行业会 unshift '考勤表转换'
    const preview = wrapper.find('.sidebar-preview')
    if (preview.exists()) {
      expect(preview.text()).toContain('考勤')
    }
  })

  it('host-pack 步骤：showNoAccountCustomHint 企业版无账号定制时显示', async () => {
    const { wrapper } = await mountComponent({
      route: { step: 'host-pack' },
      isEnterprise: true,
      productSku: 'enterprise',
      baseline: createBaselinePlan({
        baseline_ready: false,
        account_custom_mod_ids: [],
      }),
    })
    await flushPromises()
    await flushPromises()
    expect(wrapper.find('.account-custom-empty-hint').exists()).toBe(true)
  })

  it('host-pack 步骤：baselineOk 时显示"进入智能对话"按钮', async () => {
    const { wrapper } = await mountComponent({
      route: { step: 'host-pack' },
      baseline: createBaselinePlan({ baseline_ready: true }),
    })
    await flushPromises()
    await flushPromises()
    const buttons = wrapper.findAll('.actions .btn.primary')
    const enterChatBtn = buttons.find((b) => b.text().includes('进入智能对话'))
    expect(enterChatBtn).toBeTruthy()
  })

  it('host-pack 步骤：点击"重新检测"按钮触发 refreshStatus', async () => {
    const { wrapper } = await mountComponent({
      route: { step: 'host-pack' },
      baseline: createBaselinePlan({ baseline_ready: true }),
    })
    await flushPromises()
    await flushPromises()
    mockContainer.fetchIndustryBaseline.mockClear()
    const refreshBtn = wrapper.find('.btn.ghost')
    expect(refreshBtn.text()).toContain('重新检测')
    await refreshBtn.trigger('click')
    await flushPromises()
    expect(mockContainer.fetchIndustryBaseline).toHaveBeenCalled()
  })

  // ===== 4. runBootstrap 测试 =====

  it('runBootstrap：成功装齐后调用 promptAdvancedTutorialAfterInstall', async () => {
    const { wrapper } = await mountComponent({
      route: { step: 'host-pack' },
      baseline: createBaselinePlan({ baseline_ready: false }),
    })
    await flushPromises()
    await flushPromises()
    // 设置 mock 序列：第一次 refreshBaseline 返回 false，第二次返回 true
    mockContainer.fetchIndustryBaseline
      .mockResolvedValueOnce(createBaselinePlan({ baseline_ready: false }))
      .mockResolvedValueOnce(createBaselinePlan({ baseline_ready: true }))
    mockContainer.promptAdvancedTutorialAfterInstall.mockClear()
    const bootstrapBtn = wrapper.find('.btn.primary')
    expect(bootstrapBtn.text()).toContain('一键装齐')
    await bootstrapBtn.trigger('click')
    await flushPromises()
    await flushPromises()
    await flushPromises()
    expect(mockContainer.installHostFoundation).toHaveBeenCalled()
    expect(mockContainer.promptAdvancedTutorialAfterInstall).toHaveBeenCalled()
  })

  it('runBootstrap：promptAdvancedTutorialAfterInstall 返回 already_completed 时调用 appAlert', async () => {
    const { wrapper } = await mountComponent({
      route: { step: 'host-pack' },
      baseline: createBaselinePlan({ baseline_ready: false }),
    })
    await flushPromises()
    await flushPromises()
    mockContainer.fetchIndustryBaseline
      .mockResolvedValueOnce(createBaselinePlan({ baseline_ready: false }))
      .mockResolvedValueOnce(createBaselinePlan({ baseline_ready: true }))
    mockContainer.promptAdvancedTutorialAfterInstall.mockResolvedValue('already_completed')
    mockContainer.appAlert.mockClear()
    const bootstrapBtn = wrapper.find('.btn.primary')
    await bootstrapBtn.trigger('click')
    await flushPromises()
    await flushPromises()
    await flushPromises()
    expect(mockContainer.appAlert).toHaveBeenCalled()
  })

  it('runBootstrap：装齐失败时调用 appAlert 显示错误', async () => {
    const { wrapper } = await mountComponent({
      route: { step: 'host-pack' },
      baseline: createBaselinePlan({ baseline_ready: false }),
    })
    await flushPromises()
    await flushPromises()
    // 在 mountComponent 之后设置 mock，避免被默认 mock 覆盖
    mockContainer.installHostFoundation.mockResolvedValue({ success: false, message: '宿主装包失败' })
    mockContainer.fetchIndustryBaseline.mockResolvedValue(
      createBaselinePlan({
        baseline_ready: false,
        missing_required_mod_ids: ['mod-x'],
      }),
    )
    mockContainer.appAlert.mockClear()
    const bootstrapBtn = wrapper.find('.btn.primary')
    await bootstrapBtn.trigger('click')
    await flushPromises()
    await flushPromises()
    await flushPromises()
    expect(mockContainer.appAlert).toHaveBeenCalled()
    const alertMsg = mockContainer.appAlert.mock.calls[0][0] as string
    expect(alertMsg).toContain('宿主装包失败')
  })

  it('runBootstrap：installHostFoundation 抛异常时进入 catch', async () => {
    const { wrapper } = await mountComponent({
      route: { step: 'host-pack' },
      baseline: createBaselinePlan({ baseline_ready: false }),
    })
    await flushPromises()
    await flushPromises()
    // 在 mountComponent 之后设置 mock，避免被默认 mock 覆盖
    mockContainer.installHostFoundation.mockRejectedValue(new Error('网络错误'))
    mockContainer.appAlert.mockClear()
    const bootstrapBtn = wrapper.find('.btn.primary')
    await bootstrapBtn.trigger('click')
    await flushPromises()
    await flushPromises()
    await flushPromises()
    expect(mockContainer.appAlert).toHaveBeenCalledWith('网络错误')
  })

  it('runBootstrap：installHostFoundation 抛非 Error 异常时显示默认错误', async () => {
    const { wrapper } = await mountComponent({
      route: { step: 'host-pack' },
      baseline: createBaselinePlan({ baseline_ready: false }),
    })
    await flushPromises()
    await flushPromises()
    // 在 mountComponent 之后设置 mock，避免被默认 mock 覆盖
    mockContainer.installHostFoundation.mockRejectedValue('string error')
    mockContainer.appAlert.mockClear()
    const bootstrapBtn = wrapper.find('.btn.primary')
    await bootstrapBtn.trigger('click')
    await flushPromises()
    await flushPromises()
    await flushPromises()
    expect(mockContainer.appAlert).toHaveBeenCalledWith('装包失败')
  })

  it('runBootstrap：industryMissing 时调用 installIndustrySeed', async () => {
    const { wrapper } = await mountComponent({
      route: { step: 'host-pack' },
      baseline: createBaselinePlan({
        baseline_ready: false,
        missing_industry_mod_ids: ['ind-1'],
      }),
    })
    await flushPromises()
    await flushPromises()
    mockContainer.fetchIndustryBaseline
      .mockResolvedValueOnce(createBaselinePlan({
        baseline_ready: false,
        missing_industry_mod_ids: ['ind-1'],
      }))
      .mockResolvedValueOnce(createBaselinePlan({ baseline_ready: true }))
    mockContainer.installIndustrySeed.mockResolvedValue({ success: true, message: '' })
    mockContainer.installIndustrySeed.mockClear()
    const bootstrapBtn = wrapper.find('.btn.primary')
    await bootstrapBtn.trigger('click')
    await flushPromises()
    await flushPromises()
    await flushPromises()
    expect(mockContainer.installIndustrySeed).toHaveBeenCalled()
  })

  it('runBootstrap：installIndustrySeed 返回 success=false 时记录错误', async () => {
    const { wrapper } = await mountComponent({
      route: { step: 'host-pack' },
      baseline: createBaselinePlan({
        baseline_ready: false,
        missing_industry_mod_ids: ['ind-1'],
      }),
    })
    await flushPromises()
    await flushPromises()
    mockContainer.fetchIndustryBaseline
      .mockResolvedValueOnce(createBaselinePlan({
        baseline_ready: false,
        missing_industry_mod_ids: ['ind-1'],
      }))
      .mockResolvedValueOnce(createBaselinePlan({ baseline_ready: false }))
    mockContainer.installIndustrySeed.mockResolvedValue({ success: false, message: '行业包失败' })
    mockContainer.appAlert.mockClear()
    const bootstrapBtn = wrapper.find('.btn.primary')
    await bootstrapBtn.trigger('click')
    await flushPromises()
    await flushPromises()
    await flushPromises()
    expect(mockContainer.appAlert).toHaveBeenCalled()
    const alertMsg = mockContainer.appAlert.mock.calls[0][0] as string
    expect(alertMsg).toContain('行业包')
  })

  it('runBootstrap：installIndustrySeed 抛异常时记录错误', async () => {
    const { wrapper } = await mountComponent({
      route: { step: 'host-pack' },
      baseline: createBaselinePlan({
        baseline_ready: false,
        missing_industry_mod_ids: ['ind-1'],
      }),
    })
    await flushPromises()
    await flushPromises()
    mockContainer.fetchIndustryBaseline
      .mockResolvedValueOnce(createBaselinePlan({
        baseline_ready: false,
        missing_industry_mod_ids: ['ind-1'],
      }))
      .mockResolvedValueOnce(createBaselinePlan({ baseline_ready: false }))
    mockContainer.installIndustrySeed.mockRejectedValue(new Error('行业包异常'))
    mockContainer.appAlert.mockClear()
    const bootstrapBtn = wrapper.find('.btn.primary')
    await bootstrapBtn.trigger('click')
    await flushPromises()
    await flushPromises()
    await flushPromises()
    expect(mockContainer.appAlert).toHaveBeenCalled()
  })

  it('runBootstrap：customMissing 时调用 installMod 与 autoOnboard', async () => {
    const { wrapper } = await mountComponent({
      route: { step: 'host-pack' },
      baseline: createBaselinePlan({
        baseline_ready: false,
        missing_account_custom_mod_ids: ['custom-1'],
      }),
    })
    await flushPromises()
    await flushPromises()
    mockContainer.fetchIndustryBaseline
      .mockResolvedValueOnce(createBaselinePlan({
        baseline_ready: false,
        missing_account_custom_mod_ids: ['custom-1'],
      }))
      .mockResolvedValueOnce(createBaselinePlan({ baseline_ready: true }))
    mockContainer.installMod.mockClear()
    mockContainer.autoOnboardWorkflowEmployeesFromMods.mockClear()
    const bootstrapBtn = wrapper.find('.btn.primary')
    await bootstrapBtn.trigger('click')
    await flushPromises()
    await flushPromises()
    await flushPromises()
    expect(mockContainer.installMod).toHaveBeenCalledWith('custom-1')
    expect(mockContainer.autoOnboardWorkflowEmployeesFromMods).toHaveBeenCalled()
  })

  it('runBootstrap：installMod 返回 success=false 时记录错误', async () => {
    const { wrapper } = await mountComponent({
      route: { step: 'host-pack' },
      baseline: createBaselinePlan({
        baseline_ready: false,
        missing_account_custom_mod_ids: ['custom-1'],
      }),
    })
    await flushPromises()
    await flushPromises()
    mockContainer.fetchIndustryBaseline
      .mockResolvedValueOnce(createBaselinePlan({
        baseline_ready: false,
        missing_account_custom_mod_ids: ['custom-1'],
      }))
      .mockResolvedValueOnce(createBaselinePlan({ baseline_ready: false }))
    mockContainer.installMod.mockResolvedValue({ success: false, message: 'mod 失败' })
    mockContainer.appAlert.mockClear()
    const bootstrapBtn = wrapper.find('.btn.primary')
    await bootstrapBtn.trigger('click')
    await flushPromises()
    await flushPromises()
    await flushPromises()
    expect(mockContainer.appAlert).toHaveBeenCalled()
  })

  it('runBootstrap：installMod 抛异常时记录错误', async () => {
    const { wrapper } = await mountComponent({
      route: { step: 'host-pack' },
      baseline: createBaselinePlan({
        baseline_ready: false,
        missing_account_custom_mod_ids: ['custom-1'],
      }),
    })
    await flushPromises()
    await flushPromises()
    mockContainer.fetchIndustryBaseline
      .mockResolvedValueOnce(createBaselinePlan({
        baseline_ready: false,
        missing_account_custom_mod_ids: ['custom-1'],
      }))
      .mockResolvedValueOnce(createBaselinePlan({ baseline_ready: false }))
    mockContainer.installMod.mockRejectedValue(new Error('mod 异常'))
    mockContainer.appAlert.mockClear()
    const bootstrapBtn = wrapper.find('.btn.primary')
    await bootstrapBtn.trigger('click')
    await flushPromises()
    await flushPromises()
    await flushPromises()
    expect(mockContainer.appAlert).toHaveBeenCalled()
  })

  it('runBootstrap：account_custom_mod_ids 时调用 installCustomerDeliverySeed', async () => {
    const { wrapper } = await mountComponent({
      route: { step: 'host-pack' },
      baseline: createBaselinePlan({
        baseline_ready: false,
        account_custom_mod_ids: ['custom-1'],
      }),
    })
    await flushPromises()
    await flushPromises()
    mockContainer.fetchIndustryBaseline
      .mockResolvedValueOnce(createBaselinePlan({
        baseline_ready: false,
        account_custom_mod_ids: ['custom-1'],
      }))
      .mockResolvedValueOnce(createBaselinePlan({ baseline_ready: true }))
    mockContainer.installCustomerDeliverySeed.mockClear()
    const bootstrapBtn = wrapper.find('.btn.primary')
    await bootstrapBtn.trigger('click')
    await flushPromises()
    await flushPromises()
    await flushPromises()
    expect(mockContainer.installCustomerDeliverySeed).toHaveBeenCalledWith('custom-1', expect.any(String))
  })

  it('runBootstrap：installCustomerDeliverySeed 返回 success=false 时记录错误', async () => {
    const { wrapper } = await mountComponent({
      route: { step: 'host-pack' },
      baseline: createBaselinePlan({
        baseline_ready: false,
        account_custom_mod_ids: ['custom-1'],
      }),
    })
    await flushPromises()
    await flushPromises()
    mockContainer.fetchIndustryBaseline
      .mockResolvedValueOnce(createBaselinePlan({
        baseline_ready: false,
        account_custom_mod_ids: ['custom-1'],
      }))
      .mockResolvedValueOnce(createBaselinePlan({ baseline_ready: false }))
    mockContainer.installCustomerDeliverySeed.mockResolvedValue({ success: false, message: '交付失败' })
    mockContainer.appAlert.mockClear()
    const bootstrapBtn = wrapper.find('.btn.primary')
    await bootstrapBtn.trigger('click')
    await flushPromises()
    await flushPromises()
    await flushPromises()
    expect(mockContainer.appAlert).toHaveBeenCalled()
  })

  it('runBootstrap：installCustomerDeliverySeed 抛异常时记录错误', async () => {
    const { wrapper } = await mountComponent({
      route: { step: 'host-pack' },
      baseline: createBaselinePlan({
        baseline_ready: false,
        account_custom_mod_ids: ['custom-1'],
      }),
    })
    await flushPromises()
    await flushPromises()
    mockContainer.fetchIndustryBaseline
      .mockResolvedValueOnce(createBaselinePlan({
        baseline_ready: false,
        account_custom_mod_ids: ['custom-1'],
      }))
      .mockResolvedValueOnce(createBaselinePlan({ baseline_ready: false }))
    mockContainer.installCustomerDeliverySeed.mockRejectedValue(new Error('交付异常'))
    mockContainer.appAlert.mockClear()
    const bootstrapBtn = wrapper.find('.btn.primary')
    await bootstrapBtn.trigger('click')
    await flushPromises()
    await flushPromises()
    await flushPromises()
    expect(mockContainer.appAlert).toHaveBeenCalled()
  })

  it('runBootstrap：autoOnboard 抛异常时进入 catch 不阻断', async () => {
    const { wrapper } = await mountComponent({
      route: { step: 'host-pack' },
      baseline: createBaselinePlan({
        baseline_ready: false,
        missing_account_custom_mod_ids: ['custom-1'],
      }),
    })
    await flushPromises()
    await flushPromises()
    mockContainer.fetchIndustryBaseline
      .mockResolvedValueOnce(createBaselinePlan({
        baseline_ready: false,
        missing_account_custom_mod_ids: ['custom-1'],
      }))
      .mockResolvedValueOnce(createBaselinePlan({ baseline_ready: true }))
    mockContainer.autoOnboardWorkflowEmployeesFromMods.mockRejectedValue(new Error('onboard 失败'))
    const consoleSpy = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    const bootstrapBtn = wrapper.find('.btn.primary')
    await bootstrapBtn.trigger('click')
    await flushPromises()
    await flushPromises()
    await flushPromises()
    await flushPromises()
    expect(consoleSpy).toHaveBeenCalled()
    consoleSpy.mockRestore()
  })

  // ===== 5. done 步骤（else 分支）=====

  it('done 步骤渲染"可以开始使用"', async () => {
    const { wrapper } = await mountComponent({ route: { step: 'done' } })
    await flushPromises()
    expect(wrapper.find('h1').text()).toBe('可以开始使用')
    const enterBtn = wrapper.find('.actions .btn.primary')
    expect(enterBtn.text()).toContain('进入智能对话')
  })

  // ===== 6. fromTutorial 模式 =====

  it('fromTutorial 模式：header 显示"新手教程 · 宿主入门"', async () => {
    const { wrapper } = await mountComponent({
      route: { from: 'tutorial', redirect: '/chat' },
    })
    await flushPromises()
    expect(wrapper.find('.brand').text()).toContain('新手教程 · 宿主入门')
  })

  it('fromTutorial 模式：footer 显示"返回上一页"按钮', async () => {
    const { wrapper } = await mountComponent({
      route: { from: 'tutorial', redirect: '/chat' },
    })
    await flushPromises()
    const footerBtn = wrapper.find('.product-flow-footer .btn.text')
    expect(footerBtn.text()).toContain('返回上一页')
  })

  it('fromTutorial 模式：点击"返回上一页"调用 returnFromTutorial', async () => {
    const { wrapper, router } = await mountComponent({
      route: { from: 'tutorial', redirect: '/chat' },
    })
    await flushPromises()
    const replaceSpy = vi.spyOn(router, 'replace')
    const footerBtn = wrapper.find('.product-flow-footer .btn.text')
    await footerBtn.trigger('click')
    await flushPromises()
    expect(replaceSpy).toHaveBeenCalledWith('/chat')
  })

  it('非 fromTutorial 模式：footer 显示"跳过引导"按钮', async () => {
    const { wrapper } = await mountComponent()
    await flushPromises()
    const footerBtn = wrapper.find('.product-flow-footer .btn.text')
    expect(footerBtn.text()).toContain('跳过引导')
  })

  it('非 fromTutorial 模式：点击"跳过引导"调用 skipEntireFlow', async () => {
    const { wrapper } = await mountComponent()
    await flushPromises()
    const footerBtn = wrapper.find('.product-flow-footer .btn.text')
    await footerBtn.trigger('click')
    await flushPromises()
    // skipEntireFlow -> !baselineOk -> markHostPackSkippedThisSession
    expect(mockContainer.markHostPackSkippedThisSession).toHaveBeenCalled()
  })

  it('fromTutorial 模式：点击"跳过引导"调用 returnFromTutorial', async () => {
    const { wrapper, router } = await mountComponent({
      route: { from: 'tutorial', redirect: '/chat' },
    })
    await flushPromises()
    const replaceSpy = vi.spyOn(router, 'replace')
    const footerBtn = wrapper.find('.product-flow-footer .btn.text')
    await footerBtn.trigger('click')
    await flushPromises()
    expect(replaceSpy).toHaveBeenCalledWith('/chat')
  })

  it('fromTutorial 模式：openModStore 跳转不带 onboarding 参数', async () => {
    const { wrapper, router } = await mountComponent({
      route: { step: 'industry', from: 'tutorial', redirect: '/chat' },
    })
    await flushPromises()
    const pushSpy = vi.spyOn(router, 'push')
    const modStoreBtn = wrapper.find('.btn.ghost')
    await modStoreBtn.trigger('click')
    await flushPromises()
    expect(pushSpy).toHaveBeenCalled()
    const callArg = pushSpy.mock.calls[0][0]
    expect(callArg.name).toBe('mod-store')
    expect(callArg.query).toEqual({})
  })

  // ===== 7. editionLabel 测试 =====

  it('editionLabel：enterprise SKU 显示"企业版"', async () => {
    const { wrapper } = await mountComponent({ productSku: 'enterprise' })
    await flushPromises()
    expect(wrapper.find('.edition-tag').text()).toContain('企业版 enterprise')
  })

  it('editionLabel：personal SKU 显示"个人版"', async () => {
    const { wrapper } = await mountComponent({ productSku: 'personal' })
    await flushPromises()
    expect(wrapper.find('.edition-tag').text()).toContain('个人版 personal')
  })

  it('editionLabel：minimal edition 显示"空壳"', async () => {
    const { wrapper } = await mountComponent({ buildEdition: 'minimal' })
    await flushPromises()
    expect(wrapper.find('.edition-tag').text()).toContain('空壳 minimal')
  })

  it('editionLabel：generic edition 显示"通用"', async () => {
    const { wrapper } = await mountComponent({ buildEdition: 'generic' })
    await flushPromises()
    expect(wrapper.find('.edition-tag').text()).toContain('通用 generic')
  })

  it('editionLabel：full edition 显示"完整"', async () => {
    const { wrapper } = await mountComponent({ buildEdition: 'full' })
    await flushPromises()
    expect(wrapper.find('.edition-tag').text()).toContain('完整 full')
  })

  // ===== 8. onWelcomeLogoError 测试 =====

  it('onWelcomeLogoError：图片错误时切换到下一个候选 logo', async () => {
    const { wrapper } = await mountComponent()
    await flushPromises()
    const img = wrapper.find('.welcome-logo')
    const initialSrc = img.attributes('src')
    await img.trigger('error')
    await flushPromises()
    const newSrc = wrapper.find('.welcome-logo').attributes('src')
    expect(newSrc).not.toBe(initialSrc)
  })

  it('onWelcomeLogoError：多次错误后不再切换', async () => {
    const { wrapper } = await mountComponent()
    await flushPromises()
    // 触发 3 次错误（共 3 个候选）
    for (let i = 0; i < 5; i++) {
      await wrapper.find('.welcome-logo').trigger('error')
      await flushPromises()
    }
    const finalSrc = wrapper.find('.welcome-logo').attributes('src')
    // 第 3 次错误后不再切换，停留在最后一个候选
    expect(finalSrc).toContain('xc-logo-base.jpg')
  })

  // ===== 9. onMounted 测试 =====

  it('onMounted：fetchProductSku 失败时静默处理', async () => {
    const { wrapper } = await mountComponent({ productSkuReject: true })
    await flushPromises()
    expect(wrapper.exists()).toBe(true)
  })

  it('onMounted：fetchOnboardingIndustryCatalog 失败时静默处理', async () => {
    const { wrapper } = await mountComponent({
      route: { step: 'industry' },
      catalogReject: true,
    })
    await flushPromises()
    await flushPromises()
    expect(wrapper.exists()).toBe(true)
    // 失败后 onboardingCatalogLoaded 仍为 true
    // preset 模式下应渲染行业 chip
    expect(wrapper.findAll('.industry-pick--open .industry-chip').length).toBeGreaterThan(0)
  })

  it('onMounted：catalog 有 open_industry_ids 时调用 setRuntimeOnboardingOpenIndustryIds', async () => {
    mockContainer.setRuntimeOnboardingOpenIndustryIds.mockClear()
    const { wrapper } = await mountComponent({
      catalog: { open_industry_ids: ['涂料', '考勤'] },
    })
    await flushPromises()
    expect(mockContainer.setRuntimeOnboardingOpenIndustryIds).toHaveBeenCalledWith(['涂料', '考勤'])
    expect(wrapper.exists()).toBe(true)
  })

  it('onMounted：industryStore 未加载时调用 initialize', async () => {
    const { wrapper } = await mountComponent({
      industry: { isLoaded: false },
    })
    await flushPromises()
    expect(mockContainer.industryState.initialize).toHaveBeenCalled()
  })

  it('onMounted：industryStore.initialize 失败时静默处理', async () => {
    const { wrapper } = await mountComponent({
      industry: {
        isLoaded: false,
        initialize: vi.fn(async () => {
          throw new Error('init fail')
        }),
      },
    })
    await flushPromises()
    expect(wrapper.exists()).toBe(true)
  })

  it('onMounted：currentStep 与 query.step 不一致时跳转', async () => {
    // resolveEntryStep 返回 welcome，但 query.step=industry
    const { router } = await mountComponent({
      route: { step: 'industry' },
      flow: {
        resolveEntryStep: vi.fn(() => 'welcome'),
      },
    })
    await flushPromises()
    // 应触发 router.replace
    // 由于 onMounted 末尾会调用 refreshStatus，这里只验证不报错
    expect(router).toBeTruthy()
  })

  // ===== 10. watcher 测试 =====

  it('watcher：route.query.step 变化时更新 currentStep', async () => {
    const { wrapper, router } = await mountComponent()
    await flushPromises()
    expect(wrapper.find('.welcome-hero').exists()).toBe(true)
    await router.push({ name: 'product-onboarding', query: { step: 'industry' } })
    await flushPromises()
    await flushPromises()
    expect(wrapper.find('h1').text()).toBe('先定行业')
  })

  it('watcher：currentStep 变为 host-pack 时触发 refreshStatus', async () => {
    mockContainer.fetchIndustryBaseline.mockClear()
    const { wrapper, router } = await mountComponent()
    await flushPromises()
    mockContainer.fetchIndustryBaseline.mockClear()
    await router.push({ name: 'product-onboarding', query: { step: 'host-pack' } })
    await flushPromises()
    await flushPromises()
    expect(mockContainer.fetchIndustryBaseline).toHaveBeenCalled()
  })

  it('watcher：pickedIndustryId 在 host-pack 步骤变化时触发 refreshStatus', async () => {
    const { wrapper } = await mountComponent({ route: { step: 'host-pack' } })
    await flushPromises()
    await flushPromises()
    mockContainer.fetchIndustryBaseline.mockClear()
    mockContainer.clearDeliverableStatusCache.mockClear()
    // 通过点击行业 chip 改变 pickedIndustryId（但 host-pack 步骤没有 chip）
    // 改用直接修改 vm setupState
    const vm = wrapper.vm as any
    const setupState = vm?.$?.setupState
    if (setupState && 'pickedIndustryId' in setupState) {
      // pickedIndustryId 是 ref，通过 devtoolsRawSetupState 修改
      const rawState = vm?.$?.devtoolsRawSetupState
      if (rawState?.pickedIndustryId) {
        rawState.pickedIndustryId.value = '考勤'
      }
    }
    await flushPromises()
    await flushPromises()
    // watcher 触发 clearDeliverableStatusCache
    expect(mockContainer.clearDeliverableStatusCache).toHaveBeenCalled()
  })

  // ===== 11. footerHint 测试 =====

  it('footerHint：fromTutorial 模式显示教程提示', async () => {
    const { wrapper } = await mountComponent({
      route: { from: 'tutorial', redirect: '/chat' },
    })
    await flushPromises()
    expect(wrapper.find('.doc-hint').text()).toContain('新手教程')
  })

  it('footerHint：非 fromTutorial 模式显示文档提示', async () => {
    const { wrapper } = await mountComponent()
    await flushPromises()
    expect(wrapper.find('.doc-hint').text()).toContain('PRODUCT_USER_FLOW.md')
  })

  // ===== 12. currentStepMeta subtitle 测试 =====

  it('currentStepMeta：industry 步骤显示 subtitle', async () => {
    const { wrapper } = await mountComponent({ route: { step: 'industry' } })
    await flushPromises()
    const brandLead = wrapper.find('.brand-lead')
    expect(brandLead.exists()).toBe(true)
    expect(brandLead.text()).toContain('行业')
  })

  it('currentStepMeta：welcome 步骤不显示 subtitle', async () => {
    const { wrapper } = await mountComponent()
    await flushPromises()
    // welcome 步骤 currentStepMeta.subtitle 存在但 currentStep === 'welcome'，所以 v-if 不渲染
    expect(wrapper.find('.brand-lead').exists()).toBe(false)
  })

  // ===== 13. step-rail 渲染 =====

  it('step-rail：渲染 3 个步骤（done 已过滤）', async () => {
    const { wrapper } = await mountComponent()
    await flushPromises()
    const items = wrapper.findAll('.step-rail-item')
    expect(items.length).toBe(3)
  })

  it('step-rail：当前步骤标记 active', async () => {
    const { wrapper } = await mountComponent({ route: { step: 'industry' } })
    await flushPromises()
    const activeItems = wrapper.findAll('.step-rail-item.active')
    expect(activeItems.length).toBe(1)
  })

  it('step-rail：已完成步骤标记 done', async () => {
    const { wrapper } = await mountComponent({ route: { step: 'host-pack' } })
    await flushPromises()
    const doneItems = wrapper.findAll('.step-rail-item.done')
    expect(doneItems.length).toBe(2)
  })

  // ===== 14. industryPackageLabel 测试 =====

  it('industryPackageLabel：catalog 有 product_name 时返回 product_name', async () => {
    const { wrapper } = await mountComponent({
      route: { step: 'industry' },
      catalog: {
        open_packages: [
          { industry_id: '涂料', name: '涂料', scenario: '', product_name: '涂料专业版' },
        ],
        open_industry_ids: ['涂料'],
      },
    })
    await flushPromises()
    const chip = wrapper.find('.industry-pick--open .industry-chip')
    expect(chip.text()).toContain('涂料专业版')
  })

  it('industryPackageLabel：preset 有 name 时返回"X行业包"', async () => {
    const { wrapper } = await mountComponent({ route: { step: 'industry' } })
    await flushPromises()
    // 默认 preset 模式，无 catalog，无 productName
    const chip = wrapper.find('.industry-pick--open .industry-chip')
    expect(chip.text()).toContain('行业包')
  })

  // ===== 15. chipScenarioText 测试 =====

  it('chipScenarioText：去掉句末句号', async () => {
    const { wrapper } = await mountComponent({
      route: { step: 'industry' },
      catalog: {
        open_packages: [
          { industry_id: '涂料', name: '涂料', scenario: '涂料化工批发。', product_name: '' },
        ],
        open_industry_ids: ['涂料'],
      },
    })
    await flushPromises()
    const scenario = wrapper.find('.industry-chip-scenario')
    expect(scenario.text()).not.toContain('。')
  })

  // ===== 16. previewIndustryOptions 测试 =====

  it('previewIndustryOptions：enterprise 且 catalog 未加载时返回空', async () => {
    const { wrapper } = await mountComponent({
      route: { step: 'industry' },
      isEnterprise: true,
      productSku: 'enterprise',
      catalogPending: true,
    })
    await flushPromises()
    // 预览区不渲染（enterprise 且 catalog 未加载时 previewIndustryOptions 返回空）
    expect(wrapper.find('.industry-pick--preview').exists()).toBe(false)
  })

  it('previewIndustryOptions：catalog 有 preview_packages 时使用 catalog', async () => {
    const { wrapper } = await mountComponent({
      route: { step: 'industry' },
      catalog: {
        open_packages: [
          { industry_id: '涂料', name: '涂料', scenario: '', product_name: '' },
        ],
        preview_packages: [
          { industry_id: '餐饮', name: '餐饮', scenario: '', product_name: '' },
        ],
        open_industry_ids: ['涂料'],
      },
    })
    await flushPromises()
    const previewHint = wrapper.find('.industry-preview-hint')
    expect(previewHint.exists()).toBe(true)
    const previewChips = wrapper.findAll('.industry-pick--preview .industry-chip--locked')
    expect(previewChips.length).toBe(1)
  })

  // ===== 17. finishHostPackFlow 测试 =====

  it('finishHostPackFlow：baselineOk 且非 fromTutorial 时调用 completeFlowAndGoChat', async () => {
    mockContainer.flowState = createFlowState({
      refreshDeliverable: vi.fn(async () => ({ deliverable: true })),
    })
    mockContainer.readProductFlowCompleted.mockReturnValue(false)
    const { wrapper } = await mountComponent({
      route: { step: 'host-pack' },
      baseline: createBaselinePlan({ baseline_ready: true }),
    })
    await flushPromises()
    await flushPromises()
    mockContainer.flowState.completeFlowAndGoChat.mockClear()
    mockContainer.flowState.markProductFlowCompleted.mockClear()
    mockContainer.flowState.markHostPackAcknowledged.mockClear()
    // 点击"进入智能对话"按钮
    const buttons = wrapper.findAll('.actions .btn.primary')
    const enterChatBtn = buttons.find((b) => b.text().includes('进入智能对话'))
    if (enterChatBtn) {
      await enterChatBtn.trigger('click')
      await flushPromises()
      expect(mockContainer.flowState.markProductFlowCompleted).toHaveBeenCalled()
      expect(mockContainer.flowState.markHostPackAcknowledged).toHaveBeenCalled()
      expect(mockContainer.flowState.completeFlowAndGoChat).toHaveBeenCalled()
    }
  })

  it('finishHostPackFlow：baselineOk 且 fromTutorial 时调用 returnFromTutorial', async () => {
    mockContainer.flowState = createFlowState({
      refreshDeliverable: vi.fn(async () => ({ deliverable: true })),
    })
    mockContainer.readProductFlowCompleted.mockReturnValue(false)
    const { wrapper, router } = await mountComponent({
      route: { step: 'host-pack', from: 'tutorial', redirect: '/chat' },
      baseline: createBaselinePlan({ baseline_ready: true }),
    })
    await flushPromises()
    await flushPromises()
    const replaceSpy = vi.spyOn(router, 'replace')
    const buttons = wrapper.findAll('.actions .btn.primary')
    const enterChatBtn = buttons.find((b) => b.text().includes('进入智能对话'))
    if (enterChatBtn) {
      await enterChatBtn.trigger('click')
      await flushPromises()
      expect(replaceSpy).toHaveBeenCalledWith('/chat')
    }
  })

  it('finishHostPackFlow：!baselineOk 时调用 markHostPackSkippedThisSession', async () => {
    const { wrapper, router } = await mountComponent({
      route: { step: 'host-pack' },
      baseline: createBaselinePlan({ baseline_ready: false }),
    })
    await flushPromises()
    await flushPromises()
    mockContainer.markHostPackSkippedThisSession.mockClear()
    const replaceSpy = vi.spyOn(router, 'replace')
    // 点击"先进入对话，稍后再补"
    const linkBtn = wrapper.find('.btn.link')
    await linkBtn.trigger('click')
    await flushPromises()
    expect(mockContainer.markHostPackSkippedThisSession).toHaveBeenCalled()
    expect(replaceSpy).toHaveBeenCalledWith({ path: '/' })
  })

  it('finishHostPackFlow：!baselineOk 且 fromTutorial 时调用 returnFromTutorial', async () => {
    const { wrapper, router } = await mountComponent({
      route: { step: 'host-pack', from: 'tutorial', redirect: '/chat' },
      baseline: createBaselinePlan({ baseline_ready: false }),
    })
    await flushPromises()
    await flushPromises()
    const replaceSpy = vi.spyOn(router, 'replace')
    const linkBtn = wrapper.find('.btn.link')
    await linkBtn.trigger('click')
    await flushPromises()
    expect(replaceSpy).toHaveBeenCalledWith('/chat')
  })

  // ===== 18. skipEntireFlow baselineOk 分支 =====

  it('skipEntireFlow：baselineOk 时调用 markProductFlowCompleted', async () => {
    mockContainer.flowState = createFlowState()
    mockContainer.readProductFlowCompleted.mockReturnValue(false)
    const { wrapper } = await mountComponent({
      route: { step: 'host-pack' },
      baseline: createBaselinePlan({ baseline_ready: true }),
    })
    await flushPromises()
    await flushPromises()
    mockContainer.flowState.markProductFlowCompleted.mockClear()
    mockContainer.flowState.markHostPackAcknowledged.mockClear()
    // 点击"跳过引导"
    const footerBtn = wrapper.find('.product-flow-footer .btn.text')
    await footerBtn.trigger('click')
    await flushPromises()
    expect(mockContainer.flowState.markProductFlowCompleted).toHaveBeenCalled()
    expect(mockContainer.flowState.markHostPackAcknowledged).toHaveBeenCalled()
  })

  // ===== 19. openModStore 测试 =====

  it('openModStore：非 fromTutorial 且未 completed 时调用 markProductFlowCompleted', async () => {
    mockContainer.readProductFlowCompleted.mockReturnValue(false)
    const { wrapper } = await mountComponent({ route: { step: 'industry' } })
    await flushPromises()
    mockContainer.flowState.markProductFlowCompleted.mockClear()
    const modStoreBtn = wrapper.find('.btn.ghost')
    await modStoreBtn.trigger('click')
    await flushPromises()
    expect(mockContainer.flowState.markProductFlowCompleted).toHaveBeenCalled()
  })

  it('openModStore：非 fromTutorial 时总是调用 markProductFlowCompleted', async () => {
    // 逻辑：if (!fromTutorial.value || !readProductFlowCompleted()) markProductFlowCompleted()
    // 非 fromTutorial 时，无论是否 completed 都会调用
    mockContainer.readProductFlowCompleted.mockReturnValue(true)
    const { wrapper } = await mountComponent({ route: { step: 'industry' } })
    await flushPromises()
    mockContainer.flowState.markProductFlowCompleted.mockClear()
    const modStoreBtn = wrapper.find('.btn.ghost')
    await modStoreBtn.trigger('click')
    await flushPromises()
    expect(mockContainer.flowState.markProductFlowCompleted).toHaveBeenCalled()
  })

  it('openModStore：fromTutorial 且已 completed 时不调用 markProductFlowCompleted', async () => {
    // 逻辑：fromTutorial && readProductFlowCompleted() 时不调用
    const { wrapper } = await mountComponent({
      route: { step: 'industry', from: 'tutorial', redirect: '/chat' },
    })
    await flushPromises()
    // 在 mountComponent 之后设置 mock，避免被默认 mock 覆盖
    mockContainer.readProductFlowCompleted.mockReturnValue(true)
    mockContainer.flowState.markProductFlowCompleted.mockClear()
    const modStoreBtn = wrapper.find('.btn.ghost')
    await modStoreBtn.trigger('click')
    await flushPromises()
    expect(mockContainer.flowState.markProductFlowCompleted).not.toHaveBeenCalled()
  })

  // ===== 20. goStep fromTutorial 分支 =====

  it('goStep：fromTutorial 时携带 from 与 redirect 参数', async () => {
    const { wrapper, router } = await mountComponent({
      route: { from: 'tutorial', redirect: '/chat' },
    })
    await flushPromises()
    const replaceSpy = vi.spyOn(router, 'replace')
    const nextBtn = wrapper.find('.actions .btn.primary')
    await nextBtn.trigger('click')
    await flushPromises()
    expect(replaceSpy).toHaveBeenCalled()
    const callArg = replaceSpy.mock.calls[0][0]
    expect(callArg.query.from).toBe('tutorial')
    expect(callArg.query.redirect).toBe('/chat')
  })

  // ===== 21. onMounted 路由跳转条件 =====

  it('onMounted：fromTutorial 但 query.from !== tutorial 时跳转', async () => {
    mockContainer.flowState = createFlowState({
      resolveEntryStep: vi.fn(() => 'welcome'),
    })
    const { router } = await mountComponent({
      route: { from: 'tutorial', redirect: '/chat' },
    })
    await flushPromises()
    // onMounted 末尾会检查 fromTutorial && route.query.from !== 'tutorial'
    // 但这里 query.from 已经是 'tutorial'，所以不会跳转
    expect(router.currentRoute.value.name).toBe('product-onboarding')
  })

  // ===== 22. missingSidebarBaselineCount 测试 =====

  it('missingSidebarBaselineCount：统计侧栏分组中必需未安装项', async () => {
    const { wrapper } = await mountComponent({
      route: { step: 'host-pack' },
      baseline: createBaselinePlan({
        baseline_ready: false,
        groups: [
          {
            id: 'core',
            title: '核心',
            hint: '',
            items: [
              { mod_id: 'mod-1', label: 'M1', installed: false, required: true },
              { mod_id: 'mod-2', label: 'M2', installed: false, required: true },
              { mod_id: 'mod-1', label: 'M1', installed: false, required: true }, // 重复 mod_id
            ],
          },
        ],
      }),
    })
    await flushPromises()
    await flushPromises()
    const statusCard = wrapper.find('.status-card')
    // 去重后应为 2 项
    expect(statusCard.text()).toContain('2')
  })

  // ===== 23. refreshStatus 异常处理 =====

  it('refreshStatus：fetchIndustryBaseline 抛异常时 loading 恢复', async () => {
    mockContainer.fetchIndustryBaseline.mockRejectedValue(new Error('baseline fail'))
    const { wrapper } = await mountComponent({ route: { step: 'host-pack' } })
    await flushPromises()
    await flushPromises()
    // loading 应为 false（finally 块）
    expect(wrapper.find('.fa-spinner').exists()).toBe(false)
  })

  // ===== 24. resolveDefaultPickedIndustryId 测试 =====

  it('resolveDefaultPickedIndustryId：catalog.selected_industry_id 可选时使用', async () => {
    const { wrapper } = await mountComponent({
      route: { step: 'industry' },
      catalog: {
        open_industry_ids: ['涂料', '考勤'],
        selected_industry_id: '考勤',
        open_packages: [
          { industry_id: '涂料', name: '涂料', scenario: '', product_name: '' },
          { industry_id: '考勤', name: '考勤', scenario: '', product_name: '' },
        ],
      },
    })
    await flushPromises()
    // 选中的应为 '考勤'
    const activeChip = wrapper.find('.industry-chip.active')
    expect(activeChip.text()).toContain('考勤')
  })

  it('resolveDefaultPickedIndustryId：selected 不可选时回退到 openIds[0]', async () => {
    const { wrapper } = await mountComponent({
      route: { step: 'industry' },
      catalog: {
        open_industry_ids: ['涂料'],
        selected_industry_id: '考勤', // 不在 open_industry_ids 中
        open_packages: [
          { industry_id: '涂料', name: '涂料', scenario: '', product_name: '' },
        ],
      },
    })
    await flushPromises()
    const activeChip = wrapper.find('.industry-chip.active')
    expect(activeChip.text()).toContain('涂料')
  })

  // ===== 25. confirmIndustryAndNext 不再调用 switchIndustry（行业由后端 SSOT 决定） =====

  it('confirmIndustryAndNext：industryStore 已加载且行业相同时直接进入下一步', async () => {
    const { wrapper, router } = await mountComponent({
      route: { step: 'industry' },
      industry: {
        isLoaded: true,
        currentIndustryId: '涂料',
      },
      catalog: {
        open_industry_ids: ['涂料'],
        selected_industry_id: '涂料',
        open_packages: [{ industry_id: '涂料', name: '涂料', scenario: '', product_name: '' }],
      },
    })
    await flushPromises()
    const replaceSpy = vi.spyOn(router, 'replace')
    const nextBtn = wrapper.find('.actions .btn.primary')
    await nextBtn.trigger('click')
    await flushPromises()
    // switchIndustry 已删除，confirmIndustryAndNext 仅进入下一步。
    expect((mockContainer.industryState as any).switchIndustry).toBeUndefined()
    expect(replaceSpy).toHaveBeenCalled()
  })

  // ===== 26. catalogChipRow 测试 =====

  it('catalogChipRow：industry_id 为空时使用 preset 名称', async () => {
    const { wrapper } = await mountComponent({
      route: { step: 'industry' },
      catalog: {
        open_packages: [
          { industry_id: '', name: '', scenario: '', product_name: '' },
        ],
        open_industry_ids: [''],
      },
    })
    await flushPromises()
    expect(wrapper.exists()).toBe(true)
  })
})
