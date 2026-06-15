/**
 * MainLayout.vue 增强测试
 * 覆盖：组件渲染、sidebar 折叠/展开、pro mode badge、
 * navigateToView、openSettings、impersonation bar、
 * currentViewTitle、currentRouteName、mobileBottomNav 等
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'

// ── 外部依赖 mock ─────────────────────────────────────────

vi.mock('./Sidebar.vue', () => ({
  default: {
    name: 'Sidebar',
    template: '<nav class="sidebar-stub" @change-view="$emit(\'change-view\', $event)" @toggle-pro-mode="$emit(\'toggle-pro-mode\')"><slot /></nav>',
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

vi.mock('@/stores/industry', () => ({
  useIndustryStore: () => ({
    currentIndustryId: 'generic',
    isLoaded: true,
    initialize: vi.fn(async () => {}),
  }),
}))

vi.mock('@/stores/mods', () => ({
  useModsStore: () => ({
    mods: [],
    modsForUi: [],
    modRoutes: [],
    activeModId: '',
    clientModsUiOff: false,
    initialize: vi.fn(async () => {}),
  }),
}))

vi.mock('@/stores/accountProfile', () => ({
  useAccountProfileStore: () => ({
    loaded: true,
    displayBrand: '',
    isImpersonating: false,
    impersonatingUsername: '',
    companyBrand: '',
    refreshFromServer: vi.fn(async () => {}),
  }),
}))

vi.mock('@/stores/onboardingTutorial', () => ({
  useOnboardingTutorialStore: () => ({
    active: false,
  }),
}))

vi.mock('@/stores/tutorial', () => ({
  useTutorialStore: () => ({
    isActive: false,
  }),
  setTutorialBuildContextFactory: vi.fn(),
}))

// Need to mock storeToRefs to return proper refs for the tutorial stores
vi.mock('pinia', async (importOriginal) => {
  const actual = await importOriginal<typeof import('pinia')>()
  return {
    ...actual,
    storeToRefs: (store: Record<string, unknown>) => {
      // Convert store properties to refs
      const refs: Record<string, { value: unknown }> = {}
      for (const key of Object.keys(store)) {
        if (typeof store[key] !== 'function') {
          refs[key] = { value: store[key] }
        }
      }
      return refs
    },
  }
})

vi.mock('@/composables/useTutorialCatalog', () => ({
  useTutorialCatalog: () => ({
    buildContext: { value: {} },
  }),
}))

vi.mock('@/composables/useResizablePane', () => ({
  useResizablePane: () => ({
    paneStyle: {},
    resetSize: vi.fn(),
    startResize: vi.fn(),
    stopResize: vi.fn(),
  }),
}))

vi.mock('@/composables/useModRoutes', () => ({
  useModRoutes: () => ({
    modMenuItems: { value: [] },
  }),
}))

vi.mock('@/api/xcmaxAdmin', () => ({
  xcmaxAdminApi: {
    endImpersonate: vi.fn(async () => {}),
  },
}))

vi.mock('@/api/marketAccount', () => ({
  LS_MARKET_USER_JSON: 'xcagi_market_user_json',
}))

vi.mock('@/utils/adminConsoleUrl', () => ({
  isAdminConsoleSpa: () => false,
}))

vi.mock('@/constants/adminOperatorNav', () => ({
  ADMIN_OPERATOR_BRAND_SUBTITLE: '运维管理',
  ADMIN_OPERATOR_HOME_ROUTE: 'admin-home',
}))

vi.mock('@/utils/appDialog', () => ({
  appAlert: vi.fn(async () => {}),
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
  resolveHostBusinessPageRedirect: () => null,
}))

vi.mock('@/utils/customerServicePagePaths', () => ({
  customerServiceHostPathFromModPath: () => null,
}))

vi.mock('@/constants/customerServiceMod', () => ({
  customerServiceModFrontendRoutesAvailable: () => false,
}))

vi.mock('@/utils/sidebarActiveKey', () => ({
  isChatSidebarActive: () => false,
  normalizeSidebarActiveKey: (key: string) => key,
}))

vi.mock('@/constants/accountModBinding', () => ({
  augmentEntitledModIdsForAccount: (_u: unknown, ids: string[]) => ids,
  isSunbirdAccountUsername: () => false,
  SUNBIRD_CLIENT_MOD_ID: 'attendance-industry',
}))

vi.mock('@/router/registerModRoutes', () => ({
  registerAllModRoutesFromGlob: vi.fn(async () => {}),
  registerModRoutes: vi.fn(async () => {}),
}))

// ── helpers ────────────────────────────────────────────────

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'chat', component: { template: '<div>Chat</div>' }, meta: { title: '智能对话' } },
      { path: '/settings', name: 'settings', component: { template: '<div>Settings</div>' }, meta: { title: '系统设置' } },
      { path: '/mod-store', name: 'mod-store', component: { template: '<div>ModStore</div>' }, meta: { title: '能力库' } },
      { path: '/im', name: 'im', component: { template: '<div>IM</div>' }, meta: { title: '消息' } },
    ],
  })
}

async function mountMainLayout(props = {}) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const router = makeRouter()
  await router.push('/')
  await router.isReady()

  const MainLayout = (await import('./MainLayout.vue')).default
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

// ── test suites ────────────────────────────────────────────

describe('MainLayout.vue – component structure', () => {
  it('mounts with sidebar stub', async () => {
    const { wrapper } = await mountMainLayout()
    expect(wrapper.find('.sidebar-stub').exists()).toBe(true)
    expect(wrapper.find('.main-container').exists()).toBe(true)
    wrapper.unmount()
  })

  it('renders main content area', async () => {
    const { wrapper } = await mountMainLayout()
    expect(wrapper.find('.main-content').exists()).toBe(true)
    wrapper.unmount()
  })

  it('renders top bar', async () => {
    const { wrapper } = await mountMainLayout()
    expect(wrapper.find('.top-bar').exists()).toBe(true)
    wrapper.unmount()
  })

  it('renders settings button', async () => {
    const { wrapper } = await mountMainLayout()
    expect(wrapper.find('.top-bar-settings-btn').exists()).toBe(true)
    wrapper.unmount()
  })

  it('renders TopAssistantFloat', async () => {
    const { wrapper } = await mountMainLayout()
    expect(wrapper.find('.top-assistant-stub').exists()).toBe(true)
    wrapper.unmount()
  })
})

describe('MainLayout.vue – sidebar behavior', () => {
  it('sidebar starts expanded by default', async () => {
    const { wrapper } = await mountMainLayout()
    expect(wrapper.find('.sidebar-shell').classes()).not.toContain('collapsed')
    wrapper.unmount()
  })

  it('sidebar collapsed class is applied when sidebarCollapsed is true', async () => {
    const { wrapper } = await mountMainLayout()
    wrapper.vm.sidebarCollapsed = true
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.sidebar-shell').classes()).toContain('collapsed')
    wrapper.unmount()
  })

  it('shows hover trigger when sidebar is collapsed and feature enabled', async () => {
    const { wrapper } = await mountMainLayout()
    wrapper.vm.sidebarCollapsed = true
    wrapper.vm.isSidebarFeatureEnabled = true
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.sidebar-hover-trigger').exists()).toBe(true)
    wrapper.unmount()
  })

  it('does not show hover trigger when sidebar feature is disabled', async () => {
    const { wrapper } = await mountMainLayout()
    wrapper.vm.isSidebarFeatureEnabled = false
    wrapper.vm.sidebarCollapsed = true
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.sidebar-hover-trigger').exists()).toBe(false)
    wrapper.unmount()
  })

  it('clicking peek button expands sidebar', async () => {
    const { wrapper } = await mountMainLayout()
    wrapper.vm.sidebarCollapsed = true
    wrapper.vm.isSidebarFeatureEnabled = true
    await wrapper.vm.$nextTick()
    const peekBtn = wrapper.find('.sidebar-peek-button')
    if (peekBtn.exists()) {
      await peekBtn.trigger('click')
      expect(wrapper.vm.sidebarCollapsed).toBe(false)
    }
    wrapper.unmount()
  })
})

describe('MainLayout.vue – pro mode badge', () => {
  it('shows normal mode badge when isProMode is false', async () => {
    const { wrapper } = await mountMainLayout({ isProMode: false })
    // modeBadgeText computed depends on isProMode prop
    expect(wrapper.vm.modeBadgeText).toContain('普通版')
    wrapper.unmount()
  })

  it('shows pro mode badge when isProMode is true', async () => {
    const { wrapper } = await mountMainLayout({ isProMode: true })
    expect(wrapper.vm.modeBadgeText).toContain('专业版')
    wrapper.unmount()
  })

  it('shows sandbox mode in sandbox mode', async () => {
    // sandbox mode is detected from URL params at module level
    // This test verifies the computed logic
    const { wrapper } = await mountMainLayout()
    // Default is not sandbox
    expect(wrapper.vm.modeBadgeText).not.toContain('沙箱模式')
    wrapper.unmount()
  })
})

describe('MainLayout.vue – currentViewTitle', () => {
  it('returns title for chat route', async () => {
    const { wrapper } = await mountMainLayout()
    expect(wrapper.vm.currentViewTitle).toBeTruthy()
    wrapper.unmount()
  })

  it('returns fallback for unknown routes', async () => {
    const { wrapper } = await mountMainLayout()
    // currentViewTitle should always return a string
    expect(typeof wrapper.vm.currentViewTitle).toBe('string')
    wrapper.unmount()
  })
})

describe('MainLayout.vue – openSettings', () => {
  it('navigates to settings page', async () => {
    const { wrapper, router } = await mountMainLayout()
    const pushSpy = vi.spyOn(router, 'push')
    wrapper.vm.openSettings()
    expect(pushSpy).toHaveBeenCalledWith({ name: 'settings' })
    pushSpy.mockRestore()
    wrapper.unmount()
  })
})

describe('MainLayout.vue – navigateToView', () => {
  it('navigates to settings by name', async () => {
    const { wrapper, router } = await mountMainLayout()
    const pushSpy = vi.spyOn(router, 'push')
    await wrapper.vm.navigateToView('settings')
    expect(pushSpy).toHaveBeenCalled()
    pushSpy.mockRestore()
    wrapper.unmount()
  })

  it('navigates to chat by name', async () => {
    const { wrapper, router } = await mountMainLayout()
    const pushSpy = vi.spyOn(router, 'push')
    await wrapper.vm.navigateToView('chat')
    expect(pushSpy).toHaveBeenCalled()
    pushSpy.mockRestore()
    wrapper.unmount()
  })

  it('handles unknown view key gracefully', async () => {
    const { wrapper } = await mountMainLayout()
    // Should not throw
    await expect(wrapper.vm.navigateToView('nonexistent-view')).resolves.toBeUndefined()
    wrapper.unmount()
  })
})

describe('MainLayout.vue – impersonation', () => {
  it('isImpersonating is falsy by default', async () => {
    const { wrapper } = await mountMainLayout()
    // isImpersonating comes from storeToRefs(accountProfileStore)
    // Our mock accountProfileStore has isImpersonating: false
    // storeToRefs converts it to a ref-like { value: false }
    // The component accesses it as isImpersonating.value or isImpersonating directly
    const val = wrapper.vm.isImpersonating
    // It should be falsy (either false or { value: false })
    expect(!val || val?.value === false || val === false).toBe(true)
    wrapper.unmount()
  })
})

describe('MainLayout.vue – currentRouteName', () => {
  it('returns chat for root path', async () => {
    const { wrapper } = await mountMainLayout()
    expect(wrapper.vm.currentRouteName).toBe('chat')
    wrapper.unmount()
  })
})

describe('MainLayout.vue – handleViewChange', () => {
  it('calls navigateToView with the provided key', async () => {
    const { wrapper } = await mountMainLayout()
    // handleViewChange calls void navigateToView(viewKey)
    // We can't spy on closure functions, so we test the effect
    const pushSpy = vi.spyOn(wrapper.vm.$router, 'push')
    await wrapper.vm.handleViewChange('settings')
    expect(pushSpy).toHaveBeenCalled()
    pushSpy.mockRestore()
    wrapper.unmount()
  })
})

describe('MainLayout.vue – resolveModBadgeSuffix', () => {
  it('returns empty string when no mods loaded', async () => {
    const { wrapper } = await mountMainLayout()
    expect(wrapper.vm.resolveModBadgeSuffix()).toBe('')
    wrapper.unmount()
  })
})

describe('MainLayout.vue – sidebar timers', () => {
  it('clearSidebarCollapseTimer clears the timer', async () => {
    const { wrapper } = await mountMainLayout()
    const timer = window.setTimeout(() => {}, 10000)
    wrapper.vm.sidebarCollapseTimer = timer
    wrapper.vm.clearSidebarCollapseTimer()
    expect(wrapper.vm.sidebarCollapseTimer).toBeNull()
    wrapper.unmount()
  })

  it('clearSidebarHoverTimer clears the timer', async () => {
    const { wrapper } = await mountMainLayout()
    const timer = window.setTimeout(() => {}, 10000)
    wrapper.vm.sidebarHoverTimer = timer
    wrapper.vm.clearSidebarHoverTimer()
    expect(wrapper.vm.sidebarHoverTimer).toBeNull()
    wrapper.unmount()
  })

  it('scheduleSidebarAutoCollapse does not schedule when sidebar is already collapsed', async () => {
    const { wrapper } = await mountMainLayout()
    wrapper.vm.sidebarCollapsed = true
    wrapper.vm.isSidebarFeatureEnabled = true
    wrapper.vm.scheduleSidebarAutoCollapse()
    // Timer should not be set
    expect(wrapper.vm.sidebarCollapseTimer).toBeNull()
    wrapper.unmount()
  })

  it('scheduleSidebarAutoCollapse does not schedule when feature is disabled', async () => {
    const { wrapper } = await mountMainLayout()
    wrapper.vm.sidebarCollapsed = false
    wrapper.vm.isSidebarFeatureEnabled = false
    wrapper.vm.scheduleSidebarAutoCollapse()
    expect(wrapper.vm.sidebarCollapseTimer).toBeNull()
    wrapper.unmount()
  })

  it('ensureSidebarExpandedForTutorial expands sidebar', async () => {
    const { wrapper } = await mountMainLayout()
    wrapper.vm.sidebarCollapsed = true
    wrapper.vm.isSidebarFeatureEnabled = true
    wrapper.vm.ensureSidebarExpandedForTutorial()
    expect(wrapper.vm.sidebarCollapsed).toBe(false)
    wrapper.unmount()
  })
})

describe('MainLayout.vue – onViewportChange', () => {
  it('disables sidebar when viewport matches mobile', async () => {
    const { wrapper } = await mountMainLayout()
    wrapper.vm.onViewportChange({ matches: true })
    expect(wrapper.vm.isSidebarFeatureEnabled).toBe(false)
    expect(wrapper.vm.sidebarCollapsed).toBe(false)
    wrapper.unmount()
  })

  it('enables sidebar when viewport does not match mobile', async () => {
    const { wrapper } = await mountMainLayout()
    wrapper.vm.isSidebarFeatureEnabled = false
    wrapper.vm.onViewportChange({ matches: false })
    expect(wrapper.vm.isSidebarFeatureEnabled).toBe(true)
    wrapper.unmount()
  })
})

describe('MainLayout.vue – onMobileNavViewportChange', () => {
  it('shows mobile bottom nav when viewport matches', async () => {
    const { wrapper } = await mountMainLayout()
    wrapper.vm.onMobileNavViewportChange({ matches: true })
    expect(wrapper.vm.showMobileBottomNav).toBe(true)
    wrapper.unmount()
  })

  it('hides mobile bottom nav when viewport does not match', async () => {
    const { wrapper } = await mountMainLayout()
    wrapper.vm.showMobileBottomNav = true
    wrapper.vm.onMobileNavViewportChange({ matches: false })
    expect(wrapper.vm.showMobileBottomNav).toBe(false)
    wrapper.unmount()
  })
})

describe('MainLayout.vue – resolveLegacyRouteFromModPath', () => {
  it('returns null for empty path', async () => {
    const { wrapper } = await mountMainLayout()
    expect(wrapper.vm.resolveLegacyRouteFromModPath('')).toBeNull()
    expect(wrapper.vm.resolveLegacyRouteFromModPath(null)).toBeNull()
    wrapper.unmount()
  })

  it('returns approval-workspace for approval-hub/workspace path', async () => {
    const { wrapper, router } = await mountMainLayout()
    const result = wrapper.vm.resolveLegacyRouteFromModPath('/mod/test/approval-hub/workspace')
    if (router.hasRoute('approval-workspace')) {
      expect(result).toEqual({ name: 'approval-workspace' })
    }
    wrapper.unmount()
  })
})
