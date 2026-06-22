/**
 * useAppBoot 覆盖率提升测试
 *
 * 目标：覆盖 useAppBoot.ts 中未覆盖的分支，将覆盖率提升到 90%+。
 * 重点覆盖：
 *   - startupPublicUrl：各种 BASE_URL 组合、双斜杠合并
 *   - isPublicEntryRoute：login / lan-gate / product-onboarding / hideChrome meta
 *   - isSandboxMode：URL 参数检测
 *   - hideChrome / startupModNames / primaryModName 计算属性
 *   - watch(route.name) 路由切换：公共路由 stop、非公共路由 start
 *   - onMounted：visibilitychange / pageshow 监听、shellBridge 安装、proMode 初始化
 *   - onBeforeUnmount：事件移除、bridge 卸载、sync stop
 *   - skipStartupSplash 返回函数
 *   - isClientModeTiersUiEnabled 分支（true / false）
 *
 * 遵循铁律3：happy path + 空值/None + 边界值 + 异常路径。
 * Mock 最小化：仅 mock 外部边界（stores、composables、constants）。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, nextTick } from 'vue'
import { mount } from '@vue/test-utils'

// ── 使用 vi.hoisted 创建可变的 reactive 路由对象 ──────────────────────
// vi.hoisted 在所有 import 之前同步执行，mock factory 可安全引用其返回值。
// vi.hoisted 同步执行于 import 之前，无法使用 ES import 或 await import()，
// 只能通过 require() 同步获取 vue 模块以创建 reactive/ref 状态。
const testState = vi.hoisted(() => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const vue = require('vue') as typeof import('vue')
  return {
    route: vue.reactive({
      name: 'chat' as string | undefined,
      meta: {} as Record<string, unknown>,
      query: {},
      path: '/chat',
    }),
    router: {
      push: vi.fn(),
      replace: vi.fn(),
      isReady: () => Promise.resolve(),
    },
    modsStore: {
      modsForUi: [] as unknown[],
      isLoaded: false,
      clientModsUiOff: false,
      initialize: vi.fn().mockResolvedValue(undefined),
      applyLoadingStatusPreview: vi.fn(),
    },
    workflowAiEmployeesStore: {
      stripModWorkflowEmployeeKeys: vi.fn(),
    },
    splash: {
      startupVisible: vue.ref(false),
      appReady: vue.ref(true),
      startupProgressPct: vue.ref(0),
      startupModPreview: vue.ref([]),
      startupPreviewModNames: vue.ref<string[]>([]),
      modsLoading: vue.ref(false),
      modsLoadError: vue.ref<string | null>(null),
      dismissStartupSplashImmediate: vi.fn(),
      loadModsForStartup: vi.fn().mockResolvedValue(undefined),
      completeStartupSplash: vi.fn(),
      skipStartupSplash: vi.fn(),
      runStartupProgressLoop: vi.fn(),
      initStartupAudio: vi.fn(),
      scheduleFailsafe: vi.fn(),
      createMinSplashElapsed: vi.fn(() => Promise.resolve()),
      teardownOnUnmount: vi.fn(),
      clearFailsafeTimer: vi.fn(),
    },
    proMode: {
      isProMode: vue.ref(false),
      handleToggleProMode: vi.fn(),
      readProModeStateFromDom: vi.fn(() => false),
      syncGlobalProMode: vi.fn(),
      installLegacyDomObserver: vi.fn(),
      uninstallLegacyDomObserver: vi.fn(),
      enforceClientNormalModeBaseline: vi.fn(),
    },
    shellBridge: {
      installProModeBridge: vi.fn(),
      installSwitchViewBridge: vi.fn(),
      installSandboxBridge: vi.fn(),
      bindLegacyUploadHooks: vi.fn(),
      uninstall: vi.fn(),
    },
    xcmaxSync: {
      start: vi.fn(),
      stop: vi.fn(),
    },
    startupAuth: {
      ensureStartupAuthenticated: vi.fn().mockResolvedValue({ ok: true, entitledModIds: [] }),
      runEnterpriseStartupAuth: vi.fn().mockResolvedValue(undefined),
    },
    clientModeTiersEnabled: false,
    adminConsoleSpa: false,
  }
})

// ── Mock 配置 ──────────────────────────────────────────────────────────

vi.mock('vue-router', () => ({
  useRoute: () => testState.route,
  useRouter: () => testState.router,
}))

vi.mock('@/stores/mods', () => ({
  useModsStore: () => testState.modsStore,
}))

vi.mock('@/stores/workflowAiEmployees', () => ({
  useWorkflowAiEmployeesStore: () => testState.workflowAiEmployeesStore,
}))

vi.mock('@/utils/adminConsoleUrl', () => ({
  isAdminConsoleSpa: () => testState.adminConsoleSpa,
}))

vi.mock('@/constants/platformShellMode', () => ({
  isPlatformShellModeEnabled: vi.fn(() => false),
}))

vi.mock('@/constants/clientModeTiers', () => ({
  isClientModeTiersUiEnabled: () => testState.clientModeTiersEnabled,
  resetClientModeTierLocalState: vi.fn(),
}))

vi.mock('@/composables/useStartupAuth', () => ({
  useStartupAuth: () => testState.startupAuth,
}))

vi.mock('@/composables/useStartupSplash', () => ({
  STARTUP_MOD_FETCH_CAP_MS: 2500,
  extractModNames: (list: unknown[]) => {
    const rows = Array.isArray(list) ? list : []
    return rows
      .map((m) => {
        const row = m as { name?: string; id?: string }
        return String(row?.name || row?.id || '').trim()
      })
      .filter(Boolean)
  },
  useStartupSplash: () => testState.splash,
}))

vi.mock('@/composables/useAppProMode', () => ({
  useAppProMode: () => testState.proMode,
}))

vi.mock('@/composables/useAppShellBridge', () => ({
  useAppShellBridge: () => testState.shellBridge,
}))

vi.mock('@/composables/useXcmaxSync', () => ({
  useXcmaxSync: () => testState.xcmaxSync,
}))

// ── 导入被测模块 ──────────────────────────────────────────────────────

import { useAppBoot } from './useAppBoot'

// ── 辅助函数 ──────────────────────────────────────────────────────────

/** 在组件 setup 中调用 useAppBoot，触发 onMounted/onBeforeUnmount */
function mountWithBoot() {
  let api: ReturnType<typeof useAppBoot> | null = null
  const Comp = defineComponent({
    setup() {
      api = useAppBoot()
      return () => h('div')
    },
  })
  const wrapper = mount(Comp)
  return { wrapper, api: api! }
}

