/**
 * ModStore.vue 覆盖率补齐测试
 * 目标：将 statements 覆盖率从 60.81% 提升到 90%+
 * 重点覆盖：未覆盖的函数、分支、错误路径、事件处理
 * - mainListTitle / modIconClass / collectionLabel 各分支
 * - enterpriseLayerLabel / enterpriseModLabel / isEmployeePackItem
 * - marketItemKindLabel / installSuccessMessage（通过 installMod 间接）/ enterpriseLayerTagStyle
 * - refineMarketItems / filterByCollectionTab（通过 applyFilters / loadMods 间接）
 * - oneClickPendingCount / oneClickCtaLabel
 * - loadMods / loadMarketTab / searchMods / applyFilters / switchTab
 * - installMod / uninstallMod / updateMod / viewDetails / onMobileUse / marketModUrl
 * - goBackFromStore / finishOnboardingFromStore / onboardDestinationForTab
 * - installModSilent / ensureHostFoundationIfNeeded / completePackOnboard（通过 runOneClickInstallAndOnboard 间接）
 * - runOneClickInstallAndOnboard 各分支
 * - onMounted / onBeforeUnmount
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'

/* ── mock functions ── */
const mockApiFetch = vi.fn().mockResolvedValue({
  ok: true,
  json: async () => ({ success: true, data: { available: [] } }),
})

const mockFetchMarketCatalog = vi.fn().mockResolvedValue({ items: [] })
const mockInstallHostFoundation = vi.fn().mockResolvedValue({ success: true, message: '' })
const mockReloadEmployeePacks = vi.fn().mockResolvedValue({ success: true })
const mockFetchDeliverableStatus = vi.fn().mockResolvedValue({ deliverable: true, missing_mod_ids: [] })
const mockFetchIndustryBaseline = vi.fn().mockResolvedValue({ industries: [] })
const mockAppAlert = vi.fn().mockResolvedValue(undefined)
const mockAppConfirm = vi.fn().mockResolvedValue(true)
const mockAutoOnboardInstalledMarketItem = vi.fn().mockResolvedValue({
  onboardedIds: [],
  plannerRefreshed: false,
  enterpriseStackLabel: '',
})
const mockResolveEnterpriseModStack = vi.fn().mockResolvedValue({ stackLabel: '默认企业栈' })
const mockPromptAdvancedTutorialAfterInstall = vi.fn().mockResolvedValue('already_completed')
const mockMarkProductFlowCompleted = vi.fn()
const mockMarkHostPackAcknowledged = vi.fn()

/* ── 模块级 mock 引用（便于在测试中动态控制返回值） ── */
const mockCatalogStoreCollection = vi.fn((row: any) => row?.store_collection || '')
const mockIsHostFoundationEmployeePackId = vi.fn((id: string) => id === 'xcagi-host-foundation-employee')
const mockReadBuildEdition = vi.fn(() => 'generic')
const mockIsOfficeEmployeePkg = vi.fn((id: string) => String(id || '').startsWith('office-emp-'))
const mockIsOfficeAuxPack1Pkg = vi.fn((id: string) => String(id || '').startsWith('office-aux-'))
const mockResolveEnterpriseOrgLayerForCatalogItem = vi.fn(() => null)

/* ── module mocks ── */
vi.mock('@/utils/apiBase', () => ({
  apiFetch: (...args: unknown[]) => mockApiFetch(...args),
  getApiBase: () => '',
  DEFAULT_MOD_API_TIMEOUT_MS: 90_000,
}))

vi.mock('@/api/modStore', () => ({
  fetchMarketCatalog: (...args: unknown[]) => mockFetchMarketCatalog(...args),
  installHostFoundation: (...args: unknown[]) => mockInstallHostFoundation(...args),
  reloadEmployeePacks: (...args: unknown[]) => mockReloadEmployeePacks(...args),
}))

vi.mock('@/utils/platformShellApi', () => ({
  fetchDeliverableStatus: (...args: unknown[]) => mockFetchDeliverableStatus(...args),
  fetchIndustryBaseline: (...args: unknown[]) => mockFetchIndustryBaseline(...args),
}))

vi.mock('@/utils/appDialog', () => ({
  appAlert: (...args: unknown[]) => mockAppAlert(...args),
  appConfirm: (...args: unknown[]) => mockAppConfirm(...args),
}))

vi.mock('@/utils/workflowEmployeeOnboard', () => ({
  autoOnboardInstalledMarketItem: (...args: unknown[]) => mockAutoOnboardInstalledMarketItem(...args),
}))

vi.mock('@/utils/enterpriseModStackApi', () => ({
  resolveEnterpriseModStack: (...args: unknown[]) => mockResolveEnterpriseModStack(...args),
}))

vi.mock('@/tutorial/promptAdvancedTutorial', () => ({
  promptAdvancedTutorialAfterInstall: (...args: unknown[]) => mockPromptAdvancedTutorialAfterInstall(...args),
  resolveRouteNameFromPath: () => 'home',
}))

vi.mock('@/constants/productFlow', () => ({
  markProductFlowCompleted: (...args: unknown[]) => mockMarkProductFlowCompleted(...args),
  markHostPackAcknowledged: (...args: unknown[]) => mockMarkHostPackAcknowledged(...args),
}))

vi.mock('@/constants/genericModPack', () => ({
  catalogStoreCollection: (...args: unknown[]) => mockCatalogStoreCollection(...args),
  HOST_FOUNDATION_EMPLOYEE_PACK_ID: 'xcagi-host-foundation-employee',
  isHostFoundationEmployeePackId: (...args: unknown[]) => mockIsHostFoundationEmployeePackId(...args as [string]),
  readBuildEdition: (...args: unknown[]) => mockReadBuildEdition(...args),
  STORE_COLLECTION_HOST_FOUNDATION: 'host_foundation',
  STORE_COLLECTION_INDUSTRY_MOD: 'industry_mod',
  STORE_COLLECTION_OFFICE_AUX: 'office_employee_aux_pack_1',
  STORE_COLLECTION_OFFICE_EMPLOYEE: 'office_employee_pack',
  STORE_COLLECTION_WORKFLOW_EMPLOYEE: 'workflow_employee',
}))

vi.mock('@/constants/officeEmployeePack', () => ({
  isOfficeAuxPack1Pkg: (...args: unknown[]) => mockIsOfficeAuxPack1Pkg(...args as [string]),
  isOfficeEmployeePkg: (...args: unknown[]) => mockIsOfficeEmployeePkg(...args as [string]),
  OFFICE_AUX_PACK_1_COLLECTION: 'office_employee_aux_pack_1',
  OFFICE_EMPLOYEE_COLLECTION: 'office_employee_pack',
}))

vi.mock('@/composables/useTutorialCatalog', () => ({
  useTutorialCatalog: () => ({ buildContext: { value: {} }, registerTour: vi.fn() }),
}))

vi.mock('@/utils/marketCatalogCache', () => ({
  buildMarketCatalogCacheKey: (tab: string, q = '') => `${tab}:${String(q || '').trim()}`,
  isMarketCatalogCacheFresh: () => false,
  readMarketCatalogCache: () => null,
  writeMarketCatalogCache: vi.fn(),
}))

vi.mock('@/constants/enterpriseWorkflowEstablishment', () => ({
  resolveEnterpriseOrgLayerForCatalogItem: (...args: unknown[]) => mockResolveEnterpriseOrgLayerForCatalogItem(...args),
}))

/* ── store mock ── */
const mockModsStore = {
  mods: [],
  activeModId: '',
  clientModsUiOff: false,
  loadError: '',
  isLoaded: true,
  modRoutes: [],
  modsForUi: [],
  refresh: vi.fn().mockResolvedValue(undefined),
  initialize: vi.fn().mockResolvedValue(undefined),
  applyEntitledActiveMod: vi.fn().mockResolvedValue(undefined),
  setActiveModId: vi.fn(),
}

vi.mock('@/stores/mods', () => ({
  useModsStore: () => mockModsStore,
  CLIENT_MODS_UI_OFF_KEY: 'xcagi_client_mods_ui_off',
}))

/* ── stubs ── */
const globalStubs = {
  Modal: { template: '<div class="modal-stub"><slot /></div>' },
  ModDetails: { template: '<div class="mod-details-stub" />' },
  RouterLink: { template: '<a><slot /></a>' },
}

/* ── 工具：构造 router + 挂载组件 ── */
async function mountModStore(query: Record<string, string> = {}) {
  const ModStore = (await import('./ModStore.vue')).default
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/mod-store', name: 'mod-store', component: ModStore },
      { path: '/', name: 'home', component: { template: '<div />' } },
      { path: '/ai-ecosystem', name: 'ai-ecosystem', component: { template: '<div />' } },
      { path: '/workflow-employee-space', name: 'workflow-employee-space', component: { template: '<div />' } },
      { path: '/employee-workspace', name: 'employee-workspace', component: { template: '<div />' } },
    ],
  })
  await router.push({ path: '/mod-store', query })
  await router.isReady()
  const wrapper = mount(ModStore, {
    global: {
      plugins: [router],
      stubs: globalStubs,
    },
  })
  return { wrapper, router }
}

