import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, h } from 'vue'
import { validateEnterpriseSessionCached } from '@/utils/authSessionCache'

vi.mock('@/utils/authSessionCache', () => ({ validateEnterpriseSessionCached: vi.fn().mockResolvedValue(true), invalidateEnterpriseSessionCache: vi.fn() }))

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
  updateCompanyBrand: vi.fn(),
  installHostFoundation: vi.fn(),
  installMod: vi.fn(),
  installIndustrySeed: vi.fn(),
  installCustomerDeliverySeed: vi.fn(),
  autoOnboardWorkflowEmployeesFromMods: vi.fn(),
  fetchProductSku: vi.fn(),
  fetchIndustryBaseline: vi.fn(),
  fetchOnboardingIndustryCatalog: vi.fn(),
  seedOnboardingDemo: vi.fn(),
  clearDeliverableStatusCache: vi.fn(),
  appAlert: vi.fn(),
  promptAdvancedTutorialAfterInstall: vi.fn(),
  resolveRouteNameFromPath: vi.fn(),
  invalidateHostPackCompletionCache: vi.fn(),
  markHostPackSkippedThisSession: vi.fn(),
  readBuildEdition: vi.fn(),
  isEnterpriseEdition: vi.fn(),
  patchWorkspacePrefs: vi.fn(),
  queueWorkspacePrefsSync: vi.fn(),
  // productFlow 工具
  setRuntimeOnboardingOpenIndustryIds: vi.fn(),
  readProductFlowCompleted: vi.fn(),
}))

// ===== Mock 模块 =====
vi.mock('@/api/auth', () => ({ authApi: { getSubscriptionStatus: vi.fn().mockResolvedValue({ data: null }), updateCompanyBrand: mockContainer.updateCompanyBrand } }))
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
  seedOnboardingDemo: mockContainer.seedOnboardingDemo,
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

