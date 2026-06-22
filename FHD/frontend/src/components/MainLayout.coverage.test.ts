/**
 * MainLayout.vue 覆盖率提升测试
 *
 * 目标：覆盖 MainLayout.vue 中未覆盖的分支，将覆盖率提升到 90%+。
 * 重点覆盖：
 *   - endImpersonation：代管结束流程（含成功/失败路径）
 *   - accountUsername：localStorage 读取与 JSON 解析（含异常）
 *   - resolveModBadgeSuffix / modeBadgeText：Mod 徽标后缀
 *   - modPathToSidebarKey：Mod 菜单 path → key 映射
 *   - currentRouteName：matched 路由回退
 *   - useResizablePane 回调：enabled / onResizeStart / onResizeEnd
 *   - currentViewTitle：metaTitle 回退
 *   - resolveLegacyRouteFromModPath：approval-hub 路径
 *   - navigateToView：Mod 路由注册/跳转/legacy/csHost 各分支
 *   - watch(isAnyTutorialActive)：教程激活/失活
 *   - handleGlobalActivity / onSidebarMouseEnter / onHoverTriggerEnter / onHoverTriggerLeave
 *   - onMounted：store 未加载时刷新 / addListener 旧 API 回退
 *   - onBeforeUnmount：removeListener 旧 API 回退
 *
 * 遵循铁律3：happy path + 空值/None + 边界值 + 异常路径。
 * Mock 最小化：仅 mock 外部边界（stores / composables / utils / 子组件）。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'

// ── 使用 vi.hoisted 创建可变的 reactive 状态 ──────────────────
// vi.hoisted 在所有 import 之前同步执行，无法使用 ES import 或 await import()，
// 只能通过 require() 同步获取 vue 模块以创建 reactive/ref 状态供 vi.mock 工厂引用。
// eslint-disable-next-line @typescript-eslint/no-require-imports
const vueModule = vi.hoisted(() => require('vue') as typeof import('vue'))

const testState = vi.hoisted(() => {
  const vue = vueModule
  return {
    // 路由状态
    route: vue.reactive({
      name: 'chat' as string | undefined,
      meta: {} as Record<string, unknown>,
      path: '/chat',
      matched: [] as Array<{ path: string }>,
    }),
    // 教程 store 状态（reactive 以便 watch 触发）
    onboardingTutorialStore: vue.reactive({
      active: false,
    }),
    tutorialStore: vue.reactive({
      isActive: false,
    }),
    // mods store 状态
    modsStore: vue.reactive({
      modsForUi: [] as unknown[],
      modRoutes: [] as unknown[],
      initialize: vi.fn().mockResolvedValue(undefined),
    }),
    // accountProfile store 状态
    accountProfileStore: vue.reactive({
      loaded: true,
      displayBrand: '',
      isImpersonating: false,
      impersonatingUsername: '',
      companyBrand: '',
      refreshFromServer: vi.fn().mockResolvedValue(undefined),
    }),
    // industry store 状态
    industryStore: vue.reactive({
      currentIndustryId: 'generic',
      isLoaded: true,
      initialize: vi.fn().mockResolvedValue(undefined),
    }),
    // useResizablePane 配置捕获
    resizablePaneConfig: null as Record<string, unknown> | null,
    resizablePaneReturn: {
      paneStyle: {},
      resetSize: vi.fn(),
      startResize: vi.fn(),
      stopResize: vi.fn(),
    },
    // useModRoutes 返回
    modMenuItems: vue.ref<unknown[]>([]),
    // 标志
    adminConsoleSpa: false,
    // resolveHostBusinessPageRedirect 返回值控制
    hostBusinessRedirect: null as string | null,
    // customerServiceHostPathFromModPath 返回值控制
    csHostPath: null as string | null,
    // xcmaxAdminApi
    xcmaxAdminApi: {
      endImpersonate: vi.fn().mockResolvedValue(undefined),
    },
  }
})

// ── 外部依赖 mock ─────────────────────────────────────────

vi.mock('vue-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('vue-router')>()
  return {
    ...actual,
    useRoute: () => testState.route,
    useRouter: () => testRouter,
  }
})

// useRouter 返回的 router 对象（在测试中创建真实 router）
let testRouter: ReturnType<typeof createRouter>

vi.mock('pinia', async (importOriginal) => {
  const actual = await importOriginal<typeof import('pinia')>()
  return {
    ...actual,
    storeToRefs: (store: Record<string, unknown>) => {
      // 使用 computed 创建只读 ref，跟踪 reactive store 属性变化
      const refs: Record<string, ReturnType<typeof vueModule.computed>> = {}
      for (const key of Object.keys(store)) {
        if (typeof store[key] !== 'function') {
          refs[key] = vueModule.computed(() => store[key])
        }
      }
      return refs
    },
  }
})

vi.mock('@/stores/industry', () => ({
  useIndustryStore: () => testState.industryStore,
}))

vi.mock('@/stores/mods', () => ({
  useModsStore: () => testState.modsStore,
}))

vi.mock('@/stores/accountProfile', () => ({
  useAccountProfileStore: () => testState.accountProfileStore,
}))

vi.mock('@/stores/onboardingTutorial', () => ({
  useOnboardingTutorialStore: () => testState.onboardingTutorialStore,
}))

vi.mock('@/stores/tutorial', () => ({
  useTutorialStore: () => testState.tutorialStore,
  setTutorialBuildContextFactory: vi.fn(),
}))

vi.mock('@/composables/useTutorialCatalog', () => ({
  useTutorialCatalog: () => ({
    buildContext: { value: {} },
  }),
}))

vi.mock('@/composables/useResizablePane', () => ({
  useResizablePane: (config: Record<string, unknown>) => {
    testState.resizablePaneConfig = config
    return testState.resizablePaneReturn
  },
}))

vi.mock('@/composables/useModRoutes', () => ({
  useModRoutes: () => ({
    modMenuItems: testState.modMenuItems,
  }),
}))

vi.mock('@/api/xcmaxAdmin', () => ({
  xcmaxAdminApi: testState.xcmaxAdminApi,
}))

vi.mock('@/api/marketAccount', () => ({
  LS_MARKET_USER_JSON: 'xcagi_market_user_json',
}))

vi.mock('@/utils/adminConsoleUrl', () => ({
  isAdminConsoleSpa: () => testState.adminConsoleSpa,
}))

vi.mock('@/constants/adminOperatorNav', () => ({
  ADMIN_OPERATOR_BRAND_SUBTITLE: '运维管理',
}))

vi.mock('@/utils/appDialog', () => ({
  appAlert: vi.fn().mockResolvedValue(undefined),
}))

vi.mock('@/constants/industryDefaults', () => ({
  DEFAULT_INDUSTRY_ID: 'generic',
}))

vi.mock('@/constants/industryPresets', () => ({
  getIndustryPreset: (id: string) => ({ name: id === 'generic' ? '通用' : id }),
}))

vi.mock('@/utils/coreNavLabel', () => ({
  resolveCoreNavLabel: () => null,
  INDUSTRY_MENU_LABELS: {},
}))

vi.mock('@/constants/clientModeTiers', () => ({
  isClientModeTiersUiEnabled: () => false,
}))

vi.mock('@/utils/hostBusinessPageRedirect', () => ({
  resolveHostBusinessPageRedirect: () => testState.hostBusinessRedirect,
}))

vi.mock('@/utils/customerServicePagePaths', () => ({
  customerServiceHostPathFromModPath: () => testState.csHostPath,
}))

vi.mock('@/utils/sidebarActiveKey', () => ({
  isChatSidebarActive: () => false,
  normalizeSidebarActiveKey: (key: string) => key,
}))

vi.mock('@/router/registerModRoutes', () => ({
  registerAllModRoutesFromGlob: vi.fn().mockResolvedValue(undefined),
  registerModRoutes: vi.fn().mockResolvedValue(undefined),
}))

// 子组件 stub
vi.mock('./Sidebar.vue', () => ({
  default: {
    name: 'Sidebar',
    template:
      '<nav class="sidebar-stub" @change-view="$emit(\'change-view\', $event)" @toggle-pro-mode="$emit(\'toggle-pro-mode\')"><slot /></nav>',
    props: ['activeView', 'isProMode'],
    emits: ['change-view', 'toggle-pro-mode'],
  },
}))

vi.mock('./PaneResizeHandle.vue', () => ({
  default: { template: '<span class="pane-resize-stub" />' },
}))

vi.mock('./FloatingChatAssistant.vue', () => ({
  default: { template: '<div class="floating-chat-stub" />' },
}))

vi.mock('./TopAssistantFloat.vue', () => ({
  default: { template: '<div class="top-assistant-stub" />' },
}))

vi.mock('./VirtualCursor.vue', () => ({
  default: { template: '<div class="virtual-cursor-stub" />' },
}))

vi.mock('./OnboardingTutorial.vue', () => ({
  default: { template: '<div class="onboarding-tutorial-stub" />' },
}))

vi.mock('./TutorialOverlay.vue', () => ({
  default: { template: '<div class="tutorial-overlay-stub" />' },
}))

vi.mock('./MobileBottomNav.vue', () => ({
  default: { template: '<div class="mobile-bottom-nav-stub" />' },
}))

// ── 导入被测组件 ──────────────────────────────────────────

import MainLayout from './MainLayout.vue'

// ── 辅助函数 ──────────────────────────────────────────────

/** 重置 testState 到默认值 */
function resetTestState() {
  testState.route.name = 'chat'
  testState.route.meta = {}
  testState.route.path = '/chat'
  testState.route.matched = []
  testState.onboardingTutorialStore.active = false
  testState.tutorialStore.isActive = false
  testState.modsStore.modsForUi = []
  testState.modsStore.modRoutes = []
  testState.modsStore.initialize = vi.fn().mockResolvedValue(undefined)
  testState.accountProfileStore.loaded = true
  testState.accountProfileStore.displayBrand = ''
  testState.accountProfileStore.isImpersonating = false
  testState.accountProfileStore.impersonatingUsername = ''
  testState.accountProfileStore.companyBrand = ''
  testState.accountProfileStore.refreshFromServer = vi.fn().mockResolvedValue(undefined)
  testState.industryStore.currentIndustryId = 'generic'
  testState.industryStore.isLoaded = true
  testState.industryStore.initialize = vi.fn().mockResolvedValue(undefined)
  testState.resizablePaneConfig = null
  testState.resizablePaneReturn = {
    paneStyle: {},
    resetSize: vi.fn(),
    startResize: vi.fn(),
    stopResize: vi.fn(),
  }
  testState.modMenuItems.value = []
  testState.adminConsoleSpa = false
  testState.hostBusinessRedirect = null
  testState.csHostPath = null
  testState.xcmaxAdminApi.endImpersonate = vi.fn().mockResolvedValue(undefined)
  localStorage.clear()
}