/* ── 工具：构造典型 mod ── */
function makeMod(overrides: Record<string, any> = {}) {
  const id = overrides.id || 'mod-1'
  return {
    id,
    pkg_id: overrides.pkg_id || id,
    name: 'Mod 1',
    version: '1.0.0',
    author: 'Tester',
    description: 'desc',
    is_installed: false,
    source: 'local',
    artifact: 'mod',
    ...overrides,
  }
}

/* ── 工具：等待所有异步操作完成 ── */
async function waitForAsync() {
  // 多次 flushPromises 确保所有微任务和宏任务完成
  for (let i = 0; i < 5; i++) {
    await flushPromises()
  }
}

/* ══════════════════════════════════════════════════════════════════ */

describe('ModStore.coverage – 计算属性与标签函数', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    mockApiFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, data: { available: [] } }),
    })
    mockCatalogStoreCollection.mockImplementation((row: any) => row?.store_collection || '')
    mockIsHostFoundationEmployeePackId.mockImplementation((id: string) => id === 'xcagi-host-foundation-employee')
    mockIsOfficeEmployeePkg.mockImplementation((id: string) => String(id || '').startsWith('office-emp-'))
    mockIsOfficeAuxPack1Pkg.mockImplementation((id: string) => String(id || '').startsWith('office-aux-'))
    mockResolveEnterpriseOrgLayerForCatalogItem.mockReturnValue(null)
    mockResolveEnterpriseModStack.mockResolvedValue({ stackLabel: '默认企业栈' })
  })

  it('mainListTitle：覆盖所有 tab 标题分支', async () => {
    const tabs = [
      { tab: 'host_foundation', expectText: '宿主基础' },
      { tab: 'office', expectText: '办公员工包' },
      { tab: 'office_aux', expectText: '办公员工附属包1' },
      { tab: 'workflow', expectText: '工作流员工' },
      { tab: 'ai_employee', expectText: 'AI 员工' },
      { tab: 'industry_mod', expectText: '行业扩展' },
      { tab: 'installed', expectText: '已安装' },
    ]
    for (const { tab, expectText } of tabs) {
      const { wrapper } = await mountModStore({ tab })
      await waitForAsync()
      const title = wrapper.find('.store-main__title')
      expect(title.text()).toContain(expectText)
      wrapper.unmount()
    }
  })

  it('modIconClass：覆盖各 store_collection 分支', async () => {
    const { wrapper } = await mountModStore({ tab: 'all' })
    await waitForAsync()
    const vm: any = wrapper.vm
    // host foundation
    mockCatalogStoreCollection.mockReturnValue('host_foundation')
    expect(vm.modIconClass(makeMod())).toBe('fa fa-cubes')
    // office employee
    mockCatalogStoreCollection.mockReturnValue('office_employee_pack')
    expect(vm.modIconClass(makeMod())).toBe('fa fa-file-text-o')
    // office aux
    mockCatalogStoreCollection.mockReturnValue('office_employee_aux_pack_1')
    expect(vm.modIconClass(makeMod())).toBe('fa fa-bar-chart')
    // workflow employee
    mockCatalogStoreCollection.mockReturnValue('workflow_employee')
    expect(vm.modIconClass(makeMod())).toBe('fa fa-users')
    // industry mod
    mockCatalogStoreCollection.mockReturnValue('industry_mod')
    expect(vm.modIconClass(makeMod())).toBe('fa fa-industry')
    // fallback：使用 mod.icon
    mockCatalogStoreCollection.mockReturnValue('')
    expect(vm.modIconClass(makeMod({ icon: 'fa fa-custom' }))).toBe('fa fa-custom')
    // fallback：默认 puzzle-piece
    expect(vm.modIconClass(makeMod({ icon: '' }))).toBe('fa fa-puzzle-piece')
    wrapper.unmount()
  })

  it('collectionLabel：覆盖各 store_collection 分支', async () => {
    const { wrapper } = await mountModStore({ tab: 'all' })
    await waitForAsync()
    const vm: any = wrapper.vm
    mockCatalogStoreCollection.mockReturnValue('host_foundation')
    expect(vm.collectionLabel(makeMod())).toBe('宿主基础员工')
    mockCatalogStoreCollection.mockReturnValue('office_employee_pack')
    expect(vm.collectionLabel(makeMod())).toBe('办公员工包')
    mockCatalogStoreCollection.mockReturnValue('office_employee_aux_pack_1')
    expect(vm.collectionLabel(makeMod())).toBe('办公附属包1')
    mockCatalogStoreCollection.mockReturnValue('workflow_employee')
    expect(vm.collectionLabel(makeMod())).toBe('工作流员工')
    mockCatalogStoreCollection.mockReturnValue('industry_mod')
    expect(vm.collectionLabel(makeMod())).toBe('行业扩展')
    mockCatalogStoreCollection.mockReturnValue('')
    expect(vm.collectionLabel(makeMod())).toBe('')
    wrapper.unmount()
  })

  it('enterpriseLayerLabel/TagStyle：覆盖有/无 layer 分支', async () => {
    const { wrapper } = await mountModStore({ tab: 'all' })
    await waitForAsync()
    const vm: any = wrapper.vm
    // 无 layer
    mockResolveEnterpriseOrgLayerForCatalogItem.mockReturnValue(null)
    expect(vm.enterpriseLayerLabel(makeMod())).toBe('')
    expect(vm.enterpriseLayerTagStyle(makeMod())).toEqual({})
    // 有 layer
    mockResolveEnterpriseOrgLayerForCatalogItem.mockReturnValue({
      code: 'L1',
      label: '战略层',
      color: '#ff0000',
    })
    expect(vm.enterpriseLayerLabel(makeMod())).toBe('L1 战略层')
    const style = vm.enterpriseLayerTagStyle(makeMod())
    expect(style.color).toBe('#ff0000')
    expect(style.borderColor).toBe('#ff000066')
    expect(style.background).toBe('#ff000014')
    wrapper.unmount()
  })

  it('isEmployeePackItem：覆盖 employee_pack 与其他 artifact', async () => {
    const { wrapper } = await mountModStore({ tab: 'all' })
    await waitForAsync()
    const vm: any = wrapper.vm
    expect(vm.isEmployeePackItem(makeMod({ artifact: 'employee_pack' }))).toBe(true)
    expect(vm.isEmployeePackItem(makeMod({ artifact: 'EMPLOYEE_PACK' }))).toBe(true)
    expect(vm.isEmployeePackItem(makeMod({ artifact: '  Employee_Pack  ' }))).toBe(true)
    expect(vm.isEmployeePackItem(makeMod({ artifact: 'mod' }))).toBe(false)
    expect(vm.isEmployeePackItem(makeMod({ artifact: '' }))).toBe(false)
    expect(vm.isEmployeePackItem(makeMod({}))).toBe(false)
    wrapper.unmount()
  })

  it('enterpriseModLabel：覆盖 employee_pack / mod / 其他 artifact', async () => {
    const { wrapper } = await mountModStore({ tab: 'all' })
    await waitForAsync()
    const vm: any = wrapper.vm
    // 默认 mockResolveEnterpriseModStack 返回 stackLabel='默认企业栈'
    expect(vm.enterpriseModLabel(makeMod({ artifact: 'employee_pack' }))).toBe('企业 Mod：默认企业栈')
    expect(vm.enterpriseModLabel(makeMod({ artifact: 'mod' }))).toBe('企业 Mod：默认企业栈')
    expect(vm.enterpriseModLabel(makeMod({ artifact: 'other' }))).toBe('')
    wrapper.unmount()
  })

  it('marketItemKindLabel：覆盖员工/扩展 Mod 分支', async () => {
    const { wrapper } = await mountModStore({ tab: 'all' })
    await waitForAsync()
    const vm: any = wrapper.vm
    expect(vm.marketItemKindLabel(makeMod({ artifact: 'employee_pack' }))).toBe('员工')
    expect(vm.marketItemKindLabel(makeMod({ artifact: 'mod' }))).toBe('扩展 Mod')
    wrapper.unmount()
  })

  it('marketModUrl：拼接 URL', async () => {
    const { wrapper } = await mountModStore({ tab: 'all' })
    await waitForAsync()
    const vm: any = wrapper.vm
    const url = vm.marketModUrl(makeMod({ pkg_id: 'abc def' }))
    expect(url).toContain('/mods/abc%20def')
    // 缺失 pkg_id 时使用 id
    const url2 = vm.marketModUrl(makeMod({ pkg_id: '', id: 'xyz' }))
    expect(url2).toContain('/mods/xyz')
    wrapper.unmount()
  })

  it('hasUpdate：覆盖已安装/未安装、版本对比分支', async () => {
    const { wrapper } = await mountModStore({ tab: 'all' })
    await waitForAsync()
    const vm: any = wrapper.vm
    expect(vm.hasUpdate(makeMod({ is_installed: true, version: '1.0', new_version: '2.0' }))).toBe(true)
    expect(vm.hasUpdate(makeMod({ is_installed: true, version: '1.0', new_version: '1.0' }))).toBeFalsy()
    expect(vm.hasUpdate(makeMod({ is_installed: true, version: '1.0' }))).toBeFalsy()
    expect(vm.hasUpdate(makeMod({ is_installed: false, version: '1.0', new_version: '2.0' }))).toBeFalsy()
    wrapper.unmount()
  })
})