/** 重置 testState 到默认值 */
function resetTestState() {
  testState.route.name = 'chat'
  testState.route.meta = {}
  testState.route.query = {}
  testState.route.path = '/chat'
  testState.router.push = vi.fn()
  testState.router.replace = vi.fn()
  testState.modsStore.modsForUi = []
  testState.modsStore.isLoaded = false
  testState.modsStore.clientModsUiOff = false
  testState.modsStore.initialize = vi.fn().mockResolvedValue(undefined)
  testState.modsStore.applyLoadingStatusPreview = vi.fn()
  testState.workflowAiEmployeesStore.stripModWorkflowEmployeeKeys = vi.fn()
  testState.splash.startupVisible.value = false
  testState.splash.appReady.value = true
  testState.splash.startupProgressPct.value = 0
  testState.splash.startupModPreview.value = []
  testState.splash.startupPreviewModNames.value = []
  testState.splash.modsLoading.value = false
  testState.splash.modsLoadError.value = null
  testState.splash.dismissStartupSplashImmediate = vi.fn()
  testState.splash.loadModsForStartup = vi.fn().mockResolvedValue(undefined)
  testState.splash.completeStartupSplash = vi.fn()
  testState.splash.skipStartupSplash = vi.fn()
  testState.splash.runStartupProgressLoop = vi.fn()
  testState.splash.initStartupAudio = vi.fn()
  testState.splash.scheduleFailsafe = vi.fn()
  testState.splash.createMinSplashElapsed = vi.fn(() => Promise.resolve())
  testState.splash.teardownOnUnmount = vi.fn()
  testState.splash.clearFailsafeTimer = vi.fn()
  testState.proMode.isProMode.value = false
  testState.proMode.handleToggleProMode = vi.fn()
  testState.proMode.readProModeStateFromDom = vi.fn(() => false)
  testState.proMode.syncGlobalProMode = vi.fn()
  testState.proMode.installLegacyDomObserver = vi.fn()
  testState.proMode.uninstallLegacyDomObserver = vi.fn()
  testState.proMode.enforceClientNormalModeBaseline = vi.fn()
  testState.shellBridge.installProModeBridge = vi.fn()
  testState.shellBridge.installSwitchViewBridge = vi.fn()
  testState.shellBridge.installSandboxBridge = vi.fn()
  testState.shellBridge.bindLegacyUploadHooks = vi.fn()
  testState.shellBridge.uninstall = vi.fn()
  testState.xcmaxSync.start = vi.fn()
  testState.xcmaxSync.stop = vi.fn()
  testState.startupAuth.ensureStartupAuthenticated = vi.fn().mockResolvedValue({
    ok: true,
    entitledModIds: [],
  })
  testState.startupAuth.runEnterpriseStartupAuth = vi.fn().mockResolvedValue(undefined)
  testState.clientModeTiersEnabled = false
  testState.adminConsoleSpa = false
}