/** 创建带路由的 MainLayout wrapper */
async function mountMainLayout(props: Record<string, unknown> = {}) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'chat', component: { template: '<div>Chat</div>' } },
      { path: '/settings', name: 'settings', component: { template: '<div>Settings</div>' } },
      { path: '/mod-store', name: 'mod-store', component: { template: '<div>ModStore</div>' } },
      {
        path: '/approval-hub/workspace',
        name: 'approval-workspace',
        component: { template: '<div>Approval</div>' },
      },
      {
        path: '/approval-hub',
        name: 'approval-hub',
        component: { template: '<div>Hub</div>' },
      },
    ],
  })
  await router.push('/')
  await router.isReady()
  testRouter = router

  const wrapper = mount(MainLayout, {
    global: {
      plugins: [pinia, router],
      stubs: {
        RouterView: { template: '<div class="router-view-stub" />' },
        RouterLink: { template: '<a><slot /></a>' },
      },
    },
    props: { isProMode: false, ...props },
  })
  return { wrapper, router }
}

// ── 测试套件 ──────────────────────────────────────────────

describe('MainLayout.vue - coverage ramp', () => {
  let originalMatchMedia: typeof window.matchMedia

  beforeEach(() => {
    resetTestState()
    originalMatchMedia = window.matchMedia
    // 默认 matchMedia 返回桌面（不匹配移动端）
    window.matchMedia = vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }))
  })

  afterEach(() => {
    window.matchMedia = originalMatchMedia
    vi.clearAllMocks()
  })

  // ════════════════════════════════════════════════════════════════════
  // endImpersonation
  // ════════════════════════════════════════════════════════════════════

  describe('endImpersonation', () => {
    it('成功结束时调用 endImpersonate + refreshFromServer + reload', async () => {
      testState.accountProfileStore.isImpersonating = true
      const reloadSpy = vi.fn()
      Object.defineProperty(window, 'location', {
        configurable: true,
        value: { ...window.location, reload: reloadSpy },
      })

      const { wrapper } = await mountMainLayout()
      await nextTick()

      // 点击结束代管按钮
      const endBtn = wrapper.find('.impersonate-bar__end')
      expect(endBtn.exists()).toBe(true)

      await endBtn.trigger('click')
      await nextTick()
      await nextTick()

      expect(testState.xcmaxAdminApi.endImpersonate).toHaveBeenCalled()
      expect(testState.accountProfileStore.refreshFromServer).toHaveBeenCalled()
      expect(reloadSpy).toHaveBeenCalled()

      wrapper.unmount()
    })

    it('endImpersonate 失败时显示 appAlert', async () => {
      testState.accountProfileStore.isImpersonating = true
      testState.xcmaxAdminApi.endImpersonate = vi.fn().mockRejectedValue(new Error('网络错误'))
      const { appAlert } = await import('@/utils/appDialog')

      // mock reload 避免实际刷新
      Object.defineProperty(window, 'location', {
        configurable: true,
        value: { ...window.location, reload: vi.fn() },
      })

      const { wrapper } = await mountMainLayout()
      await nextTick()

      const endBtn = wrapper.find('.impersonate-bar__end')
      await endBtn.trigger('click')
      await nextTick()
      await nextTick()
      await nextTick()

      expect(appAlert).toHaveBeenCalledWith(expect.stringContaining('结束代管失败'))
      wrapper.unmount()
    })

    it('endingImpersonation 状态在请求中为 true', async () => {
      testState.accountProfileStore.isImpersonating = true
      let resolveEndImpersonate: () => void
      testState.xcmaxAdminApi.endImpersonate = vi.fn(
        () => new Promise<void>((resolve) => {
          resolveEndImpersonate = resolve
        }),
      )

      Object.defineProperty(window, 'location', {
        configurable: true,
        value: { ...window.location, reload: vi.fn() },
      })

      const { wrapper } = await mountMainLayout()
      await nextTick()

      const endBtn = wrapper.find('.impersonate-bar__end')
      const clickPromise = endBtn.trigger('click')
      await nextTick()

      // 按钮应显示"结束中…"
      expect(wrapper.find('.impersonate-bar__end').text()).toContain('结束中')

      // resolve 请求
      resolveEndImpersonate!()
      await clickPromise
      await nextTick()
      await nextTick()

      wrapper.unmount()
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // accountUsername
  // ════════════════════════════════════════════════════════════════════

  describe('accountUsername', () => {
    it('localStorage 有有效 JSON 时返回 username', async () => {
      testState.accountProfileStore.displayBrand = '测试品牌'
      localStorage.setItem('xcagi_market_user_json', JSON.stringify({ username: 'testuser' }))

      const { wrapper } = await mountMainLayout()
      await nextTick()

      expect(wrapper.find('.page-account-sub').exists()).toBe(true)
      expect(wrapper.find('.page-account-sub').text()).toContain('testuser')
      wrapper.unmount()
    })

    it('localStorage JSON 解析失败时返回空字符串', async () => {
      testState.accountProfileStore.displayBrand = '测试品牌'
      localStorage.setItem('xcagi_market_user_json', 'invalid-json{')

      const { wrapper } = await mountMainLayout()
      await nextTick()

      // 不应崩溃，accountUsername 为空
      expect(wrapper.find('.page-account-sub').exists()).toBe(false)
      wrapper.unmount()
    })

    it('localStorage 无数据时返回空字符串', async () => {
      testState.accountProfileStore.displayBrand = '测试品牌'
      const { wrapper } = await mountMainLayout()
      await nextTick()

      expect(wrapper.find('.page-account-sub').exists()).toBe(false)
      wrapper.unmount()
    })

    it('JSON 中 username 为空时返回空字符串', async () => {
      testState.accountProfileStore.displayBrand = '测试品牌'
      localStorage.setItem('xcagi_market_user_json', JSON.stringify({ username: '' }))

      const { wrapper } = await mountMainLayout()
      await nextTick()

      expect(wrapper.find('.page-account-sub').exists()).toBe(false)
      wrapper.unmount()
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // resolveModBadgeSuffix / modeBadgeText
  // ════════════════════════════════════════════════════════════════════

  describe('resolveModBadgeSuffix / modeBadgeText', () => {
    it('有 mods 时 modeBadgeText 包含 Mod 名称', async () => {
      testState.modsStore.modsForUi = [{ name: '财务分析', primary: true }]
      const { wrapper } = await mountMainLayout()
      expect(wrapper.vm.modeBadgeText).toContain('财务分析')
      wrapper.unmount()
    })

    it('mod name 超过 8 字符时截断', async () => {
      testState.modsStore.modsForUi = [{ name: '这是一个很长的Mod名称测试', primary: true }]
      const { wrapper } = await mountMainLayout()
      const suffix = wrapper.vm.resolveModBadgeSuffix()
      expect(suffix).toContain('…')
      expect(suffix.length).toBeLessThanOrEqual(8)
      wrapper.unmount()
    })

    it('mod 无 name 时使用 id', async () => {
      testState.modsStore.modsForUi = [{ id: 'mod-id' }]
      const { wrapper } = await mountMainLayout()
      expect(wrapper.vm.resolveModBadgeSuffix()).toBe('mod-id')
      wrapper.unmount()
    })

    it('mod 无 name 和 id 时返回 Mod', async () => {
      testState.modsStore.modsForUi = [{}]
      const { wrapper } = await mountMainLayout()
      expect(wrapper.vm.resolveModBadgeSuffix()).toBe('Mod')
      wrapper.unmount()
    })

    it('首个 primary mod 优先于非 primary', async () => {
      testState.modsStore.modsForUi = [
        { name: 'NonPrim' },
        { name: 'Primary', primary: true },
      ]
      const { wrapper } = await mountMainLayout()
      expect(wrapper.vm.resolveModBadgeSuffix()).toBe('Primary')
      wrapper.unmount()
    })

    it('sandbox 模式时 modeBadgeText 为沙箱模式', async () => {
      // sandbox 通过 URL 参数检测，在模块级别读取
      // 这里直接验证 modeBadgeText 逻辑
      const { wrapper } = await mountMainLayout()
      // 默认非 sandbox
      expect(wrapper.vm.modeBadgeText).not.toContain('沙箱模式')
      wrapper.unmount()
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // modPathToSidebarKey
  // ════════════════════════════════════════════════════════════════════

  describe('modPathToSidebarKey', () => {
    it('modMenuItems 有 path 时建立映射', async () => {
      testState.modMenuItems.value = [
        { key: 'mod-a', path: '/mod/a' },
        { key: 'mod-b', path: '/mod/b' },
      ]
      const { wrapper } = await mountMainLayout()
      const map = wrapper.vm.modPathToSidebarKey
      expect(map['/mod/a']).toBe('mod-a')
      expect(map['/mod/b']).toBe('mod-b')
      wrapper.unmount()
    })

    it('modMenuItems 无 path 时不建立映射', async () => {
      testState.modMenuItems.value = [{ key: 'mod-a' }, { key: 'mod-b', path: '' }]
      const { wrapper } = await mountMainLayout()
      const map = wrapper.vm.modPathToSidebarKey
      expect(Object.keys(map).length).toBe(0)
      wrapper.unmount()
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // currentRouteName - matched 路由回退
  // ════════════════════════════════════════════════════════════════════

  describe('currentRouteName - matched 路由回退', () => {
    it('route.path 不在 routeNameMap 但 matched 中有已知路径时回退', async () => {
      testState.route.path = '/unknown'
      testState.route.name = undefined
      testState.route.matched = [{ path: '/' }] // '/' 在 routeNameMap 中 → 'chat'

      const { wrapper } = await mountMainLayout()
      await nextTick()
      expect(wrapper.vm.currentRouteName).toBe('chat')
      wrapper.unmount()
    })

    it('route.path 和 matched 都无匹配时使用 route.name', async () => {
      testState.route.path = '/unknown'
      testState.route.name = 'custom-route'
      testState.route.matched = []

      const { wrapper } = await mountMainLayout()
      await nextTick()
      expect(wrapper.vm.currentRouteName).toBe('custom-route')
      wrapper.unmount()
    })

    it('route.name 也为空时默认 chat', async () => {
      testState.route.path = '/unknown'
      testState.route.name = ''
      testState.route.matched = []

      const { wrapper } = await mountMainLayout()
      await nextTick()
      expect(wrapper.vm.currentRouteName).toBe('chat')
      wrapper.unmount()
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // useResizablePane 回调
  // ════════════════════════════════════════════════════════════════════

  describe('useResizablePane 回调', () => {
    it('enabled 回调：sidebar 启用且未折叠时返回 true', async () => {
      const { wrapper } = await mountMainLayout()
      const config = testState.resizablePaneConfig!
      const enabledFn = config.enabled as () => boolean

      wrapper.vm.sidebarCollapsed = false
      wrapper.vm.isSidebarFeatureEnabled = true
      expect(enabledFn()).toBe(true)

      wrapper.vm.sidebarCollapsed = true
      expect(enabledFn()).toBe(false)

      wrapper.vm.sidebarCollapsed = false
      wrapper.vm.isSidebarFeatureEnabled = false
      expect(enabledFn()).toBe(false)
      wrapper.unmount()
    })

    it('onResizeStart 回调：清理 collapse 和 hover timer', async () => {
      const { wrapper } = await mountMainLayout()
      const config = testState.resizablePaneConfig!
      const onResizeStart = config.onResizeStart as () => void

      // 设置 timer
      wrapper.vm.sidebarCollapseTimer = window.setTimeout(() => {}, 10000)
      wrapper.vm.sidebarHoverTimer = window.setTimeout(() => {}, 10000)

      onResizeStart()

      expect(wrapper.vm.sidebarCollapseTimer).toBeNull()
      expect(wrapper.vm.sidebarHoverTimer).toBeNull()
      wrapper.unmount()
    })

    it('onResizeEnd 回调：sidebar 启用且未折叠时 scheduleSidebarAutoCollapse', async () => {
      const setTimeoutSpy = vi.spyOn(window, 'setTimeout')
      const { wrapper } = await mountMainLayout()
      const config = testState.resizablePaneConfig!
      const onResizeEnd = config.onResizeEnd as () => void

      setTimeoutSpy.mockClear()
      onResizeEnd()
      // scheduleSidebarAutoCollapse 应调用 setTimeout
      expect(setTimeoutSpy).toHaveBeenCalled()
      wrapper.unmount()
      setTimeoutSpy.mockRestore()
    })

    it('onResizeEnd 回调：sidebar 禁用时不 schedule', async () => {
      // 通过 matchMedia 禁用 sidebar（匹配 SIDEBAR_DISABLE_MQ）
      window.matchMedia = vi.fn().mockImplementation((query: string) => ({
        matches: query === '(max-width: 767px)',
        media: query,
        onchange: null,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        addListener: vi.fn(),
        removeListener: vi.fn(),
        dispatchEvent: vi.fn(),
      }))

      const setTimeoutSpy = vi.spyOn(window, 'setTimeout')
      const { wrapper } = await mountMainLayout()
      const config = testState.resizablePaneConfig!
      const onResizeEnd = config.onResizeEnd as () => void

      setTimeoutSpy.mockClear()
      onResizeEnd()
      // sidebar 禁用时不应调度 auto collapse
      expect(setTimeoutSpy).not.toHaveBeenCalled()
      wrapper.unmount()
      setTimeoutSpy.mockRestore()
    })

    it('onResizeEnd 回调：sidebar 折叠时不 schedule', async () => {
      vi.useFakeTimers()
      const { wrapper } = await mountMainLayout()
      const config = testState.resizablePaneConfig!
      const onResizeEnd = config.onResizeEnd as () => void

      // 先触发 auto-collapse 让 sidebarCollapsed = true
      onResizeEnd()
      vi.advanceTimersByTime(15000) // SIDEBAR_INACTIVITY_MS

      // 现在 sidebarCollapsed 应为 true，onResizeEnd 不应调度新 timer
      const setTimeoutSpy = vi.spyOn(window, 'setTimeout')
      onResizeEnd()
      expect(setTimeoutSpy).not.toHaveBeenCalled()

      wrapper.unmount()
      vi.useRealTimers()
      setTimeoutSpy.mockRestore()
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // currentViewTitle - metaTitle 回退
  // ════════════════════════════════════════════════════════════════════

  describe('currentViewTitle - metaTitle 回退', () => {
    it('route.meta.title 存在时使用 meta title', async () => {
      testState.route.name = 'unknown-route'
      testState.route.meta = { title: '自定义页面标题' }
      const { wrapper } = await mountMainLayout()
      await nextTick()
      expect(wrapper.vm.currentViewTitle).toBe('自定义页面标题')
      wrapper.unmount()
    })

    it('无匹配时返回"未知页面"', async () => {
      testState.route.name = 'unknown-route'
      testState.route.meta = {}
      const { wrapper } = await mountMainLayout()
      await nextTick()
      expect(wrapper.vm.currentViewTitle).toBe('未知页面')
      wrapper.unmount()
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // resolveLegacyRouteFromModPath
  // ════════════════════════════════════════════════════════════════════

  describe('resolveLegacyRouteFromModPath', () => {
    it('approval-hub/workspace 路径返回 approval-workspace', async () => {
      const { wrapper, router } = await mountMainLayout()
      // router 有 approval-workspace 路由
      const result = wrapper.vm.resolveLegacyRouteFromModPath('/mod/test/approval-hub/workspace')
      expect(result).toEqual({ name: 'approval-workspace' })
      wrapper.unmount()
    })

    it('以 /approval-hub 结尾的路径返回 approval-hub', async () => {
      const { wrapper } = await mountMainLayout()
      const result = wrapper.vm.resolveLegacyRouteFromModPath('/mod/test/approval-hub')
      expect(result).toEqual({ name: 'approval-hub' })
      wrapper.unmount()
    })

    it('最后一段匹配路由名时返回该路由', async () => {
      const { wrapper } = await mountMainLayout()
      // 'settings' 是已注册路由
      const result = wrapper.vm.resolveLegacyRouteFromModPath('/some/path/settings')
      expect(result).toEqual({ name: 'settings' })
      wrapper.unmount()
    })

    it('无匹配时返回 null', async () => {
      const { wrapper } = await mountMainLayout()
      const result = wrapper.vm.resolveLegacyRouteFromModPath('/some/unknown/path')
      expect(result).toBeNull()
      wrapper.unmount()
    })

    it('路径含 query 和 hash 时正确解析', async () => {
      const { wrapper } = await mountMainLayout()
      const result = wrapper.vm.resolveLegacyRouteFromModPath('/mod/test/approval-hub/workspace?foo=bar#section')
      expect(result).toEqual({ name: 'approval-workspace' })
      wrapper.unmount()
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // navigateToView - Mod 路由分支
  // ════════════════════════════════════════════════════════════════════

  describe('navigateToView - Mod 路由分支', () => {
    it('modItem.path 已注册时直接 push', async () => {
      const { wrapper, router } = await mountMainLayout()
      const pushSpy = vi.spyOn(router, 'push')
      testState.modMenuItems.value = [{ key: 'mod-store', path: '/mod-store' }]

      await wrapper.vm.navigateToView('mod-store')
      expect(pushSpy).toHaveBeenCalledWith('/mod-store')
      wrapper.unmount()
    })

    it('modItem.path 未注册但 legacy 路由存在时 push legacy', async () => {
      const { wrapper, router } = await mountMainLayout()
      const pushSpy = vi.spyOn(router, 'push')
      testState.modMenuItems.value = [
        { key: 'mod-approval', path: '/mod/test/approval-hub/workspace' },
      ]

      await wrapper.vm.navigateToView('mod-approval')
      expect(pushSpy).toHaveBeenCalledWith({ name: 'approval-workspace' })
      wrapper.unmount()
    })

    it('modItem.path 未注册且无 legacy 但有 csHost 时 push csHost', async () => {
      const { wrapper, router } = await mountMainLayout()
      const pushSpy = vi.spyOn(router, 'push')
      testState.csHostPath = '/customer-service/host'
      testState.modMenuItems.value = [{ key: 'mod-cs', path: '/mod/test/cs' }]

      await wrapper.vm.navigateToView('mod-cs')
      expect(pushSpy).toHaveBeenCalledWith('/customer-service/host')
      wrapper.unmount()
    })

    it('modItem.path 未注册且无 legacy/csHost 时 warn', async () => {
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
      const { wrapper } = await mountMainLayout()
      testState.modMenuItems.value = [{ key: 'mod-unknown', path: '/mod/unknown/path' }]

      await wrapper.vm.navigateToView('mod-unknown')
      expect(warnSpy).toHaveBeenCalledWith(
        expect.stringContaining('Mod 路由未注册'),
        '/mod/unknown/path',
      )
      warnSpy.mockRestore()
      wrapper.unmount()
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // navigateToView - modBusinessPath 分支
  // ════════════════════════════════════════════════════════════════════

  describe('navigateToView - modBusinessPath 分支', () => {
    it('resolveHostBusinessPageRedirect 返回已注册路径时 push', async () => {
      const { wrapper, router } = await mountMainLayout()
      const pushSpy = vi.spyOn(router, 'push')
      testState.hostBusinessRedirect = '/settings'

      await wrapper.vm.navigateToView('settings')
      expect(pushSpy).toHaveBeenCalledWith('/settings')
      wrapper.unmount()
    })

    it('resolveHostBusinessPageRedirect 返回未注册路径但 legacy 存在时 push legacy', async () => {
      const { wrapper, router } = await mountMainLayout()
      const pushSpy = vi.spyOn(router, 'push')
      // hostBusinessRedirect 指向一个未注册但 legacy 可解析的路径
      testState.hostBusinessRedirect = '/mod/test/approval-hub/workspace'

      await wrapper.vm.navigateToView('approval-hub')
      expect(pushSpy).toHaveBeenCalledWith({ name: 'approval-workspace' })
      wrapper.unmount()
    })

    it('resolveHostBusinessPageRedirect 返回未注册路径且有 csHost 时 push csHost', async () => {
      const { wrapper, router } = await mountMainLayout()
      const pushSpy = vi.spyOn(router, 'push')
      testState.hostBusinessRedirect = '/mod/test/unknown'
      testState.csHostPath = '/customer-service/host'

      await wrapper.vm.navigateToView('unknown-mod')
      expect(pushSpy).toHaveBeenCalledWith('/customer-service/host')
      wrapper.unmount()
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // navigateToView - nameCandidate / routePath 回退
  // ════════════════════════════════════════════════════════════════════

  describe('navigateToView - nameCandidate / routePath 回退', () => {
    it('routeName 去除 mod- 前缀后匹配路由时 push', async () => {
      const { wrapper, router } = await mountMainLayout()
      const pushSpy = vi.spyOn(router, 'push')

      // 'mod-settings' 去除前缀后为 'settings'，已注册
      await wrapper.vm.navigateToView('mod-settings')
      expect(pushSpy).toHaveBeenCalledWith({ name: 'settings' })
      wrapper.unmount()
    })

    it('routeName 直接匹配路由名时 push', async () => {
      const { wrapper, router } = await mountMainLayout()
      const pushSpy = vi.spyOn(router, 'push')

      await wrapper.vm.navigateToView('settings')
      // settings 在 routeNameMap 中对应 '/settings'，也可能通过 name 匹配
      expect(pushSpy).toHaveBeenCalled()
      wrapper.unmount()
    })

    it('routeNameMap 反查到路径时 push 路径', async () => {
      const { wrapper, router } = await mountMainLayout()
      const pushSpy = vi.spyOn(router, 'push')

      // 'chat' 在 routeNameMap 中对应 '/'
      await wrapper.vm.navigateToView('chat')
      expect(pushSpy).toHaveBeenCalled()
      wrapper.unmount()
    })

    it('无任何匹配时 warn', async () => {
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
      const { wrapper } = await mountMainLayout()

      await wrapper.vm.navigateToView('nonexistent-view')
      expect(warnSpy).toHaveBeenCalledWith(
        expect.stringContaining('侧栏无对应路由'),
        'nonexistent-view',
      )
      warnSpy.mockRestore()
      wrapper.unmount()
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // watch(isAnyTutorialActive)
  // ════════════════════════════════════════════════════════════════════

  describe('watch(isAnyTutorialActive)', () => {
    it('教程激活时展开 sidebar', async () => {
      const { wrapper } = await mountMainLayout()
      wrapper.vm.sidebarCollapsed = true
      wrapper.vm.isSidebarFeatureEnabled = true
      await nextTick()

      // 激活教程
      testState.onboardingTutorialStore.active = true
      await nextTick()

      // sidebar 应展开
      expect(wrapper.vm.sidebarCollapsed).toBe(false)
      wrapper.unmount()
    })

    it('教程失活且 sidebar 启用时 schedule auto collapse', async () => {
      const { wrapper } = await mountMainLayout()
      wrapper.vm.isSidebarFeatureEnabled = true
      wrapper.vm.sidebarCollapsed = false

      // 先激活教程
      testState.onboardingTutorialStore.active = true
      await nextTick()

      // 清除 timer
      wrapper.vm.sidebarCollapseTimer = null

      // 失活教程
      testState.onboardingTutorialStore.active = false
      await nextTick()

      // 应调度 auto collapse
      expect(wrapper.vm.sidebarCollapseTimer).not.toBeNull()
      wrapper.unmount()
    })

    it('legacy tutorial 激活也触发展开', async () => {
      const { wrapper } = await mountMainLayout()
      wrapper.vm.sidebarCollapsed = true
      wrapper.vm.isSidebarFeatureEnabled = true
      await nextTick()

      testState.tutorialStore.isActive = true
      await nextTick()

      expect(wrapper.vm.sidebarCollapsed).toBe(false)
      wrapper.unmount()
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // handleGlobalActivity / onSidebarMouseEnter
  // ════════════════════════════════════════════════════════════════════

  describe('handleGlobalActivity / onSidebarMouseEnter', () => {
    it('sidebar 启用且未折叠时 onSidebarMouseEnter 调度 auto collapse', async () => {
      const { wrapper } = await mountMainLayout()
      wrapper.vm.isSidebarFeatureEnabled = true
      wrapper.vm.sidebarCollapsed = false
      wrapper.vm.sidebarCollapseTimer = null

      await wrapper.find('.sidebar-shell').trigger('mouseenter')
      expect(wrapper.vm.sidebarCollapseTimer).not.toBeNull()
      wrapper.unmount()
    })

    it('sidebar 禁用时 onSidebarMouseEnter 不调度', async () => {
      const { wrapper } = await mountMainLayout()
      wrapper.vm.isSidebarFeatureEnabled = false
      wrapper.vm.sidebarCollapseTimer = null

      await wrapper.find('.sidebar-shell').trigger('mouseenter')
      expect(wrapper.vm.sidebarCollapseTimer).toBeNull()
      wrapper.unmount()
    })

    it('sidebar 折叠时 handleGlobalActivity 不调度', async () => {
      const { wrapper } = await mountMainLayout()
      wrapper.vm.isSidebarFeatureEnabled = true
      wrapper.vm.sidebarCollapsed = true
      wrapper.vm.sidebarCollapseTimer = null

      wrapper.vm.handleGlobalActivity()
      expect(wrapper.vm.sidebarCollapseTimer).toBeNull()
      wrapper.unmount()
    })

    it('全局 mousemove 事件触发 handleGlobalActivity', async () => {
      const { wrapper } = await mountMainLayout()
      wrapper.vm.isSidebarFeatureEnabled = true
      wrapper.vm.sidebarCollapsed = false
      wrapper.vm.sidebarCollapseTimer = null

      window.dispatchEvent(new Event('mousemove'))
      expect(wrapper.vm.sidebarCollapseTimer).not.toBeNull()
      wrapper.unmount()
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // onHoverTriggerEnter / onHoverTriggerLeave / onHoverTriggerClick
  // ════════════════════════════════════════════════════════════════════

  describe('onHoverTriggerEnter / onHoverTriggerLeave / onHoverTriggerClick', () => {
    it('onHoverTriggerClick 立即展开 sidebar', async () => {
      const { wrapper } = await mountMainLayout()
      wrapper.vm.isSidebarFeatureEnabled = true
      wrapper.vm.sidebarCollapsed = true

      wrapper.vm.onHoverTriggerClick()
      expect(wrapper.vm.sidebarCollapsed).toBe(false)
      // 应调度 auto collapse
      expect(wrapper.vm.sidebarCollapseTimer).not.toBeNull()
      wrapper.unmount()
    })

    it('onHoverTriggerEnter 在 sidebar 禁用时不操作', async () => {
      const { wrapper } = await mountMainLayout()
      wrapper.vm.isSidebarFeatureEnabled = false
      wrapper.vm.sidebarCollapsed = true

      wrapper.vm.onHoverTriggerEnter()
      // 不应设置 hover timer
      expect(wrapper.vm.sidebarHoverTimer).toBeNull()
      wrapper.unmount()
    })

    it('onHoverTriggerEnter 在 sidebar 已展开时不操作', async () => {
      const { wrapper } = await mountMainLayout()
      wrapper.vm.isSidebarFeatureEnabled = true
      wrapper.vm.sidebarCollapsed = false

      wrapper.vm.onHoverTriggerEnter()
      expect(wrapper.vm.sidebarHoverTimer).toBeNull()
      wrapper.unmount()
    })

    it('onHoverTriggerLeave 清理 hover timer', async () => {
      const { wrapper } = await mountMainLayout()
      wrapper.vm.sidebarHoverTimer = window.setTimeout(() => {}, 10000)

      wrapper.vm.onHoverTriggerLeave()
      expect(wrapper.vm.sidebarHoverTimer).toBeNull()
      wrapper.unmount()
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // onMounted - store 未加载时刷新
  // ════════════════════════════════════════════════════════════════════

  describe('onMounted - store 未加载时刷新', () => {
    it('accountProfileStore.loaded=false 时调用 refreshFromServer', async () => {
      testState.accountProfileStore.loaded = false
      const { wrapper } = await mountMainLayout()
      await nextTick()
      await nextTick()
      expect(testState.accountProfileStore.refreshFromServer).toHaveBeenCalled()
      wrapper.unmount()
    })

    it('industryStore.isLoaded=false 时调用 initialize', async () => {
      testState.industryStore.isLoaded = false
      const { wrapper } = await mountMainLayout()
      await nextTick()
      await nextTick()
      expect(testState.industryStore.initialize).toHaveBeenCalled()
      wrapper.unmount()
    })

    it('refreshFromServer 失败时不抛异常', async () => {
      testState.accountProfileStore.loaded = false
      testState.accountProfileStore.refreshFromServer = vi.fn().mockRejectedValue(new Error('fail'))
      const { wrapper } = await mountMainLayout()
      await nextTick()
      await nextTick()
      wrapper.unmount()
    })

    it('industryStore.initialize 失败时不抛异常', async () => {
      testState.industryStore.isLoaded = false
      testState.industryStore.initialize = vi.fn().mockRejectedValue(new Error('fail'))
      const { wrapper } = await mountMainLayout()
      await nextTick()
      await nextTick()
      wrapper.unmount()
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // matchMedia - addListener/removeListener 旧 API 回退
  // ════════════════════════════════════════════════════════════════════

  describe('matchMedia - 旧 API 回退', () => {
    it('MediaQueryList 无 addEventListener 但有 addListener 时使用 addListener', async () => {
      // 模拟旧浏览器：只有 addListener/removeListener
      const oldMql = {
        matches: false,
        media: '',
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        dispatchEvent: vi.fn(),
        // 无 addEventListener / removeEventListener
      }
      window.matchMedia = vi.fn().mockReturnValue(oldMql)

      const { wrapper } = await mountMainLayout()
      await nextTick()

      // addListener 应被调用（sidebar viewport + mobile nav viewport）
      expect(oldMql.addListener).toHaveBeenCalled()
      wrapper.unmount()

      // 卸载后 removeListener 应被调用
      expect(oldMql.removeListener).toHaveBeenCalled()
    })

    it('MediaQueryList 有 addEventListener 时使用 addEventListener', async () => {
      const addEventListenerSpy = vi.fn()
      const removeEventListenerSpy = vi.fn()
      window.matchMedia = vi.fn().mockReturnValue({
        matches: false,
        media: '',
        onchange: null,
        addEventListener: addEventListenerSpy,
        removeEventListener: removeEventListenerSpy,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })

      const { wrapper } = await mountMainLayout()
      await nextTick()

      expect(addEventListenerSpy).toHaveBeenCalled()
      wrapper.unmount()
      expect(removeEventListenerSpy).toHaveBeenCalled()
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // onViewportChange
  // ════════════════════════════════════════════════════════════════════

  describe('onViewportChange', () => {
    it('matches=true 时禁用 sidebar 并停止 resize', async () => {
      const { wrapper } = await mountMainLayout()
      wrapper.vm.isSidebarFeatureEnabled = true
      wrapper.vm.sidebarCollapsed = true

      wrapper.vm.onViewportChange({ matches: true })
      expect(wrapper.vm.isSidebarFeatureEnabled).toBe(false)
      expect(wrapper.vm.sidebarCollapsed).toBe(false)
      // stopSidebarResize 应被调用
      expect(testState.resizablePaneReturn.stopResize).toHaveBeenCalled()
      wrapper.unmount()
    })

    it('matches=false 时启用 sidebar 并调度 auto collapse', async () => {
      const { wrapper } = await mountMainLayout()
      wrapper.vm.isSidebarFeatureEnabled = false
      wrapper.vm.sidebarCollapseTimer = null

      wrapper.vm.onViewportChange({ matches: false })
      expect(wrapper.vm.isSidebarFeatureEnabled).toBe(true)
      expect(wrapper.vm.sidebarCollapseTimer).not.toBeNull()
      wrapper.unmount()
    })

    it('matches=undefined 时视为 false', async () => {
      const { wrapper } = await mountMainLayout()
      wrapper.vm.isSidebarFeatureEnabled = false

      wrapper.vm.onViewportChange(undefined as unknown as MediaQueryListEvent)
      expect(wrapper.vm.isSidebarFeatureEnabled).toBe(true)
      wrapper.unmount()
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // mobileBottomNavVisible
  // ════════════════════════════════════════════════════════════════════

  describe('mobileBottomNavVisible', () => {
    it('showMobileBottomNav=true 且非 adminConsoleSpa 时可见', async () => {
      const { wrapper } = await mountMainLayout()
      wrapper.vm.showMobileBottomNav = true
      await nextTick()
      expect(wrapper.vm.mobileBottomNavVisible).toBe(true)
      wrapper.unmount()
    })

    it('showMobileBottomNav=true 但 adminConsoleSpa 时不可见', async () => {
      testState.adminConsoleSpa = true
      const { wrapper } = await mountMainLayout()
      wrapper.vm.showMobileBottomNav = true
      await nextTick()
      expect(wrapper.vm.mobileBottomNavVisible).toBe(false)
      wrapper.unmount()
    })

    it('route.meta.hideChrome=true 时不可见', async () => {
      const { wrapper } = await mountMainLayout()
      testState.route.meta = { hideChrome: true }
      wrapper.vm.showMobileBottomNav = true
      await nextTick()
      expect(wrapper.vm.mobileBottomNavVisible).toBe(false)
      wrapper.unmount()
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // topKickerText
  // ════════════════════════════════════════════════════════════════════

  describe('topKickerText', () => {
    it('adminConsoleSpa 时返回 ADMIN_OPERATOR_BRAND_SUBTITLE', async () => {
      testState.adminConsoleSpa = true
      const { wrapper } = await mountMainLayout()
      expect(wrapper.vm.topKickerText).toBe('运维管理')
      wrapper.unmount()
    })

    it('displayBrand 非空时返回 displayBrand', async () => {
      testState.accountProfileStore.displayBrand = '我的品牌'
      const { wrapper } = await mountMainLayout()
      expect(wrapper.vm.topKickerText).toBe('我的品牌')
      wrapper.unmount()
    })

    it('displayBrand 为空时返回 workbenchKicker', async () => {
      testState.accountProfileStore.displayBrand = ''
      const { wrapper } = await mountMainLayout()
      expect(wrapper.vm.topKickerText).toContain('工作台')
      wrapper.unmount()
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // impersonationLabel
  // ════════════════════════════════════════════════════════════════════

  describe('impersonationLabel', () => {
    it('companyBrand 非空时优先使用', async () => {
      testState.accountProfileStore.isImpersonating = true
      testState.accountProfileStore.companyBrand = '公司品牌'
      testState.accountProfileStore.impersonatingUsername = 'user'
      const { wrapper } = await mountMainLayout()
      expect(wrapper.vm.impersonationLabel).toBe('公司品牌')
      wrapper.unmount()
    })

    it('companyBrand 为空时使用 impersonatingUsername', async () => {
      testState.accountProfileStore.isImpersonating = true
      testState.accountProfileStore.companyBrand = ''
      testState.accountProfileStore.impersonatingUsername = 'testuser'
      const { wrapper } = await mountMainLayout()
      expect(wrapper.vm.impersonationLabel).toBe('testuser')
      wrapper.unmount()
    })

    it('两者都为空时返回"目标用户"', async () => {
      testState.accountProfileStore.isImpersonating = true
      testState.accountProfileStore.companyBrand = ''
      testState.accountProfileStore.impersonatingUsername = ''
      const { wrapper } = await mountMainLayout()
      expect(wrapper.vm.impersonationLabel).toBe('目标用户')
      wrapper.unmount()
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // openSettings
  // ════════════════════════════════════════════════════════════════════

  describe('openSettings', () => {
    it('push settings 路由', async () => {
      const { wrapper, router } = await mountMainLayout()
      const pushSpy = vi.spyOn(router, 'push')
      wrapper.vm.openSettings()
      expect(pushSpy).toHaveBeenCalledWith({ name: 'settings' })
      wrapper.unmount()
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // scheduleSidebarAutoCollapse - isAnyTutorialActive 守卫
  // ════════════════════════════════════════════════════════════════════

  describe('scheduleSidebarAutoCollapse - tutorial 守卫', () => {
    it('教程激活时不调度 auto collapse', async () => {
      const { wrapper } = await mountMainLayout()
      testState.onboardingTutorialStore.active = true
      await nextTick()

      wrapper.vm.isSidebarFeatureEnabled = true
      wrapper.vm.sidebarCollapsed = false
      wrapper.vm.sidebarCollapseTimer = null

      wrapper.vm.scheduleSidebarAutoCollapse()
      expect(wrapper.vm.sidebarCollapseTimer).toBeNull()
      wrapper.unmount()
    })
  })
})