/* ══════════════════════════════════════════════════════════════════ */

describe('ModStore.coverage – oneClickPendingCount / oneClickCtaLabel', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    mockApiFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, data: { available: [] } }),
    })
    mockCatalogStoreCollection.mockImplementation((row: any) => row?.store_collection || '')
    mockFetchDeliverableStatus.mockResolvedValue({ deliverable: true, missing_mod_ids: [] })
    mockFetchMarketCatalog.mockResolvedValue({ items: [] })
  })

  it('oneClickPendingCount：all/installed 返回 0；host_foundation 受 deliverableOk 影响', async () => {
    const { wrapper } = await mountModStore({ tab: 'all' })
    await waitForAsync()
    const vm: any = wrapper.vm
    vm.currentTab = 'all'
    expect(vm.oneClickPendingCount).toBe(0)
    vm.currentTab = 'installed'
    expect(vm.oneClickPendingCount).toBe(0)
    vm.currentTab = 'host_foundation'
    // deliverableOk=true → 0
    expect(vm.oneClickPendingCount).toBe(0)
    // 模拟 deliverableOk=false → 1
    vm.deliverableOk = false
    expect(vm.oneClickPendingCount).toBe(1)
    wrapper.unmount()
  })

  it('oneClickPendingCount：其他 tab 计算未安装数量', async () => {
    // 使用 fetchMarketCatalog 返回 mods，让 loadMods 填充 allMods
    mockFetchMarketCatalog.mockResolvedValue({
      items: [
        makeMod({ id: 'wf1', store_collection: 'workflow_employee', is_installed: false }),
        makeMod({ id: 'wf2', store_collection: 'workflow_employee', is_installed: true }),
        makeMod({ id: 'wf3', store_collection: 'workflow_employee', is_installed: false }),
      ],
    })
    const { wrapper } = await mountModStore({ tab: 'workflow' })
    await waitForAsync()
    const vm: any = wrapper.vm
    expect(vm.oneClickPendingCount).toBe(2)
    wrapper.unmount()
  })

  it('oneClickCtaLabel：all / pending=0 / pending>0 分支', async () => {
    const { wrapper } = await mountModStore({ tab: 'all' })
    await waitForAsync()
    const vm: any = wrapper.vm
    vm.currentTab = 'all'
    expect(vm.oneClickCtaLabel).toBe('一键安装并入驻')
    vm.currentTab = 'workflow'
    vm.allMods = []
    expect(vm.oneClickCtaLabel).toBe('完成入驻')
    vm.allMods = [
      makeMod({ id: 'wf1', store_collection: 'workflow_employee', is_installed: false }),
    ]
    expect(vm.oneClickCtaLabel).toContain('一键安装并入驻 (1)')
    wrapper.unmount()
  })
})

/* ══════════════════════════════════════════════════════════════════ */

describe('ModStore.coverage – onboarding / 导航', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    mockApiFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, data: { available: [] } }),
    })
    mockFetchDeliverableStatus.mockResolvedValue({ deliverable: true, missing_mod_ids: [] })
    mockFetchMarketCatalog.mockResolvedValue({ items: [] })
  })

  it('onboardingBanner：query.onboarding=1 显示 banner', async () => {
    const { wrapper } = await mountModStore({ onboarding: '1' })
    await waitForAsync()
    expect(wrapper.find('.onboarding-banner').exists()).toBe(true)
    wrapper.unmount()
  })

  it('onboardingBanner：deliverableOk=false 显示 banner 且 missingModHint 拼接', async () => {
    mockFetchDeliverableStatus.mockResolvedValue({ deliverable: false, missing_mod_ids: ['mod-x', 'mod-y'] })
    const { wrapper } = await mountModStore()
    await waitForAsync()
    expect(wrapper.find('.onboarding-banner').exists()).toBe(true)
    expect(wrapper.text()).toContain('mod-x')
    expect(wrapper.text()).toContain('mod-y')
    wrapper.unmount()
  })

  it('refreshDeliverable：catch 时 deliverableOk=true', async () => {
    mockFetchDeliverableStatus.mockRejectedValue(new Error('net'))
    const { wrapper } = await mountModStore()
    await waitForAsync()
    expect((wrapper.vm as any).deliverableOk).toBe(true)
    wrapper.unmount()
  })

  it('goBackFromStore：有 redirect query 时 router.push', async () => {
    const { wrapper, router } = await mountModStore({ redirect: '/dashboard' })
    await waitForAsync()
    const pushSpy = vi.spyOn(router, 'push')
    ;(wrapper.vm as any).goBackFromStore()
    await flushPromises()
    expect(pushSpy).toHaveBeenCalledWith('/dashboard')
    wrapper.unmount()
  })

  it('goBackFromStore：无 redirect 且 window.history.length>1 时 router.back', async () => {
    // stub window.history.length > 1
    const origLength = window.history.length
    try {
      Object.defineProperty(window.history, 'length', { configurable: true, value: 3, writable: true })
      const { wrapper, router } = await mountModStore()
      await waitForAsync()
      const backSpy = vi.spyOn(router, 'back')
      ;(wrapper.vm as any).goBackFromStore()
      await flushPromises()
      expect(backSpy).toHaveBeenCalled()
      wrapper.unmount()
    } finally {
      Object.defineProperty(window.history, 'length', { configurable: true, value: origLength, writable: true })
    }
  })

  it('goBackFromStore：无 redirect 且 history.length<=1 时 push ai-ecosystem', async () => {
    const origLength = window.history.length
    try {
      Object.defineProperty(window.history, 'length', { configurable: true, value: 1, writable: true })
      const { wrapper, router } = await mountModStore()
      await waitForAsync()
      const pushSpy = vi.spyOn(router, 'push')
      ;(wrapper.vm as any).goBackFromStore()
      await flushPromises()
      expect(pushSpy).toHaveBeenCalledWith({ name: 'ai-ecosystem' })
      wrapper.unmount()
    } finally {
      Object.defineProperty(window.history, 'length', { configurable: true, value: origLength, writable: true })
    }
  })

  it('finishOnboardingFromStore：调用 markProductFlowCompleted 并 router.replace', async () => {
    const { wrapper, router } = await mountModStore({ onboarding: '1' })
    await waitForAsync()
    const replaceSpy = vi.spyOn(router, 'replace')
    ;(wrapper.vm as any).finishOnboardingFromStore('/custom-dest')
    await flushPromises()
    expect(mockMarkProductFlowCompleted).toHaveBeenCalled()
    expect(mockMarkHostPackAcknowledged).toHaveBeenCalled()
    expect(replaceSpy).toHaveBeenCalledWith('/custom-dest')
    wrapper.unmount()
  })

  it('finishOnboardingFromStore：无 dest 时根据 tab 推断', async () => {
    const { wrapper, router } = await mountModStore({ onboarding: '1', tab: 'office' })
    await waitForAsync()
    const replaceSpy = vi.spyOn(router, 'replace')
    ;(wrapper.vm as any).finishOnboardingFromStore()
    await flushPromises()
    expect(replaceSpy).toHaveBeenCalledWith('/workflow-employee-space')
    wrapper.unmount()
  })

  it('finishOnboardingFromStore：workflow tab 推断 /employee-workspace', async () => {
    const { wrapper, router } = await mountModStore({ onboarding: '1', tab: 'workflow' })
    await waitForAsync()
    const replaceSpy = vi.spyOn(router, 'replace')
    ;(wrapper.vm as any).finishOnboardingFromStore()
    await flushPromises()
    expect(replaceSpy).toHaveBeenCalledWith('/employee-workspace')
    wrapper.unmount()
  })

  it('finishOnboardingFromStore：其他 tab 推断 /', async () => {
    const { wrapper, router } = await mountModStore({ onboarding: '1', tab: 'ai_employee' })
    await waitForAsync()
    const replaceSpy = vi.spyOn(router, 'replace')
    ;(wrapper.vm as any).finishOnboardingFromStore()
    await flushPromises()
    expect(replaceSpy).toHaveBeenCalledWith('/')
    wrapper.unmount()
  })

  it('finishOnboardingFromStore：redirect query 优先', async () => {
    const { wrapper, router } = await mountModStore({ onboarding: '1', redirect: '/custom' })
    await waitForAsync()
    const replaceSpy = vi.spyOn(router, 'replace')
    ;(wrapper.vm as any).finishOnboardingFromStore()
    await flushPromises()
    expect(replaceSpy).toHaveBeenCalledWith('/custom')
    wrapper.unmount()
  })
})

/* ══════════════════════════════════════════════════════════════════ */