vi.mock('@/utils/workspacePrefsApi', () => ({
  patchWorkspacePrefs: mockContainer.patchWorkspacePrefs,
  queueWorkspacePrefsSync: mockContainer.queueWorkspacePrefsSync,
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
function createTestRouter() {
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
      const s = String(q || '')
        .trim()
        .toLowerCase()
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
    loadFromServer: vi.fn(async () => {
      const patch = mockContainer.patchWorkspacePrefs.mock.calls.at(-1)?.[0]
      if (patch?.selected_industry_id) mockContainer.industryState.currentIndustryId = patch.selected_industry_id
    }),
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
    buildContext: { value: { industryId: '通用', mods: [], visibleNav: [] } },
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

function mockBaselineForInstallation(
  install: typeof mockContainer.installHostFoundation,
  missing = createBaselinePlan(),
) {
  let installed = false
  const runInstall = install.getMockImplementation()
  if (!runInstall) throw new Error('Configure the installation result before its baseline')
  // Reading status never installs anything. Only the corresponding successful
  // installation changes readiness; rejected responses and exceptions keep it missing.
  mockContainer.fetchIndustryBaseline.mockImplementation(async () => (
    installed ? createBaselinePlan({ baseline_ready: true }) : missing
  ))
  install.mockImplementation(async (...args) => {
    const result = await runInstall(...args)
    if (result?.success === true) installed = true
    return result
  })
}

let currentWrapper: ReturnType<typeof mount> | null = null

async function mountComponent(
  options: {
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
  } = {},
) {
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
    vi.mocked(validateEnterpriseSessionCached).mockResolvedValue(true)
    if (options.productSkuReject) {
      mockContainer.fetchProductSku.mockRejectedValue(new Error('sku fail'))
    } else {
      mockContainer.fetchProductSku.mockResolvedValue(options.productSku || 'generic')
    }
    mockContainer.isEnterpriseEdition.mockReturnValue(!!options.isEnterprise)
    mockContainer.readBuildEdition.mockReturnValue(options.buildEdition || 'full')
    if (options.baselinePending) {
      mockContainer.fetchIndustryBaseline.mockImplementation(() => new Promise(() => undefined))
    } else if (options.baselineReject) {
      mockContainer.fetchIndustryBaseline.mockRejectedValue(new Error('baseline fail'))
    } else {
      mockContainer.fetchIndustryBaseline.mockResolvedValue(options.baseline === undefined ? createBaselinePlan() : options.baseline)
    }
    if (options.catalogPending) {
      mockContainer.fetchOnboardingIndustryCatalog.mockImplementation(() => new Promise(() => undefined))
    } else if (options.catalogReject) {
      mockContainer.fetchOnboardingIndustryCatalog.mockRejectedValue(new Error('catalog fail'))
    } else {
      mockContainer.fetchOnboardingIndustryCatalog.mockResolvedValue(options.catalog === undefined ? null : options.catalog)
    }
    mockContainer.updateCompanyBrand.mockImplementation(async (name: string) => ({ success: true, company_brand: name, tenant_name: name }))
    mockContainer.installHostFoundation.mockResolvedValue({ success: true, message: '' })
    mockContainer.installMod.mockResolvedValue({ success: true, message: '' })
    mockContainer.installIndustrySeed.mockResolvedValue({ success: true, message: '' })
    mockContainer.installCustomerDeliverySeed.mockResolvedValue({ success: true, message: '' })
    mockContainer.autoOnboardWorkflowEmployeesFromMods.mockResolvedValue([])
    mockContainer.seedOnboardingDemo.mockResolvedValue({
      industry_id: '涂料',
      customer: { id: 1, name: '新手演示客户' },
      product: { id: 1, name: '新手演示商品' },
    })
    mockContainer.appAlert.mockResolvedValue(undefined)
    mockContainer.patchWorkspacePrefs.mockResolvedValue({ success: true, data: {} })
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

describe('ProductOnboardingView three-step configuration contracts', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: true,
        status: 200,
        headers: { get: () => 'application/json' },
        json: async () => ({ success: true, data: {} }),
        text: async () => '',
      })),
    )
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

  async function press(wrapper: ReturnType<typeof mount>, text: string) {
    const button = wrapper.findAll('button').find((node) => node.text().includes(text))
    expect(button, `button ${text}`).toBeDefined()
    await button!.trigger('click')
    await flushPromises()
  }

  it('has exactly three setup steps and requires a company name before continuing', async () => {
    const { wrapper, router } = await mountComponent()
    expect(wrapper.findAll('.step-label').map((node) => node.text())).toEqual(['公司', '行业', '配置'])
    expect(wrapper.get('.btn.primary').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).not.toContain('价格预期')
    expect(wrapper.text()).not.toContain('Mod')
    await wrapper.get('#onboarding-company').setValue('蓝色科技 & 团队')
    await press(wrapper, '让 XC 认识我的公司')
    expect(router.currentRoute.value.query).toMatchObject({ step: 'industry', company: '蓝色科技 & 团队' })
    expect(mockContainer.seedOnboardingDemo).not.toHaveBeenCalled()
    expect(mockContainer.patchWorkspacePrefs).not.toHaveBeenCalled()
  })

  it('lets users expand the full taxonomy and preserves their selection when returning from company details', async () => {
    const { wrapper, router } = await mountComponent({ route: { step: 'industry' } })
    await press(wrapper, '全部')
    const initialCount = wrapper.findAll('[role="option"]').length
    await press(wrapper, '查看另外')
    const options = wrapper.findAll('[role="option"]')
    expect(options.length).toBeGreaterThan(initialCount)
    const selected = options[options.length - 1]
    const selectedName = selected.get('.industry-chip-name').text()
    await selected.trigger('click')
    await flushPromises()
    expect(selected.attributes('aria-selected')).toBe('true')
    expect(wrapper.get('.industry-understanding').text()).toContain(selectedName)

    await press(wrapper, '返回公司名称')
    expect(router.currentRoute.value.query.step).toBe('welcome')
    await wrapper.get('#onboarding-company').setValue('行业选择测试公司')
    await press(wrapper, '让 XC 认识我的公司')
    expect(router.currentRoute.value.query.step).toBe('industry')
    expect(wrapper.get('[role="option"][aria-selected="true"]').text()).toContain(selectedName)
    expect(mockContainer.patchWorkspacePrefs).not.toHaveBeenCalled()
    expect(mockContainer.seedOnboardingDemo).not.toHaveBeenCalled()
  })

  it('searches the company taxonomy even when no dedicated package is offered', async () => {
    const { wrapper } = await mountComponent({ route: { step: 'industry' }, catalog: { open_industry_ids: [], open_packages: [] } })
    await wrapper.get('#onboarding-industry-search').setValue('SaaS')
    expect(wrapper.findAll('[role="option"]')).toHaveLength(1)
    expect(wrapper.get('[role="option"]').text()).toContain('软件与信息技术')
    await wrapper.get('[role="option"]').trigger('click')
    expect(wrapper.text()).toContain('通用业务能力')
    expect(wrapper.text()).not.toContain('即将开放')
  })

  it('supports a custom industry and clears the previous dedicated package binding without seeding', async () => {
    const { wrapper, router } = await mountComponent({ route: { step: 'industry' }, industry: { currentIndustryId: '涂料' } })
    await wrapper.get('#onboarding-industry-search').setValue('智能硬件服务')
    await press(wrapper, '作为行业')
    await press(wrapper, '生成我的配置方案')
    expect(mockContainer.patchWorkspacePrefs).toHaveBeenCalledWith({ selected_industry_id: '智能硬件服务', industry_mod_id: '' })
    expect(mockContainer.industryState.loadFromServer).toHaveBeenCalled()
    expect(router.currentRoute.value.query.step).toBe('host-pack')
    expect(wrapper.text()).toContain('通用业务工作空间')
    expect(mockContainer.seedOnboardingDemo).not.toHaveBeenCalled()
    expect(localStorage.getItem('xcagi_product_flow_pending_prompt')).toBeNull()
  })

  it('keeps the selected company and industry when company persistence is rejected', async () => {
    const { wrapper, router } = await mountComponent()
    await wrapper.get('#onboarding-company').setValue('公司名称')
    await press(wrapper, '让 XC 认识我的公司')
    mockContainer.updateCompanyBrand.mockRejectedValue(new Error('名称未同步到账户'))
    await press(wrapper, '生成我的配置方案')
    expect(router.currentRoute.value.query.step).toBe('industry')
    expect(mockContainer.appAlert).toHaveBeenCalledWith('名称未同步到账户')
    expect(mockContainer.patchWorkspacePrefs).not.toHaveBeenCalled()
  })

  it.each([false, 'offline'])('does not bind or install when the account validation is %s', async (state) => {
    const { wrapper, router } = await mountComponent({ route: { step: 'industry' } })
    if (state === false) vi.mocked(validateEnterpriseSessionCached).mockResolvedValue(false)
    else vi.mocked(validateEnterpriseSessionCached).mockRejectedValue(new Error('network offline'))
    await press(wrapper, '生成我的配置方案')
    expect(mockContainer.patchWorkspacePrefs).not.toHaveBeenCalled()
    expect(mockContainer.installHostFoundation).not.toHaveBeenCalled()
    expect(router.currentRoute.value.query.step).toBe('industry')
    expect(state === false ? wrapper.text().includes('登录并继续设置') : mockContainer.appAlert.mock.calls.length > 0).toBe(true)
  })

  it('stays on industry when the binding business result is false', async () => {
    const { wrapper, router } = await mountComponent({ route: { step: 'industry' } })
    mockContainer.patchWorkspacePrefs.mockResolvedValue({ success: false })
    await press(wrapper, '生成我的配置方案')
    expect(router.currentRoute.value.query.step).toBe('industry')
    expect(mockContainer.industryState.loadFromServer).not.toHaveBeenCalled()
    expect(mockContainer.appAlert).toHaveBeenCalledWith('行业未保存，请重试')
  })

  it('does not pretend a stale industry store has refreshed', async () => {
    const { wrapper, router } = await mountComponent({ route: { step: 'industry' }, industry: { currentIndustryId: '旧行业', loadFromServer: vi.fn().mockResolvedValue(undefined) } })
    await wrapper.get('#onboarding-industry-search').setValue('新行业')
    await press(wrapper, '作为行业')
    await press(wrapper, '生成我的配置方案')
    expect(router.currentRoute.value.query.step).toBe('industry')
    expect(mockContainer.appAlert).toHaveBeenCalledWith('行业已保存，但工作空间尚未刷新，请重试')
  })

  it('lists actual capabilities separately from deferred business concepts', async () => {
    const { wrapper } = await mountComponent({ route: { step: 'host-pack' }, industry: { currentIndustryId: '软件信息' }, baseline: createBaselinePlan({ baseline_ready: true }) })
    expect(wrapper.get('[aria-label="行业工作空间方案"]').text()).toContain('服务订单')
    expect(wrapper.get('[aria-label="行业工作空间方案"]').text()).not.toContain('合同管理')
    expect(wrapper.get('.capability-note').text()).toContain('合同管理')
    expect(wrapper.text()).toContain('通用业务工作空间')
  })

  it('completes configuration with a confirmed server receipt and no demo task', async () => {
    const { wrapper } = await mountComponent({ route: { step: 'host-pack' }, baseline: createBaselinePlan({ baseline_ready: true }) })
    await press(wrapper, '进入我的工作空间')
    expect(mockContainer.patchWorkspacePrefs).toHaveBeenCalledWith({ host_pack_acknowledged: true, product_flow_completed: true })
    expect(mockContainer.flowState.completeFlowAndGoChat).toHaveBeenCalledOnce()
    expect(mockContainer.seedOnboardingDemo).not.toHaveBeenCalled()
    expect(localStorage.getItem('xcagi_product_flow_first_task_pending')).toBeNull()
  })

  it('does not complete configuration when the server rejects its receipt', async () => {
    const { wrapper } = await mountComponent({ route: { step: 'host-pack' }, baseline: createBaselinePlan({ baseline_ready: true }) })
    mockContainer.patchWorkspacePrefs.mockImplementation(async (patch) => ({ success: patch.product_flow_completed !== true }))
    await press(wrapper, '进入我的工作空间')
    expect(mockContainer.patchWorkspacePrefs).toHaveBeenCalledWith({ selected_industry_id: expect.any(String), industry_mod_id: '' })
    expect(mockContainer.patchWorkspacePrefs).toHaveBeenCalledWith({ host_pack_acknowledged: true, product_flow_completed: true })
    expect(mockContainer.flowState.completeFlowAndGoChat).not.toHaveBeenCalled()
    expect(mockContainer.appAlert).toHaveBeenCalledWith('工作空间配置未保存，请重试')
  })

  it('installs missing features and enters the workspace without adding extra setup steps', async () => {
    const { wrapper } = await mountComponent({ route: { step: 'host-pack' } })
    mockBaselineForInstallation(mockContainer.installHostFoundation)
    await press(wrapper, '进入我的工作空间')
    expect(mockContainer.installHostFoundation).toHaveBeenCalledOnce()
    expect(mockContainer.flowState.completeFlowAndGoChat).toHaveBeenCalledOnce()
    expect(mockContainer.seedOnboardingDemo).not.toHaveBeenCalled()
    await expect(mockContainer.fetchIndustryBaseline()).resolves.toMatchObject({ baseline_ready: true })
  })

  it('offers the example separately and waits for another explicit click before seeding', async () => {
    const { wrapper, router } = await mountComponent({ route: { step: 'host-pack' }, baseline: createBaselinePlan({ baseline_ready: true }) })
    await press(wrapper, '查看演示业务体验')
    expect(router.currentRoute.value.query.step).toBe('seed-demo')
    expect(mockContainer.seedOnboardingDemo).not.toHaveBeenCalled()
    expect(mockContainer.flowState.markProductFlowCompleted).not.toHaveBeenCalled()
  })

  it('returns tutorial replay to the source without modifying configuration', async () => {
    const { wrapper, router } = await mountComponent({ route: { step: 'industry', from: 'tutorial', redirect: '/data-sources?tab=files' } })
    await press(wrapper, '返回上一页')
    expect(router.currentRoute.value.fullPath).toBe('/data-sources?tab=files')
    expect(mockContainer.patchWorkspacePrefs).not.toHaveBeenCalled()
    expect(mockContainer.seedOnboardingDemo).not.toHaveBeenCalled()
  })

  it('allows an unfinished workspace to be skipped for this session only', async () => {
    const { wrapper } = await mountComponent({ route: { step: 'host-pack' } })
    await press(wrapper, '先进入，稍后再设置')
    expect(mockContainer.markHostPackSkippedThisSession).toHaveBeenCalled()
    expect(mockContainer.flowState.markProductFlowCompleted).not.toHaveBeenCalled()
  })

  it('runBootstrap：装齐失败时调用 appAlert 显示错误', async () => {
    const { wrapper } = await mountComponent({
      route: { step: 'host-pack' },
      baseline: createBaselinePlan({ baseline_ready: false }),
    })
    await flushPromises()
    await flushPromises()
    // 在 mountComponent 之后设置 mock，避免被默认 mock 覆盖
    mockContainer.installHostFoundation.mockResolvedValue({
      success: false,
      message: '宿主装包失败',
    })
    mockBaselineForInstallation(mockContainer.installHostFoundation, createBaselinePlan({ baseline_ready: false, missing_required_mod_ids: ['mod-x'] }))
    mockContainer.appAlert.mockClear()
    const bootstrapBtn = wrapper.find('.btn.primary')
    await bootstrapBtn.trigger('click')
    await flushPromises()
    await flushPromises()
    await flushPromises()
    expect(mockContainer.appAlert).toHaveBeenCalled()
    const alertMsg = mockContainer.appAlert.mock.calls[0][0] as string
    expect(alertMsg).toContain('宿主装包失败')
    expect(mockContainer.installHostFoundation).toHaveBeenCalledOnce()
    expect(mockContainer.flowState.completeFlowAndGoChat).not.toHaveBeenCalled()
    await expect(mockContainer.fetchIndustryBaseline()).resolves.toMatchObject({ baseline_ready: false })
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
    mockBaselineForInstallation(mockContainer.installHostFoundation)
    mockContainer.appAlert.mockClear()
    const bootstrapBtn = wrapper.find('.btn.primary')
    await bootstrapBtn.trigger('click')
    await flushPromises()
    await flushPromises()
    await flushPromises()
    expect(mockContainer.appAlert).toHaveBeenCalledWith('网络错误')
    expect(mockContainer.installHostFoundation).toHaveBeenCalledOnce()
    expect(mockContainer.flowState.completeFlowAndGoChat).not.toHaveBeenCalled()
    await expect(mockContainer.fetchIndustryBaseline()).resolves.toMatchObject({ baseline_ready: false })
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
    mockBaselineForInstallation(mockContainer.installHostFoundation)
    mockContainer.appAlert.mockClear()
    const bootstrapBtn = wrapper.find('.btn.primary')
    await bootstrapBtn.trigger('click')
    await flushPromises()
    await flushPromises()
    await flushPromises()
    expect(mockContainer.appAlert).toHaveBeenCalledWith('string error')
    expect(mockContainer.installHostFoundation).toHaveBeenCalledOnce()
    expect(mockContainer.flowState.completeFlowAndGoChat).not.toHaveBeenCalled()
    await expect(mockContainer.fetchIndustryBaseline()).resolves.toMatchObject({ baseline_ready: false })
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
    mockContainer.installIndustrySeed.mockResolvedValue({ success: true, message: '' })
    mockContainer.installIndustrySeed.mockClear()
    mockBaselineForInstallation(mockContainer.installIndustrySeed, createBaselinePlan({ baseline_ready: false, missing_industry_mod_ids: ['ind-1'] }))
    const bootstrapBtn = wrapper.find('.btn.primary')
    await bootstrapBtn.trigger('click')
    await flushPromises()
    await flushPromises()
    await flushPromises()
    expect(mockContainer.installIndustrySeed).toHaveBeenCalled()
    await expect(mockContainer.fetchIndustryBaseline()).resolves.toMatchObject({ baseline_ready: true })
    expect(mockContainer.flowState.completeFlowAndGoChat).toHaveBeenCalledOnce()
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
    mockContainer.installIndustrySeed.mockResolvedValue({ success: false, message: '行业包失败' })
    mockContainer.appAlert.mockClear()
    mockBaselineForInstallation(mockContainer.installIndustrySeed, createBaselinePlan({ baseline_ready: false, missing_industry_mod_ids: ['ind-1'] }))
    const bootstrapBtn = wrapper.find('.btn.primary')
    await bootstrapBtn.trigger('click')
    await flushPromises()
    await flushPromises()
    await flushPromises()
    expect(mockContainer.appAlert).toHaveBeenCalled()
    const alertMsg = mockContainer.appAlert.mock.calls[0][0] as string
    expect(alertMsg).toContain('行业包')
    expect(mockContainer.installIndustrySeed).toHaveBeenCalledOnce()
    expect(mockContainer.flowState.completeFlowAndGoChat).not.toHaveBeenCalled()
    await expect(mockContainer.fetchIndustryBaseline()).resolves.toMatchObject({ baseline_ready: false, missing_industry_mod_ids: ['ind-1'] })
    expect(mockContainer.appAlert.mock.calls[0][0]).toContain('行业包失败')
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
    mockContainer.installIndustrySeed.mockRejectedValue(new Error('行业包异常'))
    mockContainer.appAlert.mockClear()
    mockBaselineForInstallation(mockContainer.installIndustrySeed, createBaselinePlan({ baseline_ready: false, missing_industry_mod_ids: ['ind-1'] }))
    const bootstrapBtn = wrapper.find('.btn.primary')
    await bootstrapBtn.trigger('click')
    await flushPromises()
    await flushPromises()
    await flushPromises()
    expect(mockContainer.appAlert).toHaveBeenCalled()
    expect(mockContainer.installIndustrySeed).toHaveBeenCalledOnce()
    expect(mockContainer.flowState.completeFlowAndGoChat).not.toHaveBeenCalled()
    await expect(mockContainer.fetchIndustryBaseline()).resolves.toMatchObject({ baseline_ready: false, missing_industry_mod_ids: ['ind-1'] })
    expect(mockContainer.appAlert.mock.calls[0][0]).toContain('行业包异常')
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
    mockContainer.installMod.mockClear()
    mockContainer.autoOnboardWorkflowEmployeesFromMods.mockClear()
    mockBaselineForInstallation(mockContainer.installMod, createBaselinePlan({ baseline_ready: false, missing_account_custom_mod_ids: ['custom-1'] }))
    const bootstrapBtn = wrapper.find('.btn.primary')
    await bootstrapBtn.trigger('click')
    await flushPromises()
    await flushPromises()
    await flushPromises()
    expect(mockContainer.installMod).toHaveBeenCalledWith('custom-1')
    expect(mockContainer.autoOnboardWorkflowEmployeesFromMods).toHaveBeenCalled()
    await expect(mockContainer.fetchIndustryBaseline()).resolves.toMatchObject({ baseline_ready: true })
    expect(mockContainer.flowState.completeFlowAndGoChat).toHaveBeenCalledOnce()
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
    mockContainer.installMod.mockResolvedValue({ success: false, message: 'mod 失败' })
    mockContainer.appAlert.mockClear()
    mockBaselineForInstallation(mockContainer.installMod, createBaselinePlan({ baseline_ready: false, missing_account_custom_mod_ids: ['custom-1'] }))
    const bootstrapBtn = wrapper.find('.btn.primary')
    await bootstrapBtn.trigger('click')
    await flushPromises()
    await flushPromises()
    await flushPromises()
    expect(mockContainer.appAlert).toHaveBeenCalled()
    expect(mockContainer.installMod).toHaveBeenCalledOnce()
    expect(mockContainer.flowState.completeFlowAndGoChat).not.toHaveBeenCalled()
    await expect(mockContainer.fetchIndustryBaseline()).resolves.toMatchObject({ baseline_ready: false, missing_account_custom_mod_ids: ['custom-1'] })
    expect(mockContainer.appAlert.mock.calls[0][0]).toContain('mod 失败')
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
    mockContainer.installMod.mockRejectedValue(new Error('mod 异常'))
    mockContainer.appAlert.mockClear()
    mockBaselineForInstallation(mockContainer.installMod, createBaselinePlan({ baseline_ready: false, missing_account_custom_mod_ids: ['custom-1'] }))
    const bootstrapBtn = wrapper.find('.btn.primary')
    await bootstrapBtn.trigger('click')
    await flushPromises()
    await flushPromises()
    await flushPromises()
    expect(mockContainer.appAlert).toHaveBeenCalled()
    expect(mockContainer.installMod).toHaveBeenCalledOnce()
    expect(mockContainer.flowState.completeFlowAndGoChat).not.toHaveBeenCalled()
    await expect(mockContainer.fetchIndustryBaseline()).resolves.toMatchObject({ baseline_ready: false, missing_account_custom_mod_ids: ['custom-1'] })
    expect(mockContainer.appAlert.mock.calls[0][0]).toContain('mod 异常')
  })

  it('runBootstrap：account_delivery_seed_packages 时调用 installCustomerDeliverySeed', async () => {
    const seedBaseline = createBaselinePlan({
      baseline_ready: false,
      account_custom_mod_ids: ['custom-1', 'xcagi-core-workflow-employees'],
      account_delivery_seed_packages: [{ mod_id: 'custom-1', pkg_id: 'seed-1', version: '1.0.0' }],
    })
    const { wrapper } = await mountComponent({
      route: { step: 'host-pack' },
      baseline: seedBaseline,
    })
    await flushPromises()
    await flushPromises()
    mockContainer.installCustomerDeliverySeed.mockClear()
    mockBaselineForInstallation(mockContainer.installCustomerDeliverySeed, seedBaseline)
    const bootstrapBtn = wrapper.find('.btn.primary')
    await bootstrapBtn.trigger('click')
    await flushPromises()
    await flushPromises()
    await flushPromises()
    expect(mockContainer.installCustomerDeliverySeed).toHaveBeenCalledWith('custom-1', expect.any(String))
    expect(mockContainer.installCustomerDeliverySeed).not.toHaveBeenCalledWith('xcagi-core-workflow-employees', expect.any(String))
    await expect(mockContainer.fetchIndustryBaseline()).resolves.toMatchObject({ baseline_ready: true })
    expect(mockContainer.flowState.completeFlowAndGoChat).toHaveBeenCalledOnce()
  })

  it('runBootstrap：installCustomerDeliverySeed 返回 success=false 时记录错误', async () => {
    const seedBaseline = createBaselinePlan({
      baseline_ready: false,
      account_custom_mod_ids: ['custom-1'],
      account_delivery_seed_packages: [{ mod_id: 'custom-1', pkg_id: 'seed-1', version: '1.0.0' }],
    })
    const { wrapper } = await mountComponent({
      route: { step: 'host-pack' },
      baseline: seedBaseline,
    })
    await flushPromises()
    await flushPromises()
    mockContainer.installCustomerDeliverySeed.mockResolvedValue({
      success: false,
      message: '交付失败',
    })
    mockContainer.appAlert.mockClear()
    mockBaselineForInstallation(mockContainer.installCustomerDeliverySeed, seedBaseline)
    const bootstrapBtn = wrapper.find('.btn.primary')
    await bootstrapBtn.trigger('click')
    await flushPromises()
    await flushPromises()
    await flushPromises()
    expect(mockContainer.appAlert).toHaveBeenCalled()
    expect(mockContainer.installCustomerDeliverySeed).toHaveBeenCalledOnce()
    expect(mockContainer.flowState.completeFlowAndGoChat).not.toHaveBeenCalled()
    await expect(mockContainer.fetchIndustryBaseline()).resolves.toMatchObject(seedBaseline)
    expect(mockContainer.appAlert.mock.calls[0][0]).toContain('交付失败')
  })

  it('runBootstrap：installCustomerDeliverySeed 抛异常时记录错误', async () => {
    const seedBaseline = createBaselinePlan({
      baseline_ready: false,
      account_custom_mod_ids: ['custom-1'],
      account_delivery_seed_packages: [{ mod_id: 'custom-1', pkg_id: 'seed-1', version: '1.0.0' }],
    })
    const { wrapper } = await mountComponent({
      route: { step: 'host-pack' },
      baseline: seedBaseline,
    })
    await flushPromises()
    await flushPromises()
    mockContainer.installCustomerDeliverySeed.mockRejectedValue(new Error('交付异常'))
    mockContainer.appAlert.mockClear()
    mockBaselineForInstallation(mockContainer.installCustomerDeliverySeed, seedBaseline)
    const bootstrapBtn = wrapper.find('.btn.primary')
    await bootstrapBtn.trigger('click')
    await flushPromises()
    await flushPromises()
    await flushPromises()
    expect(mockContainer.appAlert).toHaveBeenCalled()
    expect(mockContainer.installCustomerDeliverySeed).toHaveBeenCalledOnce()
    expect(mockContainer.flowState.completeFlowAndGoChat).not.toHaveBeenCalled()
    await expect(mockContainer.fetchIndustryBaseline()).resolves.toMatchObject(seedBaseline)
    expect(mockContainer.appAlert.mock.calls[0][0]).toContain('交付异常')
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
    mockContainer.autoOnboardWorkflowEmployeesFromMods.mockRejectedValue(new Error('onboard 失败'))
    const consoleSpy = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    mockBaselineForInstallation(mockContainer.installMod, createBaselinePlan({ baseline_ready: false, missing_account_custom_mod_ids: ['custom-1'] }))
    const bootstrapBtn = wrapper.find('.btn.primary')
    await bootstrapBtn.trigger('click')
    await flushPromises()
    await flushPromises()
    await flushPromises()
    await flushPromises()
    expect(consoleSpy).toHaveBeenCalled()
    consoleSpy.mockRestore()
    await expect(mockContainer.fetchIndustryBaseline()).resolves.toMatchObject({ baseline_ready: true })
    expect(mockContainer.flowState.completeFlowAndGoChat).toHaveBeenCalledOnce()
  })


})