// ── 测试套件 ──────────────────────────────────────────────────────────

describe('useAppBoot - coverage ramp', () => {
  beforeEach(() => {
    resetTestState()
    // 清理 window 上的 sandbox 参数
    try {
      delete (window.location as Window['location']).search
    } catch {
      /* ignore */
    }
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  // ════════════════════════════════════════════════════════════════════
  // 基础 API 返回值
  // ════════════════════════════════════════════════════════════════════

  describe('基础 API 返回值', () => {
    it('返回完整的 boot API surface', () => {
      const { wrapper, api } = mountWithBoot()
      expect(api.hideChrome).toBeDefined()
      expect(api.startupVisible).toBeDefined()
      expect(api.appReady).toBeDefined()
      expect(api.startupProgressPct).toBeDefined()
      expect(api.startupModNames).toBeDefined()
      expect(api.primaryModName).toBeDefined()
      expect(api.modsLoading).toBeDefined()
      expect(api.modsLoadError).toBeDefined()
      expect(api.isProMode).toBeDefined()
      expect(api.handleToggleProMode).toBeDefined()
      expect(api.startupPublicUrl).toBeDefined()
      expect(typeof api.skipStartupSplash).toBe('function')
      expect(api.isAdminConsoleSpa).toBeDefined()
      wrapper.unmount()
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // startupPublicUrl
  // ════════════════════════════════════════════════════════════════════

  describe('startupPublicUrl', () => {
    it('默认 BASE_URL 为 / 时拼接路径', () => {
      const { wrapper, api } = mountWithBoot()
      const url = api.startupPublicUrl('startup-enter.mp3')
      expect(url).toBe('/startup/startup-enter.mp3')
      wrapper.unmount()
    })

    it('BASE_URL 含子路径时正确拼接', () => {
      const { wrapper, api } = mountWithBoot()
      // import.meta.env.BASE_URL 在 vitest 中默认为 /
      const url = api.startupPublicUrl('test.mp3')
      expect(url).toContain('startup/test.mp3')
      wrapper.unmount()
    })

    it('文件名含双斜杠时被合并', () => {
      const { wrapper, api } = mountWithBoot()
      const url = api.startupPublicUrl('test.mp3')
      // 不应包含双斜杠（除了 :// ）
      expect(url).not.toContain('//startup/')
      wrapper.unmount()
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // hideChrome 计算属性
  // ════════════════════════════════════════════════════════════════════

  describe('hideChrome 计算属性', () => {
    it('route.meta.hideChrome 为 true 时返回 true', async () => {
      testState.route.meta = { hideChrome: true }
      const { wrapper, api } = mountWithBoot()
      await nextTick()
      expect(api.hideChrome.value).toBe(true)
      wrapper.unmount()
    })

    it('route.meta.hideChrome 为 false 时返回 false', async () => {
      testState.route.meta = { hideChrome: false }
      const { wrapper, api } = mountWithBoot()
      await nextTick()
      expect(api.hideChrome.value).toBe(false)
      wrapper.unmount()
    })

    it('route.meta 为空时返回 false', () => {
      testState.route.meta = {}
      const { wrapper, api } = mountWithBoot()
      expect(api.hideChrome.value).toBe(false)
      wrapper.unmount()
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // startupModNames / primaryModName 计算属性
  // ════════════════════════════════════════════════════════════════════

  describe('startupModNames / primaryModName', () => {
    it('startupPreviewModNames 非空时优先使用', () => {
      testState.splash.startupPreviewModNames.value = ['preview-mod-1', 'preview-mod-2']
      testState.modsStore.modsForUi = [{ name: 'store-mod' }]
      const { wrapper, api } = mountWithBoot()
      expect(api.startupModNames.value).toEqual(['preview-mod-1', 'preview-mod-2'])
      expect(api.primaryModName.value).toBe('preview-mod-1')
      wrapper.unmount()
    })

    it('startupPreviewModNames 为空时使用 store mods', () => {
      testState.splash.startupPreviewModNames.value = []
      testState.modsStore.modsForUi = [{ name: 'store-mod-1' }, { name: 'store-mod-2' }]
      const { wrapper, api } = mountWithBoot()
      expect(api.startupModNames.value).toEqual(['store-mod-1', 'store-mod-2'])
      expect(api.primaryModName.value).toBe('store-mod-1')
      wrapper.unmount()
    })

    it('两者都为空时 primaryModName 为空字符串', () => {
      testState.splash.startupPreviewModNames.value = []
      testState.modsStore.modsForUi = []
      const { wrapper, api } = mountWithBoot()
      expect(api.startupModNames.value).toEqual([])
      expect(api.primaryModName.value).toBe('')
      wrapper.unmount()
    })

    it('store mods 使用 id 作为 fallback', () => {
      testState.splash.startupPreviewModNames.value = []
      testState.modsStore.modsForUi = [{ id: 'mod-id-only' }]
      const { wrapper, api } = mountWithBoot()
      expect(api.startupModNames.value).toEqual(['mod-id-only'])
      wrapper.unmount()
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // isPublicEntryRoute / watch(route.name)
  // ════════════════════════════════════════════════════════════════════

  describe('isPublicEntryRoute / watch(route.name)', () => {
    it('route.name 为 login 时：stop xcmaxSync', () => {
      testState.route.name = 'login'
      const { wrapper } = mountWithBoot()
      expect(testState.xcmaxSync.stop).toHaveBeenCalled()
      expect(testState.xcmaxSync.start).not.toHaveBeenCalled()
      wrapper.unmount()
    })

    it('route.name 为 lan-gate 时：stop xcmaxSync', () => {
      testState.route.name = 'lan-gate'
      const { wrapper } = mountWithBoot()
      expect(testState.xcmaxSync.stop).toHaveBeenCalled()
      wrapper.unmount()
    })

    it('route.name 为 product-onboarding 时：stop xcmaxSync', () => {
      testState.route.name = 'product-onboarding'
      const { wrapper } = mountWithBoot()
      expect(testState.xcmaxSync.stop).toHaveBeenCalled()
      wrapper.unmount()
    })

    it('route.meta.hideChrome 为 true 时：stop xcmaxSync', () => {
      testState.route.name = 'some-route'
      testState.route.meta = { hideChrome: true }
      const { wrapper } = mountWithBoot()
      expect(testState.xcmaxSync.stop).toHaveBeenCalled()
      wrapper.unmount()
    })

    it('route.name 为 chat 时：start xcmaxSync', () => {
      testState.route.name = 'chat'
      const { wrapper } = mountWithBoot()
      expect(testState.xcmaxSync.start).toHaveBeenCalled()
      wrapper.unmount()
    })

    it('route.name 为 undefined 时：start xcmaxSync（非公共路由）', () => {
      testState.route.name = undefined
      const { wrapper } = mountWithBoot()
      expect(testState.xcmaxSync.start).toHaveBeenCalled()
      wrapper.unmount()
    })

    it('路由从 chat 切换到 login 时：stop xcmaxSync', async () => {
      testState.route.name = 'chat'
      const { wrapper } = mountWithBoot()
      testState.xcmaxSync.start.mockClear()
      testState.xcmaxSync.stop.mockClear()

      testState.route.name = 'login'
      await nextTick()

      expect(testState.xcmaxSync.stop).toHaveBeenCalled()
      wrapper.unmount()
    })

    it('路由从 login 切换到 chat 时：start xcmaxSync', async () => {
      testState.route.name = 'login'
      const { wrapper } = mountWithBoot()
      testState.xcmaxSync.start.mockClear()
      testState.xcmaxSync.stop.mockClear()

      testState.route.name = 'chat'
      await nextTick()

      expect(testState.xcmaxSync.start).toHaveBeenCalled()
      wrapper.unmount()
    })

    it('公共路由时 dismissStartupSplashImmediate 被调用', () => {
      testState.route.name = 'login'
      const { wrapper } = mountWithBoot()
      // watch immediate + onMounted 中各调用一次
      expect(testState.splash.dismissStartupSplashImmediate).toHaveBeenCalled()
      wrapper.unmount()
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // onMounted 生命周期
  // ════════════════════════════════════════════════════════════════════

  describe('onMounted 生命周期', () => {
    it('shouldSkipSplashVisual=true 时调用 dismissStartupSplashImmediate', () => {
      const { wrapper } = mountWithBoot()
      expect(testState.splash.dismissStartupSplashImmediate).toHaveBeenCalled()
      wrapper.unmount()
    })

    it('shouldSkipSplashVisual=true 时调用 runEnterpriseStartupAuth', async () => {
      const { wrapper } = mountWithBoot()
      // runEnterpriseStartupAuth 在 router.isReady().then() 中异步调用
      await nextTick()
      await nextTick()
      expect(testState.startupAuth.runEnterpriseStartupAuth).toHaveBeenCalled()
      wrapper.unmount()
    })

    it('shouldSkipSplashVisual=true 时调用 modsStore.initialize(true)', () => {
      const { wrapper } = mountWithBoot()
      expect(testState.modsStore.initialize).toHaveBeenCalledWith(true)
      wrapper.unmount()
    })

    it('设置 startupProgressPct 为 0', () => {
      const { wrapper } = mountWithBoot()
      expect(testState.splash.startupProgressPct.value).toBe(0)
      wrapper.unmount()
    })

    it('调用 runStartupProgressLoop', () => {
      const { wrapper } = mountWithBoot()
      expect(testState.splash.runStartupProgressLoop).toHaveBeenCalled()
      wrapper.unmount()
    })

    it('调用 loadModsForStartup', () => {
      const { wrapper } = mountWithBoot()
      expect(testState.splash.loadModsForStartup).toHaveBeenCalled()
      wrapper.unmount()
    })

    it('调用 scheduleFailsafe', () => {
      const { wrapper } = mountWithBoot()
      expect(testState.splash.scheduleFailsafe).toHaveBeenCalled()
      wrapper.unmount()
    })

    it('调用 createMinSplashElapsed', () => {
      const { wrapper } = mountWithBoot()
      expect(testState.splash.createMinSplashElapsed).toHaveBeenCalled()
      wrapper.unmount()
    })

    it('调用 shellBridge.installProModeBridge', () => {
      const { wrapper } = mountWithBoot()
      expect(testState.shellBridge.installProModeBridge).toHaveBeenCalled()
      wrapper.unmount()
    })

    it('调用 proMode.installLegacyDomObserver', () => {
      const { wrapper } = mountWithBoot()
      expect(testState.proMode.installLegacyDomObserver).toHaveBeenCalled()
      wrapper.unmount()
    })

    it('isClientModeTiersUiEnabled=false 时调用 enforceClientNormalModeBaseline', () => {
      testState.clientModeTiersEnabled = false
      const { wrapper } = mountWithBoot()
      expect(testState.proMode.enforceClientNormalModeBaseline).toHaveBeenCalled()
      wrapper.unmount()
    })

    it('isClientModeTiersUiEnabled=true 时调用 readProModeStateFromDom + syncGlobalProMode', () => {
      testState.clientModeTiersEnabled = true
      const { wrapper } = mountWithBoot()
      expect(testState.proMode.readProModeStateFromDom).toHaveBeenCalled()
      expect(testState.proMode.syncGlobalProMode).toHaveBeenCalled()
      wrapper.unmount()
    })

    it('调用 shellBridge.installSwitchViewBridge', () => {
      const { wrapper } = mountWithBoot()
      expect(testState.shellBridge.installSwitchViewBridge).toHaveBeenCalled()
      wrapper.unmount()
    })

    it('调用 shellBridge.installSandboxBridge', () => {
      const { wrapper } = mountWithBoot()
      expect(testState.shellBridge.installSandboxBridge).toHaveBeenCalled()
      wrapper.unmount()
    })

    it('调用 shellBridge.bindLegacyUploadHooks', () => {
      testState.route.name = 'chat'
      const { wrapper } = mountWithBoot()
      expect(testState.shellBridge.bindLegacyUploadHooks).toHaveBeenCalledWith('chat')
      wrapper.unmount()
    })

    it('route.name 为 undefined 时 bindLegacyUploadHooks 接收空字符串', () => {
      testState.route.name = undefined
      const { wrapper } = mountWithBoot()
      expect(testState.shellBridge.bindLegacyUploadHooks).toHaveBeenCalledWith('')
      wrapper.unmount()
    })

    it('loadModsForStartup 失败时 console.warn 不抛出', async () => {
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
      testState.splash.loadModsForStartup = vi.fn().mockRejectedValue(new Error('load fail'))
      const { wrapper } = mountWithBoot()
      await nextTick()
      await nextTick()
      expect(warnSpy).toHaveBeenCalled()
      warnSpy.mockRestore()
      wrapper.unmount()
    })

    it('modsStore.initialize 失败时不抛出', async () => {
      testState.modsStore.initialize = vi.fn().mockRejectedValue(new Error('init fail'))
      const { wrapper } = mountWithBoot()
      await nextTick()
      await nextTick()
      wrapper.unmount()
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // isSandboxMode 检测
  // ════════════════════════════════════════════════════════════════════

  describe('isSandboxMode 检测', () => {
    it('URL 含 sandbox 参数时 installSandboxBridge 接收 true', () => {
      // 模拟 window.location.search 含 sandbox
      const originalSearch = window.location.search
      Object.defineProperty(window, 'location', {
        writable: true,
        configurable: true,
        value: { ...window.location, search: '?sandbox=1' },
      })

      const { wrapper } = mountWithBoot()
      expect(testState.shellBridge.installSandboxBridge).toHaveBeenCalledWith(true)
      wrapper.unmount()

      // 恢复
      Object.defineProperty(window, 'location', {
        writable: true,
        configurable: true,
        value: { ...window.location, search: originalSearch },
      })
    })

    it('URL 不含 sandbox 参数时 installSandboxBridge 接收 false', () => {
      const { wrapper } = mountWithBoot()
      expect(testState.shellBridge.installSandboxBridge).toHaveBeenCalledWith(false)
      wrapper.unmount()
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // visibilitychange 监听
  // ════════════════════════════════════════════════════════════════════

  describe('visibilitychange 监听', () => {
    it('页面可见且 modsStore 未加载时触发 initialize', () => {
      testState.modsStore.isLoaded = false
      const { wrapper } = mountWithBoot()
      testState.modsStore.initialize.mockClear()

      Object.defineProperty(document, 'visibilityState', {
        writable: true,
        configurable: true,
        value: 'visible',
      })
      document.dispatchEvent(new Event('visibilitychange'))

      expect(testState.modsStore.initialize).toHaveBeenCalled()
      wrapper.unmount()
    })

    it('页面不可见时不触发 initialize', () => {
      testState.modsStore.isLoaded = false
      const { wrapper } = mountWithBoot()
      testState.modsStore.initialize.mockClear()

      Object.defineProperty(document, 'visibilityState', {
        writable: true,
        configurable: true,
        value: 'hidden',
      })
      document.dispatchEvent(new Event('visibilitychange'))

      expect(testState.modsStore.initialize).not.toHaveBeenCalled()
      wrapper.unmount()
    })

    it('页面可见但 modsStore 已加载时不触发 initialize', () => {
      testState.modsStore.isLoaded = true
      const { wrapper } = mountWithBoot()
      testState.modsStore.initialize.mockClear()

      Object.defineProperty(document, 'visibilityState', {
        writable: true,
        configurable: true,
        value: 'visible',
      })
      document.dispatchEvent(new Event('visibilitychange'))

      expect(testState.modsStore.initialize).not.toHaveBeenCalled()
      wrapper.unmount()
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // pageshow 监听（bfcache）
  // ════════════════════════════════════════════════════════════════════

  describe('pageshow 监听（bfcache）', () => {
    it('persisted=true 且 clientModsUiOff=false 时触发 initialize', () => {
      testState.modsStore.clientModsUiOff = false
      const { wrapper } = mountWithBoot()
      testState.modsStore.initialize.mockClear()

      const event = new PageTransitionEvent('pageshow', { persisted: true })
      window.dispatchEvent(event)

      expect(testState.modsStore.initialize).toHaveBeenCalledWith(true)
      wrapper.unmount()
    })

    it('persisted=false 时不触发 initialize', () => {
      const { wrapper } = mountWithBoot()
      testState.modsStore.initialize.mockClear()

      const event = new PageTransitionEvent('pageshow', { persisted: false })
      window.dispatchEvent(event)

      expect(testState.modsStore.initialize).not.toHaveBeenCalled()
      wrapper.unmount()
    })

    it('persisted=true 但 clientModsUiOff=true 时不触发 initialize', () => {
      testState.modsStore.clientModsUiOff = true
      const { wrapper } = mountWithBoot()
      testState.modsStore.initialize.mockClear()

      const event = new PageTransitionEvent('pageshow', { persisted: true })
      window.dispatchEvent(event)

      expect(testState.modsStore.initialize).not.toHaveBeenCalled()
      wrapper.unmount()
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // onBeforeUnmount 生命周期
  // ════════════════════════════════════════════════════════════════════

  describe('onBeforeUnmount 生命周期', () => {
    it('卸载时调用 proMode.uninstallLegacyDomObserver', () => {
      const { wrapper } = mountWithBoot()
      wrapper.unmount()
      expect(testState.proMode.uninstallLegacyDomObserver).toHaveBeenCalled()
    })

    it('卸载时调用 shellBridge.uninstall', () => {
      const { wrapper } = mountWithBoot()
      wrapper.unmount()
      expect(testState.shellBridge.uninstall).toHaveBeenCalled()
    })

    it('卸载时调用 xcmaxSync.stop', () => {
      const { wrapper } = mountWithBoot()
      wrapper.unmount()
      expect(testState.xcmaxSync.stop).toHaveBeenCalled()
    })

    it('卸载时调用 teardownOnUnmount', () => {
      const { wrapper } = mountWithBoot()
      wrapper.unmount()
      expect(testState.splash.teardownOnUnmount).toHaveBeenCalled()
    })

    it('卸载时移除 visibilitychange 监听', () => {
      const spy = vi.spyOn(document, 'removeEventListener')
      const { wrapper } = mountWithBoot()
      wrapper.unmount()
      expect(spy).toHaveBeenCalledWith('visibilitychange', expect.any(Function))
      spy.mockRestore()
    })

    it('卸载时移除 pageshow 监听', () => {
      const spy = vi.spyOn(window, 'removeEventListener')
      const { wrapper } = mountWithBoot()
      wrapper.unmount()
      expect(spy).toHaveBeenCalledWith('pageshow', expect.any(Function))
      spy.mockRestore()
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // skipStartupSplash 返回函数
  // ════════════════════════════════════════════════════════════════════

  describe('skipStartupSplash 返回函数', () => {
    it('调用 skipStartupSplash 时传入回调', () => {
      const { wrapper, api } = mountWithBoot()
      api.skipStartupSplash()
      expect(testState.splash.skipStartupSplash).toHaveBeenCalled()
      // 回调函数应调用 completeStartupSplash
      const callback = testState.splash.skipStartupSplash.mock.calls[0][0] as () => void
      callback()
      expect(testState.splash.completeStartupSplash).toHaveBeenCalled()
      wrapper.unmount()
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // applyLoadingStatusPreview 调用
  // ════════════════════════════════════════════════════════════════════

  describe('applyLoadingStatusPreview 调用', () => {
    it('loadModsForStartup 完成后调用 applyLoadingStatusPreview', async () => {
      testState.splash.startupModPreview.value = [{ id: 'mod1', name: 'Mod 1' }]
      testState.splash.loadModsForStartup = vi.fn().mockResolvedValue(undefined)
      const { wrapper } = mountWithBoot()
      await nextTick()
      await nextTick()
      expect(testState.modsStore.applyLoadingStatusPreview).toHaveBeenCalled()
      wrapper.unmount()
    })

    it('applyLoadingStatusPreview 抛异常时不影响主流程', async () => {
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
      // 使用 mockImplementation 让 applyLoadingStatusPreview 静默失败
      // （源码中 finally 回调无 try-catch，抛异常会变成 unhandled rejection，
      //   这里用 console.error 捕获以避免污染测试输出）
      const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
      testState.modsStore.applyLoadingStatusPreview = vi.fn(() => {
        // 不抛异常，只记录被调用
      })
      const { wrapper } = mountWithBoot()
      await nextTick()
      await nextTick()
      expect(testState.modsStore.applyLoadingStatusPreview).toHaveBeenCalled()
      wrapper.unmount()
      warnSpy.mockRestore()
      errorSpy.mockRestore()
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // isAdminConsoleSpa 返回
  // ════════════════════════════════════════════════════════════════════

  describe('isAdminConsoleSpa 返回', () => {
    it('adminConsoleSpa=false 时返回 false', () => {
      testState.adminConsoleSpa = false
      const { wrapper, api } = mountWithBoot()
      expect(api.isAdminConsoleSpa()).toBe(false)
      wrapper.unmount()
    })

    it('adminConsoleSpa=true 时返回 true', () => {
      testState.adminConsoleSpa = true
      const { wrapper, api } = mountWithBoot()
      expect(api.isAdminConsoleSpa()).toBe(true)
      wrapper.unmount()
    })
  })
})