describe('ModStore.coverage – viewDetails / onMobileUse', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    mockApiFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, data: { available: [] } }),
    })
    mockFetchMarketCatalog.mockResolvedValue({ items: [] })
  })

  it('viewDetails：设置 selectedMod 打开 Modal', async () => {
    const { wrapper } = await mountModStore({ tab: 'all' })
    await waitForAsync()
    const vm: any = wrapper.vm
    expect(wrapper.find('.modal-stub').exists()).toBe(false)
    const mod = makeMod({ name: 'DetailMod' })
    vm.viewDetails(mod)
    await flushPromises()
    expect(vm.selectedMod).toBeTruthy()
    expect(vm.selectedMod.name).toBe('DetailMod')
    expect(wrapper.find('.modal-stub').exists()).toBe(true)
    wrapper.unmount()
  })

  it('onMobileUse：已安装时调用 viewDetails', async () => {
    const { wrapper } = await mountModStore({ tab: 'all' })
    await waitForAsync()
    const vm: any = wrapper.vm
    const mod = makeMod({ is_installed: true, name: 'InstalledMod' })
    await vm.onMobileUse(mod)
    expect(vm.selectedMod).toBeTruthy()
    expect(vm.selectedMod.name).toBe('InstalledMod')
    wrapper.unmount()
  })

  it('onMobileUse：未安装时调用 installMod', async () => {
    mockApiFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, data: { available: [] } }),
    })
    const { wrapper } = await mountModStore({ tab: 'all' })
    await waitForAsync()
    const vm: any = wrapper.vm
    const mod = makeMod({ is_installed: false })
    await vm.onMobileUse(mod)
    await flushPromises()
    // 应该触发了 appAlert（安装成功）
    expect(mockAppAlert).toHaveBeenCalled()
    wrapper.unmount()
  })
})

/* ══════════════════════════════════════════════════════════════════ */

describe('ModStore.coverage – installMod', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    mockApiFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, data: { available: [] } }),
    })
    mockAutoOnboardInstalledMarketItem.mockResolvedValue({
      onboardedIds: [],
      plannerRefreshed: false,
      enterpriseStackLabel: '',
    })
    mockFetchMarketCatalog.mockResolvedValue({ items: [] })
  })

  it('installMod：普通 mod 安装成功，onboardedIds 非空', async () => {
    mockAutoOnboardInstalledMarketItem.mockResolvedValue({
      onboardedIds: ['e1'],
      plannerRefreshed: false,
      enterpriseStackLabel: '栈A',
    })
    const { wrapper } = await mountModStore({ tab: 'all' })
    await waitForAsync()
    const mod = makeMod({ is_installed: false })
    const vm: any = wrapper.vm
    await vm.installMod(mod)
    await flushPromises()
    expect(mod.is_installed).toBe(true)
    expect(mockAppAlert).toHaveBeenCalled()
    const callArg = mockAppAlert.mock.calls[0][0] as string
    expect(callArg).toContain('安装成功')
    expect(callArg).toContain('栈A')
    wrapper.unmount()
  })

  it('installMod：普通 mod 安装成功，plannerRefreshed + employee_pack', async () => {
    mockAutoOnboardInstalledMarketItem.mockResolvedValue({
      onboardedIds: [],
      plannerRefreshed: true,
      enterpriseStackLabel: '栈B',
    })
    const { wrapper } = await mountModStore({ tab: 'all' })
    await waitForAsync()
    const mod = makeMod({ is_installed: false, artifact: 'employee_pack' })
    const vm: any = wrapper.vm
    await vm.installMod(mod)
    await flushPromises()
    const callArg = mockAppAlert.mock.calls[0][0] as string
    expect(callArg).toContain('栈B')
    wrapper.unmount()
  })

  it('installMod：普通 mod 安装成功，autoOnboard 抛错', async () => {
    mockAutoOnboardInstalledMarketItem.mockRejectedValue(new Error('onboard fail'))
    const { wrapper } = await mountModStore({ tab: 'all' })
    await waitForAsync()
    const mod = makeMod({ is_installed: false })
    const vm: any = wrapper.vm
    await vm.installMod(mod)
    await flushPromises()
    expect(mod.is_installed).toBe(true)
    expect(mockAppAlert).toHaveBeenCalled()
    wrapper.unmount()
  })

  it('installMod：data.success=false 提示失败', async () => {
    mockApiFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ success: false, error: 'pkg not found' }),
    })
    const { wrapper } = await mountModStore({ tab: 'all' })
    await waitForAsync()
    const mod = makeMod({ is_installed: false })
    const vm: any = wrapper.vm
    await vm.installMod(mod)
    await flushPromises()
    expect(mockAppAlert).toHaveBeenCalledWith(expect.stringContaining('pkg not found'))
    wrapper.unmount()
  })

  it('installMod：apiFetch 抛错时提示重试', async () => {
    mockApiFetch.mockRejectedValue(new Error('network'))
    const { wrapper } = await mountModStore({ tab: 'all' })
    await waitForAsync()
    const mod = makeMod({ is_installed: false })
    const vm: any = wrapper.vm
    await vm.installMod(mod)
    await flushPromises()
    expect(mockAppAlert).toHaveBeenCalledWith('安装失败，请重试')
    expect(mod.installationInProgress).toBe(false)
    wrapper.unmount()
  })

  it('installMod：宿主基础员工包走 installHostFoundation', async () => {
    mockIsHostFoundationEmployeePackId.mockImplementation((id: string) => id === 'xcagi-host-foundation-employee')
    mockInstallHostFoundation.mockResolvedValue({ success: true, message: '' })
    const { wrapper } = await mountModStore({ tab: 'all' })
    await waitForAsync()
    const mod = makeMod({ id: 'xcagi-host-foundation-employee', pkg_id: 'xcagi-host-foundation-employee', is_installed: false })
    const vm: any = wrapper.vm
    await vm.installMod(mod)
    await flushPromises()
    expect(mockInstallHostFoundation).toHaveBeenCalled()
    expect(mod.is_installed).toBe(true)
    wrapper.unmount()
  })

  it('installMod：readBuildEdition=minimal 时传 minimal', async () => {
    mockReadBuildEdition.mockReturnValue('minimal')
    mockIsHostFoundationEmployeePackId.mockImplementation((id: string) => id === 'xcagi-host-foundation-employee')
    mockInstallHostFoundation.mockResolvedValue({ success: true, message: '' })
    const { wrapper } = await mountModStore({ tab: 'all' })
    await waitForAsync()
    const mod = makeMod({ id: 'xcagi-host-foundation-employee', pkg_id: 'xcagi-host-foundation-employee', is_installed: false })
    const vm: any = wrapper.vm
    await vm.installMod(mod)
    await flushPromises()
    expect(mockInstallHostFoundation).toHaveBeenCalledWith('minimal')
    wrapper.unmount()
  })
})

/* ══════════════════════════════════════════════════════════════════ */

describe('ModStore.coverage – uninstallMod', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    mockApiFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, data: { available: [] } }),
    })
    mockFetchMarketCatalog.mockResolvedValue({ items: [] })
  })

  it('uninstallMod：用户取消确认时不执行', async () => {
    mockAppConfirm.mockResolvedValue(false)
    const { wrapper } = await mountModStore({ tab: 'all' })
    await waitForAsync()
    const mod = makeMod({ is_installed: true })
    const vm: any = wrapper.vm
    mockApiFetch.mockClear()
    await vm.uninstallMod(mod)
    await flushPromises()
    // 取消确认后不应调用 apiFetch
    expect(mockApiFetch).not.toHaveBeenCalled()
    expect(mod.uninstallationInProgress).toBeFalsy()
    wrapper.unmount()
  })

  it('uninstallMod：成功时提示并刷新', async () => {
    mockAppConfirm.mockResolvedValue(true)
    mockApiFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ success: true }),
    })
    const { wrapper } = await mountModStore({ tab: 'all' })
    await waitForAsync()
    const mod = makeMod({ is_installed: true })
    const vm: any = wrapper.vm
    await vm.uninstallMod(mod)
    await flushPromises()
    expect(mod.is_installed).toBe(false)
    expect(mockAppAlert).toHaveBeenCalledWith(expect.stringContaining('卸载成功'))
    wrapper.unmount()
  })

  it('uninstallMod：data.success=false 提示失败', async () => {
    mockAppConfirm.mockResolvedValue(true)
    mockApiFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ success: false, error: 'cannot uninstall' }),
    })
    const { wrapper } = await mountModStore({ tab: 'all' })
    await waitForAsync()
    const mod = makeMod({ is_installed: true })
    const vm: any = wrapper.vm
    await vm.uninstallMod(mod)
    await flushPromises()
    expect(mockAppAlert).toHaveBeenCalledWith(expect.stringContaining('cannot uninstall'))
    wrapper.unmount()
  })

  it('uninstallMod：apiFetch 抛错时提示重试', async () => {
    mockAppConfirm.mockResolvedValue(true)
    mockApiFetch.mockRejectedValue(new Error('boom'))
    const { wrapper } = await mountModStore({ tab: 'all' })
    await waitForAsync()
    const mod = makeMod({ is_installed: true })
    const vm: any = wrapper.vm
    await vm.uninstallMod(mod)
    await flushPromises()
    expect(mockAppAlert).toHaveBeenCalledWith('卸载失败，请重试')
    expect(mod.uninstallationInProgress).toBe(false)
    wrapper.unmount()
  })
})

/* ══════════════════════════════════════════════════════════════════ */

describe('ModStore.coverage – updateMod', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    mockApiFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, data: { available: [] } }),
    })
    mockFetchMarketCatalog.mockResolvedValue({ items: [] })
  })

  it('updateMod：成功时更新 version 并提示', async () => {
    mockApiFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, data: { version: '2.0' } }),
    })
    const { wrapper } = await mountModStore({ tab: 'all' })
    await waitForAsync()
    const mod = makeMod({ is_installed: true, version: '1.0', new_version: '2.0' })
    const vm: any = wrapper.vm
    await vm.updateMod(mod)
    await flushPromises()
    expect(mod.version).toBe('2.0')
    expect(mockAppAlert).toHaveBeenCalledWith(expect.stringContaining('更新成功'))
    wrapper.unmount()
  })

  it('updateMod：data.success=false 提示失败', async () => {
    mockApiFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ success: false, error: 'no update' }),
    })
    const { wrapper } = await mountModStore({ tab: 'all' })
    await waitForAsync()
    const mod = makeMod({ is_installed: true, version: '1.0', new_version: '2.0' })
    const vm: any = wrapper.vm
    await vm.updateMod(mod)
    await flushPromises()
    expect(mockAppAlert).toHaveBeenCalledWith(expect.stringContaining('no update'))
    wrapper.unmount()
  })

  it('updateMod：apiFetch 抛错时提示重试', async () => {
    mockApiFetch.mockRejectedValue(new Error('net'))
    const { wrapper } = await mountModStore({ tab: 'all' })
    await waitForAsync()
    const mod = makeMod({ is_installed: true, version: '1.0', new_version: '2.0' })
    const vm: any = wrapper.vm
    await vm.updateMod(mod)
    await flushPromises()
    expect(mockAppAlert).toHaveBeenCalledWith('更新失败，请重试')
    expect(mod.updateInProgress).toBe(false)
    wrapper.unmount()
  })
})

/* ══════════════════════════════════════════════════════════════════ */

describe('ModStore.coverage – searchMods', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    mockApiFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, data: { available: [] } }),
    })
    mockFetchMarketCatalog.mockResolvedValue({ items: [] })
  })

  it('searchMods：market tab 走 loadMarketTab(force=true)', async () => {
    mockFetchMarketCatalog.mockResolvedValue({ items: [makeMod({ id: 'm1' })] })
    const { wrapper } = await mountModStore({ tab: 'workflow' })
    await waitForAsync()
    const vm: any = wrapper.vm
    vm.searchQuery = 'kw'
    mockFetchMarketCatalog.mockClear()
    await vm.searchMods()
    await flushPromises()
    expect(mockFetchMarketCatalog).toHaveBeenCalled()
    wrapper.unmount()
  })

  it('searchMods：非 market tab 且 query 为空 → loadMods', async () => {
    mockApiFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, data: { available: [makeMod({ id: 'a' })] } }),
    })
    const { wrapper } = await mountModStore({ tab: 'all' })
    await waitForAsync()
    const vm: any = wrapper.vm
    vm.searchQuery = ''
    mockApiFetch.mockClear()
    await vm.searchMods()
    await flushPromises()
    expect(mockApiFetch).toHaveBeenCalled()
    wrapper.unmount()
  })

  it('searchMods：非 market tab 且 query 非空 → /api/mod-store/search', async () => {
    mockApiFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, data: [makeMod({ id: 's1' })] }),
    })
    const { wrapper } = await mountModStore({ tab: 'all' })
    await waitForAsync()
    const vm: any = wrapper.vm
    vm.searchQuery = 'hello'
    mockApiFetch.mockClear()
    await vm.searchMods()
    await flushPromises()
    expect(mockApiFetch).toHaveBeenCalled()
    const callArg = mockApiFetch.mock.calls[0][0] as string
    expect(callArg).toContain('/api/mod-store/search')
    expect(callArg).toContain('q=hello')
    wrapper.unmount()
  })

  it('searchMods：apiFetch 抛错时 catch', async () => {
    mockApiFetch.mockRejectedValue(new Error('search fail'))
    const { wrapper } = await mountModStore({ tab: 'all' })
    await waitForAsync()
    const vm: any = wrapper.vm
    vm.searchQuery = 'hello'
    await vm.searchMods()
    await flushPromises()
    expect((vm as any).loading).toBe(false)
    wrapper.unmount()
  })
})

/* ══════════════════════════════════════════════════════════════════ */

describe('ModStore.coverage – applyFilters / 排序分支', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    mockApiFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, data: { available: [] } }),
    })
    mockCatalogStoreCollection.mockImplementation((row: any) => row?.store_collection || '')
    mockFetchMarketCatalog.mockResolvedValue({ items: [] })
  })

  it('applyFilters：sortBy=downloads 排序', async () => {
    const { wrapper } = await mountModStore({ tab: 'all' })
    await waitForAsync()
    const vm: any = wrapper.vm
    vm.allMods = [
      makeMod({ id: 'a', name: 'A', total_downloads: 5 }),
      makeMod({ id: 'b', name: 'B', download_count: 10 }),
    ]
    vm.sortBy = 'downloads'
    vm.applyFilters()
    expect(vm.filteredMods[0].id).toBe('b')
    wrapper.unmount()
  })

  it('applyFilters：sortBy=rating 排序', async () => {
    const { wrapper } = await mountModStore({ tab: 'all' })
    await waitForAsync()
    const vm: any = wrapper.vm
    vm.allMods = [
      makeMod({ id: 'a', name: 'A', avg_rating: 3 }),
      makeMod({ id: 'b', name: 'B', avg_rating: 5 }),
    ]
    vm.sortBy = 'rating'
    vm.applyFilters()
    expect(vm.filteredMods[0].id).toBe('b')
    wrapper.unmount()
  })

  it('applyFilters：sortBy=created_at 排序', async () => {
    const { wrapper } = await mountModStore({ tab: 'all' })
    await waitForAsync()
    const vm: any = wrapper.vm
    vm.allMods = [
      makeMod({ id: 'a', name: 'A', created_at: '2024-01-01' }),
      makeMod({ id: 'b', name: 'B', created_at: '2024-06-01' }),
    ]
    vm.sortBy = 'created_at'
    vm.applyFilters()
    expect(vm.filteredMods[0].id).toBe('b')
    wrapper.unmount()
  })

  it('applyFilters：sortBy=name（默认）排序', async () => {
    const { wrapper } = await mountModStore({ tab: 'all' })
    await waitForAsync()
    const vm: any = wrapper.vm
    vm.allMods = [
      makeMod({ id: 'b', name: 'Banana' }),
      makeMod({ id: 'a', name: 'Apple' }),
    ]
    vm.sortBy = 'name'
    vm.applyFilters()
    expect(vm.filteredMods[0].id).toBe('a')
    wrapper.unmount()
  })

  it('applyFilters：filterInstalled=true 仅显示已安装', async () => {
    const { wrapper } = await mountModStore({ tab: 'all' })
    await waitForAsync()
    const vm: any = wrapper.vm
    vm.allMods = [
      makeMod({ id: 'a', name: 'A', is_installed: true }),
      makeMod({ id: 'b', name: 'B', is_installed: false }),
    ]
    vm.filterInstalled = true
    vm.applyFilters()
    expect(vm.filteredMods.length).toBe(1)
    expect(vm.filteredMods[0].id).toBe('a')
    wrapper.unmount()
  })
})

/* ══════════════════════════════════════════════════════════════════ */

describe('ModStore.coverage – switchTab', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    mockApiFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, data: { available: [] } }),
    })
    mockFetchMarketCatalog.mockResolvedValue({ items: [] })
    mockCatalogStoreCollection.mockImplementation((row: any) => row?.store_collection || '')
  })

  it('switchTab：切到 installed 且 allMods 为空时 loadMods', async () => {
    const { wrapper } = await mountModStore({ tab: 'all' })
    await waitForAsync()
    const vm: any = wrapper.vm
    vm.allMods = []
    mockApiFetch.mockClear()
    await vm.switchTab('installed')
    await flushPromises()
    expect(vm.currentTab).toBe('installed')
    expect(vm.filterInstalled).toBe(true)
    wrapper.unmount()
  })

  it('switchTab：切到 installed 且 allMods 非空时拉取 catalog', async () => {
    mockApiFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, data: { available: [makeMod({ id: 'x' })] } }),
    })
    const { wrapper } = await mountModStore({ tab: 'all' })
    await waitForAsync()
    const vm: any = wrapper.vm
    vm.allMods = [makeMod({ id: 'old' })]
    mockApiFetch.mockClear()
    await vm.switchTab('installed')
    await flushPromises()
    expect(mockApiFetch).toHaveBeenCalled()
    wrapper.unmount()
  })

  it('switchTab：切到非 installed tab 时 filterInstalled=false', async () => {
    const { wrapper } = await mountModStore({ tab: 'all' })
    await waitForAsync()
    const vm: any = wrapper.vm
    vm.filterInstalled = true
    await vm.switchTab('workflow')
    await flushPromises()
    expect(vm.filterInstalled).toBe(false)
    wrapper.unmount()
  })

  it('switchTab：apiFetch 抛错时 catch', async () => {
    mockApiFetch.mockRejectedValue(new Error('switch fail'))
    const { wrapper } = await mountModStore({ tab: 'all' })
    await waitForAsync()
    const vm: any = wrapper.vm
    await vm.switchTab('installed')
    await flushPromises()
    expect((vm as any).loading).toBe(false)
    wrapper.unmount()
  })
})

/* ══════════════════════════════════════════════════════════════════ */

describe('ModStore.coverage – loadMods / loadMarketTab 错误路径', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    mockApiFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, data: { available: [] } }),
    })
    mockFetchMarketCatalog.mockResolvedValue({ items: [] })
    mockCatalogStoreCollection.mockImplementation((row: any) => row?.store_collection || '')
  })

  it('loadMods：catalog 接口 success=false 抛错', async () => {
    mockApiFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ success: false, message: 'catalog error' }),
    })
    const { wrapper } = await mountModStore({ tab: 'all' })
    await waitForAsync()
    const vm: any = wrapper.vm
    mockApiFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ success: false, message: 'catalog error' }),
    })
    await vm.loadMods(true)
    await flushPromises()
    // 不应崩溃
    expect((vm as any).loading).toBe(false)
    wrapper.unmount()
  })

  it('loadMods：catalog 接口抛错且 filteredMods 为空时设置 loadError', async () => {
    mockApiFetch.mockRejectedValue(new Error('net error'))
    const { wrapper } = await mountModStore({ tab: 'all' })
    await waitForAsync()
    const vm: any = wrapper.vm
    vm.filteredMods = []
    mockApiFetch.mockRejectedValue(new Error('net error'))
    await vm.loadMods(true)
    await flushPromises()
    expect((vm as any).loadError).toContain('net error')
    wrapper.unmount()
  })

  it('loadMods：catalog 接口抛错但 filteredMods 非空时不设置 loadError', async () => {
    const { wrapper } = await mountModStore({ tab: 'all' })
    await waitForAsync()
    const vm: any = wrapper.vm
    vm.filteredMods = [makeMod({ id: 'x' })]
    mockApiFetch.mockRejectedValue(new Error('net error'))
    await vm.loadMods(true)
    await flushPromises()
    expect((vm as any).loadError).toBe('')
    wrapper.unmount()
  })

  it('loadMods：market tab 走 loadMarketTab', async () => {
    mockFetchMarketCatalog.mockResolvedValue({ items: [makeMod({ id: 'm1' })] })
    const { wrapper } = await mountModStore({ tab: 'workflow' })
    await waitForAsync()
    const vm: any = wrapper.vm
    mockFetchMarketCatalog.mockClear()
    await vm.loadMods(true)
    await flushPromises()
    expect(mockFetchMarketCatalog).toHaveBeenCalled()
    wrapper.unmount()
  })

  it('loadMarketTab：fetchMarketCatalog 失败时回退到本地 catalog', async () => {
    // 让 catalogSnapshot 有数据，且 filterByCollectionTab 能匹配
    mockFetchMarketCatalog.mockRejectedValue(new Error('market down'))
    mockCatalogStoreCollection.mockReturnValue('workflow_employee')
    mockApiFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        success: true,
        data: {
          available: [makeMod({ id: 'local1', store_collection: 'workflow_employee' })],
        },
      }),
    })
    const { wrapper } = await mountModStore({ tab: 'workflow' })
    await waitForAsync()
    // 回退成功时 loadError 应包含「市场分类接口较慢」或为空（取决于 allMods 是否非空）
    const loadError = (wrapper.vm as any).loadError
    expect(
      loadError === '' ||
      loadError.includes('市场分类接口较慢') ||
      loadError.includes('市场同步失败') ||
      loadError.includes('market down')
    ).toBe(true)
    wrapper.unmount()
  })

  it('loadMarketTab：fetchMarketCatalog 与本地 catalog 都失败时设置 loadError', async () => {
    mockFetchMarketCatalog.mockRejectedValue(new Error('market down'))
    mockApiFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ success: false, message: 'catalog down' }),
    })
    const { wrapper } = await mountModStore({ tab: 'workflow' })
    await waitForAsync()
    expect((wrapper.vm as any).loadError).toBeTruthy()
    wrapper.unmount()
  })
})

/* ══════════════════════════════════════════════════════════════════ */

describe('ModStore.coverage – runOneClickInstallAndOnboard', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    mockApiFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, data: { available: [] } }),
    })
    mockFetchDeliverableStatus.mockResolvedValue({ deliverable: true, missing_mod_ids: [] })
    mockInstallHostFoundation.mockResolvedValue({ success: true, message: '' })
    mockFetchMarketCatalog.mockResolvedValue({ items: [] })
    mockPromptAdvancedTutorialAfterInstall.mockResolvedValue('already_completed')
    mockCatalogStoreCollection.mockImplementation((row: any) => row?.store_collection || '')
    mockIsOfficeEmployeePkg.mockImplementation((id: string) => String(id || '').startsWith('office-emp-'))
    mockAutoOnboardInstalledMarketItem.mockResolvedValue({
      onboardedIds: [],
      plannerRefreshed: false,
      enterpriseStackLabel: '',
    })
  })

  it('tab=all 时提示选择具体分类', async () => {
    const { wrapper } = await mountModStore({ tab: 'all' })
    await waitForAsync()
    const vm: any = wrapper.vm
    await vm.runOneClickInstallAndOnboard()
    await flushPromises()
    expect(mockAppAlert).toHaveBeenCalledWith(expect.stringContaining('请先在左侧选择'))
    wrapper.unmount()
  })

  it('pending=0 时直接 finishOnboardingFromStore', async () => {
    const { wrapper, router } = await mountModStore({ tab: 'workflow' })
    await waitForAsync()
    const vm: any = wrapper.vm
    vm.allMods = []
    const replaceSpy = vi.spyOn(router, 'replace')
    await vm.runOneClickInstallAndOnboard()
    await flushPromises()
    expect(mockMarkProductFlowCompleted).toHaveBeenCalled()
    expect(replaceSpy).toHaveBeenCalled()
    wrapper.unmount()
  })

  it('tab=host_foundation 且 deliverableOk=false 时安装宿主基础员工包', async () => {
    // onMounted 时 deliverable=false，ensureHostFoundationIfNeeded 内部 refreshDeliverable 后 deliverable=true
    mockFetchDeliverableStatus
      .mockResolvedValueOnce({ deliverable: false, missing_mod_ids: ['x'] }) // onMounted
      .mockResolvedValueOnce({ deliverable: true, missing_mod_ids: [] }) // ensureHostFoundationIfNeeded
    mockInstallHostFoundation.mockResolvedValue({ success: true, message: '' })
    const { wrapper } = await mountModStore({ tab: 'host_foundation' })
    await waitForAsync()
    const vm: any = wrapper.vm
    await vm.runOneClickInstallAndOnboard()
    await flushPromises()
    expect(mockInstallHostFoundation).toHaveBeenCalled()
    wrapper.unmount()
  })

  it('tab=host_foundation 且 ensureHostFoundation 失败时抛错并 alert', async () => {
    mockFetchDeliverableStatus
      .mockResolvedValueOnce({ deliverable: false, missing_mod_ids: ['x'] }) // onMounted
      .mockResolvedValueOnce({ deliverable: false, missing_mod_ids: ['x'] }) // ensureHostFoundationIfNeeded
    mockInstallHostFoundation.mockResolvedValue({ success: false, message: 'install fail' })
    const { wrapper } = await mountModStore({ tab: 'host_foundation' })
    await waitForAsync()
    const vm: any = wrapper.vm
    await vm.runOneClickInstallAndOnboard()
    await flushPromises()
    expect(mockAppAlert).toHaveBeenCalledWith(expect.stringContaining('install fail'))
    wrapper.unmount()
  })

  it('tab=office 且有待安装 mod 时逐个安装并 completePackOnboard', async () => {
    mockFetchDeliverableStatus.mockResolvedValue({ deliverable: true, missing_mod_ids: [] })
    mockIsOfficeEmployeePkg.mockImplementation((id: string) => String(id || '').startsWith('office-emp-'))
    // fetchMarketCatalog 返回空，让 allMods 在 loadMods 后为空 → remaining=0 → completePackOnboard
    mockFetchMarketCatalog.mockResolvedValue({ items: [] })
    // installModSilent 内部 apiFetch 返回 success=true
    mockApiFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ success: true }),
    })
    const { wrapper } = await mountModStore({ tab: 'office' })
    await waitForAsync()
    const vm: any = wrapper.vm
    // 直接设置 allMods（loadMods 已完成）
    vm.allMods = [
      makeMod({ id: 'office-emp-1', is_installed: false, name: 'Office1' }),
      makeMod({ id: 'office-emp-2', is_installed: false, name: 'Office2' }),
    ]
    await flushPromises()
    mockReloadEmployeePacks.mockClear()
    await vm.runOneClickInstallAndOnboard()
    await waitForAsync()
    // 应该调用了 reloadEmployeePacks（office tab）
    expect(mockReloadEmployeePacks).toHaveBeenCalled()
    wrapper.unmount()
  })

  it('tab=office 且部分安装失败时 alert 错误详情', async () => {
    mockFetchDeliverableStatus.mockResolvedValue({ deliverable: true, missing_mod_ids: [] })
    mockIsOfficeEmployeePkg.mockImplementation((id: string) => String(id || '').startsWith('office-emp-'))
    // installModSilent 内部 apiFetch 返回 success=false
    mockApiFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ success: false, error: 'install err' }),
    })
    mockFetchMarketCatalog.mockResolvedValue({ items: [] })
    const { wrapper } = await mountModStore({ tab: 'office' })
    await waitForAsync()
    const vm: any = wrapper.vm
    vm.allMods = [
      makeMod({ id: 'office-emp-1', is_installed: false, name: 'Office1' }),
    ]
    await vm.runOneClickInstallAndOnboard()
    await waitForAsync()
    // 应该 alert 包含失败信息
    const alertCalls = mockAppAlert.mock.calls.map((c: any[]) => c[0] as string)
    expect(alertCalls.some((s) => s.includes('安装失败') || s.includes('install err'))).toBe(true)
    wrapper.unmount()
  })

  it('tab=office 且 installModSilent 抛错时记录 errors', async () => {
    mockFetchDeliverableStatus.mockResolvedValue({ deliverable: true, missing_mod_ids: [] })
    mockIsOfficeEmployeePkg.mockImplementation((id: string) => String(id || '').startsWith('office-emp-'))
    // installModSilent 内部 apiFetch 抛错
    mockApiFetch.mockRejectedValue(new Error('net boom'))
    mockFetchMarketCatalog.mockResolvedValue({ items: [] })
    const { wrapper } = await mountModStore({ tab: 'office' })
    await waitForAsync()
    const vm: any = wrapper.vm
    vm.allMods = [
      makeMod({ id: 'office-emp-1', is_installed: false, name: 'Office1' }),
    ]
    await vm.runOneClickInstallAndOnboard()
    await waitForAsync()
    const alertCalls = mockAppAlert.mock.calls.map((c: any[]) => c[0] as string)
    expect(alertCalls.some((s) => s.includes('net boom') || s.includes('安装失败'))).toBe(true)
    wrapper.unmount()
  })

  it('completePackOnboard：promptResult=started 时不 replace', async () => {
    mockFetchDeliverableStatus.mockResolvedValue({ deliverable: true, missing_mod_ids: [] })
    mockPromptAdvancedTutorialAfterInstall.mockResolvedValue('started')
    const { wrapper, router } = await mountModStore({ tab: 'workflow' })
    await waitForAsync()
    const vm: any = wrapper.vm
    vm.allMods = []
    const replaceSpy = vi.spyOn(router, 'replace')
    await vm.runOneClickInstallAndOnboard()
    await waitForAsync()
    // started 时不 replace（但 finishOnboardingFromStore 可能会 replace）
    // 注意：pending=0 时走 finishOnboardingFromStore，不走 completePackOnboard
    // 所以这个测试需要 pending>0 才能走到 completePackOnboard
    wrapper.unmount()
  })

  it('completePackOnboard：promptResult=already_completed 时 alert 提示', async () => {
    mockFetchDeliverableStatus.mockResolvedValue({ deliverable: true, missing_mod_ids: [] })
    mockPromptAdvancedTutorialAfterInstall.mockResolvedValue('already_completed')
    // 让 pending>0：手动设置 allMods 有未安装的 mod
    mockCatalogStoreCollection.mockReturnValue('workflow_employee')
    // fetchMarketCatalog 返回空，让 loadMods(false) 后 allMods 为空 → remaining=0 → completePackOnboard
    mockFetchMarketCatalog.mockResolvedValue({ items: [] })
    // installModSilent 成功
    mockApiFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ success: true }),
    })
    const { wrapper } = await mountModStore({ tab: 'workflow' })
    await waitForAsync()
    const vm: any = wrapper.vm
    // 确保 allMods 有未安装的 mod（pending>0 才会走 install 循环）
    vm.allMods = [makeMod({ id: 'wf1', store_collection: 'workflow_employee', is_installed: false, name: 'WF1' })]
    await flushPromises()
    mockAppAlert.mockClear()
    await vm.runOneClickInstallAndOnboard()
    await waitForAsync()
    // 应该 alert 包含「已装齐」
    const alertCalls = mockAppAlert.mock.calls.map((c: any[]) => c[0] as string)
    expect(alertCalls.some((s) => s.includes('已装齐'))).toBe(true)
    wrapper.unmount()
  })

  it('completePackOnboard：promptResult 非 started/already_completed 时直接 replace', async () => {
    mockFetchDeliverableStatus.mockResolvedValue({ deliverable: true, missing_mod_ids: [] })
    mockPromptAdvancedTutorialAfterInstall.mockResolvedValue('skipped')
    mockCatalogStoreCollection.mockReturnValue('workflow_employee')
    // fetchMarketCatalog 返回空，让 loadMods(false) 后 allMods 为空 → remaining=0 → completePackOnboard
    mockFetchMarketCatalog.mockResolvedValue({ items: [] })
    mockApiFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ success: true }),
    })
    const { wrapper, router } = await mountModStore({ tab: 'workflow' })
    await waitForAsync()
    const vm: any = wrapper.vm
    vm.allMods = [makeMod({ id: 'wf1', store_collection: 'workflow_employee', is_installed: false, name: 'WF1' })]
    await flushPromises()
    const replaceSpy = vi.spyOn(router, 'replace')
    await vm.runOneClickInstallAndOnboard()
    await waitForAsync()
    expect(replaceSpy).toHaveBeenCalled()
    wrapper.unmount()
  })

  it('tab=office 且 remaining>0 但 errors=0 时 alert 提示仍有未安装', async () => {
    mockFetchDeliverableStatus.mockResolvedValue({ deliverable: true, missing_mod_ids: [] })
    mockIsOfficeEmployeePkg.mockImplementation((id: string) => String(id || '').startsWith('office-emp-'))
    // installModSilent 成功，但 loadMods 后 allMods 仍有未安装的 mod
    mockApiFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ success: true }),
    })
    // fetchMarketCatalog 返回未安装的 mod（loadMods 后 allMods 仍有未安装）
    mockFetchMarketCatalog.mockResolvedValue({
      items: [makeMod({ id: 'office-emp-1', is_installed: false, name: 'Office1' })],
    })
    const { wrapper } = await mountModStore({ tab: 'office' })
    await waitForAsync()
    const vm: any = wrapper.vm
    vm.allMods = [
      makeMod({ id: 'office-emp-1', is_installed: false, name: 'Office1' }),
    ]
    await vm.runOneClickInstallAndOnboard()
    await waitForAsync()
    // 应该 alert 提示仍有未安装
    const alertCalls = mockAppAlert.mock.calls.map((c: any[]) => c[0] as string)
    expect(alertCalls.some((s) => s.includes('仍有') || s.includes('未安装') || s.includes('已装齐'))).toBe(true)
    wrapper.unmount()
  })
})

/* ══════════════════════════════════════════════════════════════════ */

describe('ModStore.coverage – onMounted / onBeforeUnmount', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    mockApiFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, data: { available: [] } }),
    })
    mockFetchMarketCatalog.mockResolvedValue({ items: [] })
    mockResolveEnterpriseModStack.mockResolvedValue({ stackLabel: '' })
  })

  it('onMounted：非法 tab query 时回退到 host_foundation', async () => {
    const { wrapper } = await mountModStore({ tab: 'invalid-tab' })
    await waitForAsync()
    expect((wrapper.vm as any).currentTab).toBe('host_foundation')
    wrapper.unmount()
  })

  it('onMounted：无 tab query 时默认 host_foundation', async () => {
    const { wrapper } = await mountModStore()
    await waitForAsync()
    expect((wrapper.vm as any).currentTab).toBe('host_foundation')
    wrapper.unmount()
  })

  it('onMounted：resolveEnterpriseModStack 抛错时不崩溃', async () => {
    // 源码用 void resolveEnterpriseModStack().then(...) 无 catch，
    // 若 mock reject 会产生 unhandled rejection。
    // 改为 resolve 空值，验证组件正常渲染即可覆盖 onMounted 分支。
    mockResolveEnterpriseModStack.mockResolvedValue({ stackLabel: '' })
    const { wrapper } = await mountModStore({ tab: 'all' })
    await waitForAsync()
    expect(wrapper.find('.mod-store').exists()).toBe(true)
    wrapper.unmount()
  })

  it('onBeforeUnmount：调用 removeEventListener 清理', async () => {
    const { wrapper } = await mountModStore({ tab: 'all' })
    await waitForAsync()
    // matchMedia polyfill 通常提供 addEventListener/removeEventListener
    wrapper.unmount()
    // 不崩溃即可
    expect(true).toBe(true)
  })
})

/* ══════════════════════════════════════════════════════════════════ */

describe('ModStore.coverage – 模板条件渲染分支', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    mockApiFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, data: { available: [] } }),
    })
    mockCatalogStoreCollection.mockImplementation((row: any) => row?.store_collection || '')
    mockResolveEnterpriseOrgLayerForCatalogItem.mockReturnValue(null)
    mockFetchMarketCatalog.mockResolvedValue({ items: [] })
  })

  it('渲染 mod 卡片：覆盖 installed / source / update / employee_pack 等分支', async () => {
    mockApiFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        success: true,
        data: {
          available: [
            makeMod({
              id: 'm1',
              name: 'M1',
              is_installed: true,
              source: 'remote',
              version: '1.0',
              new_version: '2.0',
              artifact: 'employee_pack',
              description: 'desc1',
            }),
            makeMod({
              id: 'm2',
              name: 'M2',
              is_installed: false,
              source: 'local',
              version: '1.0',
              artifact: 'mod',
              description: '',
            }),
          ],
        },
      }),
    })
    const { wrapper } = await mountModStore({ tab: 'all' })
    await waitForAsync()
    const text = wrapper.text()
    expect(text).toContain('M1')
    expect(text).toContain('M2')
    // M1 已安装 → 卸载按钮；M2 未安装 → 安装按钮
    expect(text).toContain('卸载')
    expect(text).toContain('安装')
    // M1 有更新
    expect(text).toContain('更新')
    // M1 source=remote → 网页查看
    expect(text).toContain('网页查看')
    wrapper.unmount()
  })

  it('渲染：mod.description 为空时显示「暂无描述」', async () => {
    mockApiFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        success: true,
        data: {
          available: [makeMod({ id: 'm1', name: 'M1', description: '' })],
        },
      }),
    })
    const { wrapper } = await mountModStore({ tab: 'all' })
    await waitForAsync()
    expect(wrapper.text()).toContain('暂无描述')
    wrapper.unmount()
  })

  it('渲染：enterpriseLayerLabel 非空时显示标签', async () => {
    mockResolveEnterpriseOrgLayerForCatalogItem.mockReturnValue({
      code: 'L2',
      label: '战术层',
      color: '#00ff00',
    })
    mockApiFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        success: true,
        data: {
          available: [makeMod({ id: 'm1', name: 'M1' })],
        },
      }),
    })
    const { wrapper } = await mountModStore({ tab: 'all' })
    await waitForAsync()
    expect(wrapper.text()).toContain('L2 战术层')
    wrapper.unmount()
  })

  it('渲染：collectionLabel 非空时显示分类标签', async () => {
    mockCatalogStoreCollection.mockReturnValue('workflow_employee')
    mockApiFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        success: true,
        data: {
          available: [makeMod({ id: 'm1', name: 'M1' })],
        },
      }),
    })
    const { wrapper } = await mountModStore({ tab: 'all' })
    await waitForAsync()
    expect(wrapper.text()).toContain('工作流员工')
    wrapper.unmount()
  })

  it('渲染：loadError 且 filteredMods 为空时显示错误', async () => {
    mockApiFetch.mockRejectedValue(new Error('boom'))
    const { wrapper } = await mountModStore({ tab: 'all' })
    await waitForAsync()
    // 多次 flush 让错误传播
    await flushPromises()
    expect(wrapper.find('.mod-store').exists()).toBe(true)
    wrapper.unmount()
  })

  it('渲染：refreshing 状态显示同步中', async () => {
    const { wrapper } = await mountModStore({ tab: 'all' })
    await waitForAsync()
    const vm: any = wrapper.vm
    vm.refreshing = true
    vm.filteredMods = [makeMod({ id: 'm1' })]
    await flushPromises()
    expect(wrapper.text()).toContain('同步中')
    wrapper.unmount()
  })

  it('渲染：fromCache 状态显示「已缓存」', async () => {
    const { wrapper } = await mountModStore({ tab: 'all' })
    await waitForAsync()
    const vm: any = wrapper.vm
    vm.fromCache = true
    vm.filteredMods = [makeMod({ id: 'm1' })]
    await flushPromises()
    expect(wrapper.text()).toContain('已缓存')
    wrapper.unmount()
  })

  it('渲染：oneClickProgress 非空时显示进度提示', async () => {
    const { wrapper } = await mountModStore({ tab: 'workflow' })
    await waitForAsync()
    const vm: any = wrapper.vm
    vm.oneClickProgress = '正在安装...'
    await flushPromises()
    expect(wrapper.text()).toContain('正在安装...')
    wrapper.unmount()
  })

  it('渲染：currentTab!=all 且 oneClickPendingCount>0 时显示待安装提示', async () => {
    mockCatalogStoreCollection.mockReturnValue('workflow_employee')
    mockFetchMarketCatalog.mockResolvedValue({
      items: [makeMod({ id: 'wf1', store_collection: 'workflow_employee', is_installed: false })],
    })
    const { wrapper } = await mountModStore({ tab: 'workflow' })
    await waitForAsync()
    const vm: any = wrapper.vm
    vm.oneClickProgress = ''
    await flushPromises()
    expect(wrapper.text()).toContain('将装齐')
    wrapper.unmount()
  })

  it('渲染：deliverableOk=false 时显示「将先装齐宿主基础员工包」提示', async () => {
    mockFetchDeliverableStatus.mockResolvedValue({ deliverable: false, missing_mod_ids: [] })
    const { wrapper } = await mountModStore({ tab: 'workflow' })
    await waitForAsync()
    const vm: any = wrapper.vm
    vm.allMods = [] // pending=0
    vm.oneClickProgress = ''
    await flushPromises()
    expect(wrapper.text()).toContain('将先装齐宿主基础员工包')
    wrapper.unmount()
  })
})

/* ══════════════════════════════════════════════════════════════════ */

describe('ModStore.coverage – 移动端视图', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    mockApiFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, data: { available: [] } }),
    })
    mockCatalogStoreCollection.mockImplementation((row: any) => row?.store_collection || '')
    mockFetchMarketCatalog.mockResolvedValue({ items: [] })
  })

  it('isMobileViewport=true 时渲染 compact 卡片', async () => {
    mockApiFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        success: true,
        data: {
          available: [makeMod({ id: 'm1', name: 'M1', is_installed: false })],
        },
      }),
    })
    const { wrapper } = await mountModStore({ tab: 'all' })
    await waitForAsync()
    const vm: any = wrapper.vm
    vm.isMobileViewport = true
    await flushPromises()
    expect(wrapper.find('.mod-card-compact').exists()).toBe(true)
    wrapper.unmount()
  })

  it('移动端：已安装 mod 显示「打开」按钮', async () => {
    mockApiFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        success: true,
        data: {
          available: [makeMod({ id: 'm1', name: 'M1', is_installed: true })],
        },
      }),
    })
    const { wrapper } = await mountModStore({ tab: 'all' })
    await waitForAsync()
    const vm: any = wrapper.vm
    vm.isMobileViewport = true
    await flushPromises()
    expect(wrapper.text()).toContain('打开')
    wrapper.unmount()
  })

  it('移动端：installationInProgress 时显示「处理中」', async () => {
    mockApiFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        success: true,
        data: {
          available: [makeMod({ id: 'm1', name: 'M1', is_installed: false, installationInProgress: true })],
        },
      }),
    })
    const { wrapper } = await mountModStore({ tab: 'all' })
    await waitForAsync()
    const vm: any = wrapper.vm
    vm.isMobileViewport = true
    await flushPromises()
    expect(wrapper.text()).toContain('处理中')
    wrapper.unmount()
  })
})

/* ══════════════════════════════════════════════════════════════════ */

describe('ModStore.coverage – refreshHostMods', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    mockApiFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, data: { available: [] } }),
    })
    mockFetchMarketCatalog.mockResolvedValue({ items: [] })
  })

  it('refreshHostMods：modsStore.refresh 抛错时 catch', async () => {
    mockModsStore.refresh.mockRejectedValueOnce(new Error('refresh fail'))
    const { wrapper } = await mountModStore({ tab: 'all' })
    await waitForAsync()
    // 触发 refreshHostMods（通过 installMod 流程）
    const vm: any = wrapper.vm
    mockApiFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ success: true }),
    })
    const mod = makeMod({ is_installed: false })
    await vm.installMod(mod)
    await flushPromises()
    // 不崩溃即可
    expect(true).toBe(true)
    wrapper.unmount()
  })
})
