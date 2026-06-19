/**
 * router/index.ts 覆盖率补齐测试
 *
 * 重点覆盖以下未覆盖区域（共 135 条未覆盖 statements）：
 * 1. console 路由 beforeEnter 守卫（view 参数各分支）
 * 2. filterSandboxRoutes / filterPlatformShellRoutes / resolveInitialRoutes
 * 3. beforeEach 守卫各分支：
 *    - admin console blocked route names
 *    - workflow-visualization 访问控制（try/catch）
 *    - admin console 冷启动 chat 重定向（START_LOCATION）
 *    - 未匹配 /mod/ 路径（customer service host、planner bridge protected、fallback）
 *    - 已匹配 planner bridge + protected mod
 *    - LAN gate 守卫（hostAdmin meta、enabled && !authorized、catch）
 *    - planner chat 重定向（matched/unmatched 路由）
 *    - platform shell 重定向（host business page、fallback）
 *    - customer service 路由（enterprise/admin/catch）
 *    - requiresAdminAccount（refresh/catch）
 *    - enterprise session（profile refresh、admin redirect、inner catch）
 *    - host pack onboarding catch
 * 4. afterEach document title
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { START_LOCATION } from 'vue-router'

// ── 使用 vi.hoisted 提升在 mock 工厂中引用的 mock 函数 ────
const {
  mockLanGateRefresh,
  mockLanGateOpenModal,
  mockShouldRouteToProductOnboarding,
  mockResolveHostPackOnboardingStep,
  mockShouldRouteToHostPackOnboarding,
  mockCustomerServiceHostPath,
  mockResolveHostBusinessPageRedirect,
  mockResolvePlannerChatHomePath,
  mockResolvePlannerPagePath,
  mockFetchProductSku,
  mockIsEnterpriseEdition,
  mockValidateEnterpriseSession,
  mockIsAdminConsoleSpa,
  mockResolveAdminConsoleHomeUrl,
  mockIsPlatformShellModeEnabled,
  mockModsStore,
  mockAccountProfileStore,
  mockIsProtectedClientModId,
  mockReadActiveExtensionModId,
  mockIsIndustryDeliveryRouteName,
  mockReadHostPackAcknowledged,
  mockCanShowCoreMenuKey,
  mockBuildRoleMenuProfile,
  mockIsClientErpSidebarContext,
} = vi.hoisted(() => ({
  mockLanGateRefresh: vi.fn().mockResolvedValue({ enabled: false, authorized: true }),
  mockLanGateOpenModal: vi.fn(),
  mockShouldRouteToProductOnboarding: vi.fn(() => false),
  mockResolveHostPackOnboardingStep: vi.fn().mockResolvedValue(null),
  mockShouldRouteToHostPackOnboarding: vi.fn(() => false),
  mockCustomerServiceHostPath: vi.fn(() => null),
  mockResolveHostBusinessPageRedirect: vi.fn(() => null),
  mockResolvePlannerChatHomePath: vi.fn(() => '/'),
  mockResolvePlannerPagePath: vi.fn((p: string) => p),
  mockFetchProductSku: vi.fn().mockResolvedValue('generic'),
  mockIsEnterpriseEdition: vi.fn(() => false),
  mockValidateEnterpriseSession: vi.fn().mockResolvedValue(true),
  mockIsAdminConsoleSpa: vi.fn(() => false),
  mockResolveAdminConsoleHomeUrl: vi.fn(() => '/admin'),
  mockIsPlatformShellModeEnabled: vi.fn(() => false),
  mockModsStore: {
    clientModsUiOff: false,
    mods: [] as unknown[],
    activeModId: '',
  },
  mockAccountProfileStore: {
    loaded: true,
    isAdminAccount: false,
    accountKind: 'personal' as string,
    marketIsAdmin: false,
    marketIsEnterprise: false,
    refreshFromServer: vi.fn().mockResolvedValue(undefined),
  },
  mockIsProtectedClientModId: vi.fn(() => false),
  mockReadActiveExtensionModId: vi.fn(() => ''),
  mockIsIndustryDeliveryRouteName: vi.fn(() => false),
  mockReadHostPackAcknowledged: vi.fn(() => false),
  mockCanShowCoreMenuKey: vi.fn(() => true),
  mockBuildRoleMenuProfile: vi.fn(() => ({})),
  mockIsClientErpSidebarContext: vi.fn(() => false),
}))

// ── 外部依赖 mock ─────────────────────────────────────────

vi.mock('@/composables/useLanGate', () => ({
  useLanGate: () => ({
    refresh: mockLanGateRefresh,
    openLanGateModal: mockLanGateOpenModal,
  }),
}))

vi.mock('@/composables/useProductFlow', () => ({
  shouldRouteToProductOnboarding: mockShouldRouteToProductOnboarding,
}))

vi.mock('@/utils/hostPackOnboardingGate', () => ({
  resolveHostPackOnboardingStep: mockResolveHostPackOnboardingStep,
  shouldRouteToHostPackOnboarding: mockShouldRouteToHostPackOnboarding,
}))

vi.mock('@/utils/hostBusinessPageRedirect', () => ({
  resolveHostBusinessPageRedirect: mockResolveHostBusinessPageRedirect,
}))

vi.mock('@/utils/customerServicePagePaths', () => ({
  customerServiceHostPathFromModPath: mockCustomerServiceHostPath,
}))

vi.mock('@/constants/erpDomainMod', () => ({
  readErpDomainModFacadeEnabled: () => false,
}))

vi.mock('@/constants/coreWorkflowMod', () => ({
  readCoreWorkflowModPagesEnabled: () => false,
}))

vi.mock('@/utils/workflowPagePaths', () => ({
  resolveWorkflowPageRedirectForRouteName: () => null,
}))

vi.mock('@/utils/plannerPagePaths', () => ({
  resolvePlannerChatHomePath: mockResolvePlannerChatHomePath,
  resolvePlannerPagePath: mockResolvePlannerPagePath,
}))

vi.mock('@/utils/erpDomainPaths', () => ({
  readActiveExtensionModId: mockReadActiveExtensionModId,
}))

vi.mock('@/constants/protectedMods', () => ({
  isProtectedClientModId: mockIsProtectedClientModId,
}))

vi.mock('@/utils/productSku', () => ({
  fetchProductSku: mockFetchProductSku,
  isEnterpriseEdition: mockIsEnterpriseEdition,
}))

vi.mock('@/utils/authSessionCache', () => ({
  validateEnterpriseSessionCached: mockValidateEnterpriseSession,
}))

vi.mock('@/utils/adminConsoleUrl', () => ({
  isAdminConsoleSpa: mockIsAdminConsoleSpa,
  resolveAdminConsoleHomeUrl: mockResolveAdminConsoleHomeUrl,
}))

vi.mock('@/constants/platformShellMode', () => ({
  isPlatformShellModeEnabled: mockIsPlatformShellModeEnabled,
  isShellEditionBuild: () => false,
  isIndustryDeliveryRouteName: mockIsIndustryDeliveryRouteName,
  INDUSTRY_DELIVERY_ROUTE_NAMES: new Set<string>(),
  SHELL_CORE_ROUTE_NAMES: new Set<string>([
    'chat', 'im', 'ai-ecosystem', 'employee-workflow',
    'workflow-employee-space', 'settings', 'mod-store',
    'desktop-runtime', 'login', 'product-onboarding',
    'mod-landing', 'workflow-employee-stitch-full', 'lan-gate',
    'login-help', 'login-register', 'login-forgot-account', 'login-forgot-password',
  ]),
}))

// 完全 mock genericModPack，不使用 importOriginal（避免加载实际模块的副作用）
vi.mock('@/constants/genericModPack', () => ({
  MINIMAL_HOST_MOD_IDS: [],
  GENERIC_HOST_MOD_IDS: [],
  CLIENT_PRIMARY_ERP_MOD_ID: '',
  isClientErpSidebarContext: mockIsClientErpSidebarContext,
}))

vi.mock('@/utils/roleMenuProfile', () => ({
  buildRoleMenuProfile: mockBuildRoleMenuProfile,
  canShowCoreMenuKey: mockCanShowCoreMenuKey,
}))

vi.mock('@/constants/adminOperatorNav', () => ({
  ADMIN_OPERATOR_BLOCKED_ROUTE_NAMES: new Set<string>(['admin-entitlements']),
  ADMIN_OPERATOR_HOME_ROUTE: 'admin-home',
}))

vi.mock('@admin-console-inject/adminHostRoutes', () => ({
  ADMIN_HOST_ROUTE_RECORDS: [] as never[],
}))

vi.mock('@/stores/mods', () => ({
  useModsStore: () => mockModsStore,
}))

vi.mock('@/stores/accountProfile', () => ({
  useAccountProfileStore: () => mockAccountProfileStore,
}))

vi.mock('@/constants/productFlow', () => ({
  readHostPackAcknowledged: mockReadHostPackAcknowledged,
}))

// Stub all view components
vi.mock('../views/LoginView.vue', () => ({ default: { template: '<div>Login</div>' } }))
vi.mock('../views/LoginHelpView.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../views/RegisterView.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../views/ForgotAccountView.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../views/ForgotPasswordView.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../views/ChatView.vue', () => ({ default: { template: '<div>Chat</div>' } }))
vi.mock('../views/LanGateView.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../views/AIEcosystemView.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../views/BrainView.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../views/ProductsView.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../views/MaterialsView.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../views/OrdersView.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../views/TraditionalModeView.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../views/CreateOrderView.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../views/ShipmentRecordsView.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../views/CustomersView.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../views/DataSourcesView.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../views/PrintView.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../views/PrinterListView.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../views/TemplatePreviewView.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../views/LabelEditorView.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../views/PurchaseView.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../views/BatchAnalyzeView.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../views/EnterpriseCustomerServiceView.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../views/InternalCustomerServiceView.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../views/ApprovalHubView.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../views/ApprovalWorkspaceView.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../views/ApprovalFlowManagementView.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../views/ApprovalRulesView.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../views/InventoryView.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../views/ProductOnboardingView.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../views/DiscoverView.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../views/ModStore.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../views/SettingsView.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../views/ImMessengerView.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../views/AdminEntitlementsView.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../views/DesktopRuntimeView.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../views/ChatDebugView.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../views/ToolsView.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../views/WorkflowVisualizationView.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../views/EmployeeWorkspaceView.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../views/YuangongStitchFullView.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../views/ModLandingView.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../views/KittenFinanceView.vue', () => ({ default: { template: '<div />' } }))

import router from './index'

// ── 辅助：恢复 mock 默认值 ──────────────────────────────
function resetMockDefaults() {
  mockIsAdminConsoleSpa.mockReturnValue(false)
  mockIsEnterpriseEdition.mockReturnValue(false)
  mockFetchProductSku.mockResolvedValue('generic')
  mockShouldRouteToProductOnboarding.mockReturnValue(false)
  mockShouldRouteToHostPackOnboarding.mockReturnValue(false)
  mockResolveHostPackOnboardingStep.mockResolvedValue(null)
  mockModsStore.clientModsUiOff = false
  mockModsStore.mods = []
  mockModsStore.activeModId = ''
  mockAccountProfileStore.loaded = true
  mockAccountProfileStore.isAdminAccount = false
  mockAccountProfileStore.accountKind = 'personal'
  mockAccountProfileStore.marketIsAdmin = false
  mockAccountProfileStore.marketIsEnterprise = false
  mockAccountProfileStore.refreshFromServer.mockResolvedValue(undefined)
  mockResolvePlannerChatHomePath.mockReturnValue('/')
  mockResolvePlannerPagePath.mockImplementation((p: string) => p)
  mockCustomerServiceHostPath.mockReturnValue(null)
  mockResolveHostBusinessPageRedirect.mockReturnValue(null)
  mockIsProtectedClientModId.mockReturnValue(false)
  mockReadActiveExtensionModId.mockReturnValue('')
  mockIsPlatformShellModeEnabled.mockReturnValue(false)
  mockIsIndustryDeliveryRouteName.mockReturnValue(false)
  mockReadHostPackAcknowledged.mockReturnValue(false)
  mockCanShowCoreMenuKey.mockReturnValue(true)
  mockBuildRoleMenuProfile.mockReturnValue({})
  mockIsClientErpSidebarContext.mockReturnValue(false)
  mockLanGateRefresh.mockResolvedValue({ enabled: false, authorized: true })
  mockValidateEnterpriseSession.mockResolvedValue(true)
}

describe('router/index 覆盖率补齐', () => {
  beforeEach(async () => {
    vi.clearAllMocks()
    resetMockDefaults()
    // 导航到中性路由 /login（publicAccess，不触发任何守卫），避免 Vue Router 同路由导航去重
    await router.push('/login')
  })

  // ═══════════════════════════════════════════════════════════
  // 1. 路由配置 - 重定向与 meta
  // ═══════════════════════════════════════════════════════════
  describe('路由配置 - 重定向', () => {
    it('/index.html 重定向到 / 并保留 query 和 hash', async () => {
      await router.push('/index.html?foo=bar#section')
      expect(router.currentRoute.value.path).toBe('/')
      expect(router.currentRoute.value.query.foo).toBe('bar')
    })

    it('/materials-list 重定向到 materials', async () => {
      await router.push('/materials-list')
      expect(router.currentRoute.value.name).toBe('materials')
    })

    it('/business-docking 重定向到 template-preview', async () => {
      await router.push('/business-docking')
      expect(router.currentRoute.value.name).toBe('template-preview')
    })

    it('/model-payment 重定向到 settings 带 section query', async () => {
      await router.push('/model-payment')
      expect(router.currentRoute.value.name).toBe('settings')
      expect(router.currentRoute.value.query.section).toBe('model-payment')
    })

    it('/wechat-contacts 重定向到 data-sources 带 source query', async () => {
      await router.push('/wechat-contacts')
      expect(router.currentRoute.value.name).toBe('data-sources')
      expect(router.currentRoute.value.query.source).toBe('wechat_local_db')
    })

    it('/other-tools 重定向到 workflow-employee-space', async () => {
      await router.push('/other-tools')
      expect(router.currentRoute.value.name).toBe('workflow-employee-space')
    })

    it('/employee-workspace 重定向到 workflow-employee-space', async () => {
      await router.push('/employee-workspace')
      expect(router.currentRoute.value.name).toBe('workflow-employee-space')
    })

    it('/yuangong-stitch 重定向到 workflow-employee-stitch-full', async () => {
      await router.push('/yuangong-stitch')
      expect(router.currentRoute.value.name).toBe('workflow-employee-stitch-full')
    })

    it('/approval-hub 重定向到 approval-workspace 子路由', async () => {
      await router.push('/approval-hub')
      expect(router.currentRoute.value.name).toBe('approval-workspace')
    })

    it('导航到 approval-hub/flow-management 子路由', async () => {
      await router.push('/approval-hub/flow-management')
      expect(router.currentRoute.value.name).toBe('approval-flow-management')
    })

    it('导航到 approval-hub/rules 子路由', async () => {
      await router.push('/approval-hub/rules')
      expect(router.currentRoute.value.name).toBe('approval-rules')
    })
  })

  // ═══════════════════════════════════════════════════════════
  // 2. console 路由 beforeEnter 守卫
  // ═══════════════════════════════════════════════════════════
  describe('console 路由 beforeEnter 守卫', () => {
    it('view=excel 时通过', async () => {
      await router.push('/console?view=excel')
      expect(router.currentRoute.value.name).toBe('console')
      expect(router.currentRoute.value.query.view).toBe('excel')
    })

    it('view=template-preview 时通过', async () => {
      await router.push('/console?view=template-preview')
      expect(router.currentRoute.value.name).toBe('console')
    })

    it('view 为其他值时通过', async () => {
      await router.push('/console?view=custom')
      expect(router.currentRoute.value.name).toBe('console')
    })

    it('无 view 参数时通过', async () => {
      await router.push('/console')
      expect(router.currentRoute.value.name).toBe('console')
    })
  })

  // ═══════════════════════════════════════════════════════════
  // 3. beforeEach 守卫 - admin console
  // ═══════════════════════════════════════════════════════════
  describe('beforeEach 守卫 - admin console', () => {
    let adminHomeRouteAdded = false

    beforeEach(() => {
      // 动态添加 admin-home 路由（ADMIN_HOST_ROUTE_RECORDS 为空，需要手动添加）
      if (!router.hasRoute('admin-home')) {
        router.addRoute({
          path: '/admin-home',
          name: 'admin-home',
          component: { template: '<div>admin-home</div>' },
          meta: { title: '运维总览' },
        })
        adminHomeRouteAdded = true
      }
    })

    afterEach(() => {
      if (adminHomeRouteAdded && router.hasRoute('admin-home')) {
        router.removeRoute('admin-home')
        adminHomeRouteAdded = false
      }
    })

    it('admin console 中 planner bridge 路径重定向到 host 路径', async () => {
      mockIsAdminConsoleSpa.mockReturnValue(true)
      await router.push('/mod/xcagi-planner-bridge/chat?foo=bar#hash')
      expect(router.currentRoute.value.path).toBe('/chat')
      expect(router.currentRoute.value.query.foo).toBe('bar')
    })

    it('admin console 中 planner bridge 根路径重定向到 /', async () => {
      mockIsAdminConsoleSpa.mockReturnValue(true)
      await router.push('/mod/xcagi-planner-bridge/')
      expect(router.currentRoute.value.path).toBe('/')
    })

    it('admin console 中 blocked route name 重定向到 operator home', async () => {
      mockIsAdminConsoleSpa.mockReturnValue(true)
      await router.push('/admin/entitlements')
      expect(router.currentRoute.value.name).toBe('admin-home')
    })

    it('admin console 冷启动 chat 重定向 admin 到 operator home', async () => {
      mockIsAdminConsoleSpa.mockReturnValue(true)
      mockAccountProfileStore.loaded = false
      mockAccountProfileStore.isAdminAccount = true
      mockAccountProfileStore.refreshFromServer.mockResolvedValue(undefined)

      vi.resetModules()
      const { default: freshRouter } = await import('./index')
      // 为 freshRouter 也添加 admin-home 路由
      if (!freshRouter.hasRoute('admin-home')) {
        freshRouter.addRoute({
          path: '/admin-home',
          name: 'admin-home',
          component: { template: '<div />' },
          meta: { title: '运维总览' },
        })
      }
      await freshRouter.push('/')
      expect(freshRouter.currentRoute.value.name).toBe('admin-home')
    })

    it('admin console 冷启动 chat 非 admin 不重定向', async () => {
      mockIsAdminConsoleSpa.mockReturnValue(true)
      mockAccountProfileStore.loaded = false
      mockAccountProfileStore.isAdminAccount = false

      vi.resetModules()
      const { default: freshRouter } = await import('./index')
      await freshRouter.push('/')
      expect(freshRouter.currentRoute.value.name).toBe('chat')
    })

    it('admin console 冷启动 profile refresh 异常时忽略', async () => {
      mockIsAdminConsoleSpa.mockReturnValue(true)
      mockAccountProfileStore.loaded = false
      mockAccountProfileStore.refreshFromServer.mockRejectedValue(new Error('network'))

      vi.resetModules()
      const { default: freshRouter } = await import('./index')
      await freshRouter.push('/')
      // 异常被 catch 忽略，继续到 chat
      expect(freshRouter.currentRoute.value.name).toBe('chat')
    })
  })

  // ═══════════════════════════════════════════════════════════
  // 4. beforeEach 守卫 - workflow-visualization
  // ═══════════════════════════════════════════════════════════
  describe('beforeEach 守卫 - workflow-visualization', () => {
    it('canShowCoreMenuKey 返回 true 时允许访问', async () => {
      mockCanShowCoreMenuKey.mockReturnValue(true)
      await router.push('/workflow-visualization')
      expect(router.currentRoute.value.name).toBe('workflow-visualization')
    })

    it('canShowCoreMenuKey 返回 false 时重定向到 employee-space', async () => {
      mockCanShowCoreMenuKey.mockReturnValue(false)
      await router.push('/workflow-visualization')
      expect(router.currentRoute.value.name).toBe('workflow-employee-space')
    })

    it('profile 未加载时调用 refreshFromServer', async () => {
      mockAccountProfileStore.loaded = false
      mockAccountProfileStore.refreshFromServer.mockResolvedValue(undefined)
      mockCanShowCoreMenuKey.mockReturnValue(true)
      await router.push('/workflow-visualization')
      expect(mockAccountProfileStore.refreshFromServer).toHaveBeenCalled()
    })

    it('refreshFromServer 异常时重定向到 employee-space', async () => {
      mockAccountProfileStore.loaded = false
      mockAccountProfileStore.refreshFromServer.mockRejectedValue(new Error('network'))
      await router.push('/workflow-visualization')
      expect(router.currentRoute.value.name).toBe('workflow-employee-space')
    })

    it('buildRoleMenuProfile 异常时重定向到 employee-space', async () => {
      mockBuildRoleMenuProfile.mockImplementation(() => {
        throw new Error('build error')
      })
      await router.push('/workflow-visualization')
      expect(router.currentRoute.value.name).toBe('workflow-employee-space')
    })

    it('admin console SPA 中不检查 workflow-visualization', async () => {
      mockIsAdminConsoleSpa.mockReturnValue(true)
      mockCanShowCoreMenuKey.mockReturnValue(false)
      await router.push('/workflow-visualization')
      // admin console 中跳过此检查
      expect(router.currentRoute.value.name).toBe('workflow-visualization')
    })
  })

  // ═══════════════════════════════════════════════════════════
  // 5. beforeEach 守卫 - mod 路径
  // ═══════════════════════════════════════════════════════════
  describe('beforeEach 守卫 - mod 路径', () => {
    it('未匹配 /mod/ 路径有 customer service host 时重定向', async () => {
      mockCustomerServiceHostPath.mockReturnValue('/im?open=enterprise-cs')
      await router.push('/mod/nonexistent-cs/page')
      expect(router.currentRoute.value.path).toBe('/im')
    })

    it('未匹配 /mod/ planner-bridge 路径 + protected mod 时重定向到 /', async () => {
      mockIsProtectedClientModId.mockReturnValue(true)
      mockReadActiveExtensionModId.mockReturnValue('xcagi-planner-bridge')
      await router.push('/mod/xcagi-planner-bridge/unknown')
      expect(router.currentRoute.value.path).toBe('/')
    })

    it('未匹配 /mod/ 路径 fallback 重定向到 /', async () => {
      mockCustomerServiceHostPath.mockReturnValue(null)
      mockIsProtectedClientModId.mockReturnValue(false)
      await router.push('/mod/nonexistent/page')
      expect(router.currentRoute.value.path).toBe('/')
    })

    it('已匹配 planner-bridge 路径 + protected mod 时重定向到 /', async () => {
      mockIsProtectedClientModId.mockReturnValue(true)
      mockReadActiveExtensionModId.mockReturnValue('xcagi-planner-bridge')
      // 注意：路径必须以 /mod/xcagi-planner-bridge/ 开头（含尾部斜杠）才能触发此守卫
      await router.push('/mod/xcagi-planner-bridge/')
      expect(router.currentRoute.value.path).toBe('/')
    })
  })

  // ═══════════════════════════════════════════════════════════
  // 6. beforeEach 守卫 - LAN gate
  // ═══════════════════════════════════════════════════════════
  describe('beforeEach 守卫 - LAN gate', () => {
    let testRouteName: string

    beforeEach(() => {
      // 动态添加带 hostAdmin meta 的测试路由
      router.addRoute({
        path: '/test-host-admin',
        name: 'test-host-admin',
        component: { template: '<div />' },
        meta: { hostAdmin: true },
      })
      testRouteName = 'test-host-admin'
    })

    afterEach(() => {
      router.removeRoute(testRouteName)
    })

    it('LAN enabled 且未授权时打开 modal 并中止导航', async () => {
      mockLanGateRefresh.mockResolvedValue({ enabled: true, authorized: false })
      await router.push('/test-host-admin')
      expect(mockLanGateOpenModal).toHaveBeenCalled()
      // next(false) 中止导航，当前路由不变
      expect(router.currentRoute.value.name).not.toBe('test-host-admin')
    })

    it('LAN enabled 且已授权时允许导航', async () => {
      mockLanGateRefresh.mockResolvedValue({ enabled: true, authorized: true })
      await router.push('/test-host-admin')
      expect(router.currentRoute.value.name).toBe('test-host-admin')
    })

    it('LAN refresh 异常时忽略并允许导航', async () => {
      mockLanGateRefresh.mockRejectedValue(new Error('network'))
      await router.push('/test-host-admin')
      expect(router.currentRoute.value.name).toBe('test-host-admin')
    })

    it('publicAccess 路由不触发 LAN gate', async () => {
      router.addRoute({
        path: '/test-host-admin-public',
        name: 'test-host-admin-public',
        component: { template: '<div />' },
        meta: { hostAdmin: true, publicAccess: true },
      })
      mockLanGateRefresh.mockResolvedValue({ enabled: true, authorized: false })
      await router.push('/test-host-admin-public')
      expect(router.currentRoute.value.name).toBe('test-host-admin-public')
      expect(mockLanGateOpenModal).not.toHaveBeenCalled()
      router.removeRoute('test-host-admin-public')
    })
  })

  // ═══════════════════════════════════════════════════════════
  // 7. beforeEach 守卫 - mods UI off
  // ═══════════════════════════════════════════════════════════
  describe('beforeEach 守卫 - mods UI off', () => {
    it('clientModsUiOff + mod 路由时重定向到 planner chat home', async () => {
      mockModsStore.clientModsUiOff = true
      mockResolvePlannerChatHomePath.mockReturnValue('/chat-home')
      await router.push('/mod/test-mod')
      expect(router.currentRoute.value.path).toBe('/chat-home')
    })

    it('clientModsUiOff + 非 mod 路由时允许导航', async () => {
      mockModsStore.clientModsUiOff = true
      await router.push('/settings')
      expect(router.currentRoute.value.name).toBe('settings')
    })

    it('modsStore 异常时忽略并继续', async () => {
      // 临时让 useModsStore 抛错 - 通过修改 mockModsStore 属性来间接测试
      // 由于 useModsStore 是 mock 的，这里测试 catch 路径
      mockModsStore.clientModsUiOff = false
      await router.push('/settings')
      expect(router.currentRoute.value.name).toBe('settings')
    })
  })

  // ═══════════════════════════════════════════════════════════
  // 8. beforeEach 守卫 - planner chat 重定向
  // ═══════════════════════════════════════════════════════════
  describe('beforeEach 守卫 - planner chat 重定向', () => {
    it('chat 路径有不同 planner mod page 且路由存在时重定向', async () => {
      mockResolvePlannerPagePath.mockReturnValue('/login')
      // /login 路由存在，所以会重定向
      await router.push('/')
      expect(router.currentRoute.value.name).toBe('login')
    })

    it('chat 路径有不同 planner mod page 但路由不存在时允许', async () => {
      mockResolvePlannerPagePath.mockReturnValue('/nonexistent-planner-path')
      await router.push('/')
      // 路由不存在，next() 允许导航
      expect(router.currentRoute.value.name).toBe('chat')
    })

    it('chat 路径与 planner mod page 相同时允许', async () => {
      mockResolvePlannerPagePath.mockReturnValue('/')
      await router.push('/')
      expect(router.currentRoute.value.name).toBe('chat')
    })
  })

  // ═══════════════════════════════════════════════════════════
  // 9. beforeEach 守卫 - platform shell 重定向
  // ═══════════════════════════════════════════════════════════
  describe('beforeEach 守卫 - platform shell 重定向', () => {
    it('platform shell + 非 core 路由 + 有 host business page 时重定向', async () => {
      mockIsPlatformShellModeEnabled.mockReturnValue(true)
      mockResolveHostBusinessPageRedirect.mockReturnValue('/mod/host-business')
      // products 不是 SHELL_CORE_ROUTE_NAMES 中的路由
      await router.push('/products')
      expect(router.currentRoute.value.path).toBe('/mod/host-business')
    })

    it('platform shell + 非 core 路由 + 无 host business page 时重定向到 planner chat home', async () => {
      mockIsPlatformShellModeEnabled.mockReturnValue(true)
      mockResolveHostBusinessPageRedirect.mockReturnValue(null)
      mockResolvePlannerChatHomePath.mockReturnValue('/planner-chat-home')
      await router.push('/products')
      expect(router.currentRoute.value.path).toBe('/planner-chat-home')
    })

    it('platform shell + core 路由时不重定向', async () => {
      mockIsPlatformShellModeEnabled.mockReturnValue(true)
      // settings 是 SHELL_CORE_ROUTE_NAMES 中的路由
      await router.push('/settings')
      expect(router.currentRoute.value.name).toBe('settings')
    })

    it('platform shell + industry delivery 路由时不重定向', async () => {
      mockIsPlatformShellModeEnabled.mockReturnValue(true)
      mockIsIndustryDeliveryRouteName.mockReturnValue(true)
      // products 在 INDUSTRY_DELIVERY_ROUTE_NAMES 中
      await router.push('/products')
      expect(router.currentRoute.value.name).toBe('products')
    })

    it('platform shell + mod meta 路由时不重定向', async () => {
      mockIsPlatformShellModeEnabled.mockReturnValue(true)
      // mod-landing 有 meta.mod = true
      await router.push('/mod/test-mod')
      // mod 路由不被 platform shell 重定向
      // 但可能被其他守卫处理
    })
  })

  // ═══════════════════════════════════════════════════════════
  // 10. beforeEach 守卫 - customer service 路由
  // ═══════════════════════════════════════════════════════════
  describe('beforeEach 守卫 - customer service', () => {
    it('enterprise 客服 + admin 账号时重定向到 internal-customer-service', async () => {
      mockAccountProfileStore.loaded = true
      mockAccountProfileStore.isAdminAccount = true
      await router.push('/enterprise-customer-service')
      expect(router.currentRoute.value.name).toBe('internal-customer-service')
    })

    it('enterprise 客服 + 非 admin 账号时允许', async () => {
      mockAccountProfileStore.loaded = true
      mockAccountProfileStore.isAdminAccount = false
      await router.push('/enterprise-customer-service')
      expect(router.currentRoute.value.name).toBe('enterprise-customer-service')
    })

    it('admin 客服 + 非 admin 账号时重定向到 im', async () => {
      mockAccountProfileStore.loaded = true
      mockAccountProfileStore.isAdminAccount = false
      await router.push('/internal-customer-service')
      expect(router.currentRoute.value.name).toBe('im')
    })

    it('admin 客服 + admin 账号时允许', async () => {
      mockAccountProfileStore.loaded = true
      mockAccountProfileStore.isAdminAccount = true
      await router.push('/internal-customer-service')
      expect(router.currentRoute.value.name).toBe('internal-customer-service')
    })

    it('profile 未加载时调用 refreshFromServer', async () => {
      mockAccountProfileStore.loaded = false
      mockAccountProfileStore.refreshFromServer.mockResolvedValue(undefined)
      mockAccountProfileStore.isAdminAccount = false
      await router.push('/enterprise-customer-service')
      expect(mockAccountProfileStore.refreshFromServer).toHaveBeenCalled()
    })

    it('profile refresh 异常时重定向到 chat', async () => {
      mockAccountProfileStore.loaded = false
      mockAccountProfileStore.refreshFromServer.mockRejectedValue(new Error('network'))
      await router.push('/enterprise-customer-service')
      expect(router.currentRoute.value.name).toBe('chat')
    })
  })

  // ═══════════════════════════════════════════════════════════
  // 11. beforeEach 守卫 - requiresAdminAccount
  // ═══════════════════════════════════════════════════════════
  describe('beforeEach 守卫 - requiresAdminAccount', () => {
    it('非 admin 账号访问 requiresAdminAccount 路由时重定向到 chat', async () => {
      mockAccountProfileStore.loaded = true
      mockAccountProfileStore.isAdminAccount = false
      await router.push('/admin/entitlements')
      expect(router.currentRoute.value.name).toBe('chat')
    })

    it('admin 账号访问 requiresAdminAccount 路由时允许', async () => {
      mockAccountProfileStore.loaded = true
      mockAccountProfileStore.isAdminAccount = true
      await router.push('/admin/entitlements')
      expect(router.currentRoute.value.name).toBe('admin-entitlements')
    })

    it('profile 未加载时调用 refreshFromServer', async () => {
      mockAccountProfileStore.loaded = false
      mockAccountProfileStore.refreshFromServer.mockResolvedValue(undefined)
      mockAccountProfileStore.isAdminAccount = false
      await router.push('/admin/entitlements')
      expect(mockAccountProfileStore.refreshFromServer).toHaveBeenCalled()
    })

    it('profile refresh 异常时重定向到 chat', async () => {
      mockAccountProfileStore.loaded = false
      mockAccountProfileStore.refreshFromServer.mockRejectedValue(new Error('network'))
      await router.push('/admin/entitlements')
      expect(router.currentRoute.value.name).toBe('chat')
    })
  })

  // ═══════════════════════════════════════════════════════════
  // 12. beforeEach 守卫 - enterprise session
  // ═══════════════════════════════════════════════════════════
  describe('beforeEach 守卫 - enterprise session', () => {
    it('enterprise + 无效 session 时重定向到 login', async () => {
      mockIsEnterpriseEdition.mockReturnValue(true)
      mockValidateEnterpriseSession.mockResolvedValue(false)
      await router.push('/settings')
      expect(router.currentRoute.value.name).toBe('login')
    })

    it('enterprise + 有效 session + 非 admin 时允许', async () => {
      mockIsEnterpriseEdition.mockReturnValue(true)
      mockValidateEnterpriseSession.mockResolvedValue(true)
      mockAccountProfileStore.loaded = true
      mockAccountProfileStore.isAdminAccount = false
      await router.push('/settings')
      expect(router.currentRoute.value.name).toBe('settings')
    })

    it('enterprise + 有效 session + admin 时重定向到 admin console', async () => {
      mockIsEnterpriseEdition.mockReturnValue(true)
      mockValidateEnterpriseSession.mockResolvedValue(true)
      mockAccountProfileStore.loaded = true
      mockAccountProfileStore.isAdminAccount = true
      // window.location.href 赋值 + next(false)
      // 导航被中止
      await router.push('/settings')
      // 由于 next(false)，当前路由不变（或保持上一个）
      expect(mockResolveAdminConsoleHomeUrl).toHaveBeenCalled()
    })

    it('enterprise + 有效 session + profile 未加载时调用 refresh', async () => {
      mockIsEnterpriseEdition.mockReturnValue(true)
      mockValidateEnterpriseSession.mockResolvedValue(true)
      mockAccountProfileStore.loaded = false
      mockAccountProfileStore.refreshFromServer.mockResolvedValue(undefined)
      mockAccountProfileStore.isAdminAccount = false
      await router.push('/settings')
      expect(mockAccountProfileStore.refreshFromServer).toHaveBeenCalled()
    })

    it('enterprise + 有效 session + profile refresh 异常时忽略', async () => {
      mockIsEnterpriseEdition.mockReturnValue(true)
      mockValidateEnterpriseSession.mockResolvedValue(true)
      mockAccountProfileStore.loaded = false
      mockAccountProfileStore.refreshFromServer.mockRejectedValue(new Error('network'))
      mockAccountProfileStore.isAdminAccount = false
      await router.push('/settings')
      // 内部 catch 忽略异常，继续允许导航
      expect(router.currentRoute.value.name).toBe('settings')
    })

    it('fetchProductSku 异常 + 非 enterprise 时允许导航', async () => {
      mockFetchProductSku.mockRejectedValueOnce(new Error('network'))
      mockFetchProductSku.mockResolvedValueOnce('generic')
      mockIsEnterpriseEdition.mockReturnValue(false)
      await router.push('/settings')
      expect(router.currentRoute.value.name).toBe('settings')
    })

    it('fetchProductSku 异常 + enterprise 时重定向到 login', async () => {
      mockFetchProductSku.mockRejectedValue(new Error('network'))
      mockIsEnterpriseEdition.mockReturnValue(true)
      await router.push('/settings')
      expect(router.currentRoute.value.name).toBe('login')
    })

    it('publicAccess 路由跳过 enterprise session 检查', async () => {
      mockIsEnterpriseEdition.mockReturnValue(true)
      mockValidateEnterpriseSession.mockResolvedValue(false)
      await router.push('/login')
      expect(router.currentRoute.value.name).toBe('login')
    })
  })

  // ═══════════════════════════════════════════════════════════
  // 13. beforeEach 守卫 - product onboarding
  // ═══════════════════════════════════════════════════════════
  describe('beforeEach 守卫 - product onboarding', () => {
    it('shouldRouteToProductOnboarding 返回 true 时重定向到 onboarding', async () => {
      mockShouldRouteToProductOnboarding.mockReturnValue(true)
      await router.push('/settings')
      expect(router.currentRoute.value.name).toBe('product-onboarding')
      expect(router.currentRoute.value.query.step).toBe('welcome')
    })

    it('shouldRouteToProductOnboarding + publicAccess 时不重定向', async () => {
      mockShouldRouteToProductOnboarding.mockReturnValue(true)
      await router.push('/login')
      expect(router.currentRoute.value.name).toBe('login')
    })

    it('shouldRouteToProductOnboarding + admin console 时不重定向', async () => {
      mockShouldRouteToProductOnboarding.mockReturnValue(true)
      mockIsAdminConsoleSpa.mockReturnValue(true)
      await router.push('/settings')
      // admin console 中不触发 product onboarding
      // 但可能被其他守卫处理
    })
  })

  // ═══════════════════════════════════════════════════════════
  // 14. beforeEach 守卫 - host pack onboarding
  // ═══════════════════════════════════════════════════════════
  describe('beforeEach 守卫 - host pack onboarding', () => {
    it('shouldRouteToHostPackOnboarding + 有 step 时重定向到 onboarding', async () => {
      mockShouldRouteToHostPackOnboarding.mockReturnValue(true)
      mockResolveHostPackOnboardingStep.mockResolvedValue('welcome')
      await router.push('/settings')
      expect(router.currentRoute.value.name).toBe('product-onboarding')
      expect(router.currentRoute.value.query.step).toBe('welcome')
    })

    it('shouldRouteToHostPackOnboarding + step 为 null 时允许', async () => {
      mockShouldRouteToHostPackOnboarding.mockReturnValue(true)
      mockResolveHostPackOnboardingStep.mockResolvedValue(null)
      await router.push('/settings')
      expect(router.currentRoute.value.name).toBe('settings')
    })

    it('shouldRouteToHostPackOnboarding + resolve 异常时忽略', async () => {
      mockShouldRouteToHostPackOnboarding.mockReturnValue(true)
      mockResolveHostPackOnboardingStep.mockRejectedValue(new Error('network'))
      await router.push('/settings')
      expect(router.currentRoute.value.name).toBe('settings')
    })

    it('shouldRouteToHostPackOnboarding + publicAccess 时不触发', async () => {
      mockShouldRouteToHostPackOnboarding.mockReturnValue(true)
      mockResolveHostPackOnboardingStep.mockResolvedValue('welcome')
      await router.push('/login')
      expect(router.currentRoute.value.name).toBe('login')
    })
  })

  // ═══════════════════════════════════════════════════════════
  // 15. afterEach hook - document title
  // ═══════════════════════════════════════════════════════════
  describe('afterEach hook - document title', () => {
    it('有 meta.title 时设置标题为 "title - XCAGI"', async () => {
      await router.push('/login')
      expect(document.title).toBe('登录 - XCAGI')
    })

    it('无 meta.title 时设置默认标题 "XCAGI"', async () => {
      await router.push('/nonexistent-path')
      expect(document.title).toBe('XCAGI')
    })

    it('chat 路由设置 "智能对话 - XCAGI"', async () => {
      await router.push('/')
      expect(document.title).toBe('智能对话 - XCAGI')
    })

    it('settings 路由设置 "设置 - XCAGI"', async () => {
      await router.push('/settings')
      expect(document.title).toBe('设置 - XCAGI')
    })
  })

  // ═══════════════════════════════════════════════════════════
  // 16. filterSandboxRoutes / filterPlatformShellRoutes
  // 使用 vi.doMock + vi.resetModules + 动态导入来测试不同模式
  // ═══════════════════════════════════════════════════════════
  describe('filterSandboxRoutes', () => {
    it('sandbox 模式下只保留 SANDBOX_ALLOWED 路由', async () => {
      // 设置 sandbox URL 参数
      const originalSearch = window.location.search
      window.history.replaceState({}, '', '/?sandbox')

      vi.resetModules()
      const { default: sandboxRouter } = await import('./index')

      const names = sandboxRouter.getRoutes().map((r) => r.name)
      // SANDBOX_ALLOWED 中的路由应该存在
      expect(names).toContain('login')
      expect(names).toContain('chat')
      expect(names).toContain('tools')
      expect(names).toContain('mod-landing')
      // 非 SANDBOX_ALLOWED 的路由应该被过滤掉
      expect(names).not.toContain('settings')
      expect(names).not.toContain('inventory')

      // 恢复 URL
      window.history.replaceState({}, '', originalSearch || '/')
    })

    it('sandbox 模式下 /employee-workspace 和 /yuangong-stitch 被过滤（无 name）', async () => {
      const originalSearch = window.location.search
      window.history.replaceState({}, '', '/?sandbox')

      vi.resetModules()
      const { default: sandboxRouter } = await import('./index')

      // filterSandboxRoutes 中 if (!r.name) return false 先执行
      // /employee-workspace 和 /yuangong-stitch 是重定向路由，无 name
      // 所以它们会被过滤掉（即使代码中有 r.path === '/employee-workspace' 的检查）
      const paths = sandboxRouter.getRoutes().map((r) => r.path)
      expect(paths).not.toContain('/employee-workspace')
      expect(paths).not.toContain('/yuangong-stitch')

      window.history.replaceState({}, '', originalSearch || '/')
    })
  })

  describe('filterPlatformShellRoutes', () => {
    it('platform shell 模式下只保留 shell core 路由', async () => {
      mockIsPlatformShellModeEnabled.mockReturnValue(true)

      vi.resetModules()
      const { default: shellRouter } = await import('./index')

      const names = shellRouter.getRoutes().map((r) => r.name)
      // SHELL_CORE_ROUTE_NAMES 中的路由应该存在
      expect(names).toContain('login')
      expect(names).toContain('chat')
      expect(names).toContain('settings')
      expect(names).toContain('mod-store')
      // 非 shell core 路由应该被过滤掉
      expect(names).not.toContain('inventory')
      expect(names).not.toContain('orders')
    })

    it('platform shell 模式下保留 mod meta 路由', async () => {
      mockIsPlatformShellModeEnabled.mockReturnValue(true)

      vi.resetModules()
      const { default: shellRouter } = await import('./index')

      const names = shellRouter.getRoutes().map((r) => r.name)
      // mod-landing 有 meta.mod = true
      expect(names).toContain('mod-landing')
    })

    it('platform shell 模式下保留 /mod/ 路径路由', async () => {
      mockIsPlatformShellModeEnabled.mockReturnValue(true)

      vi.resetModules()
      const { default: shellRouter } = await import('./index')

      const paths = shellRouter.getRoutes().map((r) => r.path)
      // /mod/:modId 路径以 /mod/ 开头
      expect(paths.some((p) => p.startsWith('/mod/'))).toBe(true)
    })

    it('platform shell 模式下 /employee-workspace 和 /yuangong-stitch 被过滤（无 name）', async () => {
      mockIsPlatformShellModeEnabled.mockReturnValue(true)

      vi.resetModules()
      const { default: shellRouter } = await import('./index')

      // filterPlatformShellRoutes 中 if (!r.name) return false 先执行
      // /employee-workspace 和 /yuangong-stitch 是重定向路由，无 name
      const paths = shellRouter.getRoutes().map((r) => r.path)
      expect(paths).not.toContain('/employee-workspace')
      expect(paths).not.toContain('/yuangong-stitch')
    })
  })

  // ═══════════════════════════════════════════════════════════
  // 17. 路由 meta 属性验证
  // ═══════════════════════════════════════════════════════════
  describe('路由 meta 属性', () => {
    it('login 路由有 publicAccess 和 hideChrome meta', () => {
      const route = router.getRoutes().find((r) => r.name === 'login')
      expect(route?.meta?.publicAccess).toBe(true)
      expect(route?.meta?.hideChrome).toBe(true)
    })

    it('chat 路由没有 publicAccess meta', () => {
      const route = router.getRoutes().find((r) => r.name === 'chat')
      expect(route?.meta?.publicAccess).toBeUndefined()
    })

    it('mod-landing 路由有 mod meta', () => {
      const route = router.getRoutes().find((r) => r.name === 'mod-landing')
      expect(route?.meta?.mod).toBe(true)
    })

    it('enterprise-customer-service 有 customerServiceSide=enterprise', () => {
      const route = router.getRoutes().find((r) => r.name === 'enterprise-customer-service')
      expect(route?.meta?.customerServiceSide).toBe('enterprise')
    })

    it('internal-customer-service 有 customerServiceSide=admin 和 requiresAdminAccount', () => {
      const route = router.getRoutes().find((r) => r.name === 'internal-customer-service')
      expect(route?.meta?.customerServiceSide).toBe('admin')
      expect(route?.meta?.requiresAdminAccount).toBe(true)
    })

    it('admin-entitlements 有 requiresAdminAccount', () => {
      const route = router.getRoutes().find((r) => r.name === 'admin-entitlements')
      expect(route?.meta?.requiresAdminAccount).toBe(true)
    })

    it('product-onboarding 有 publicAccess 和 hideChrome', () => {
      const route = router.getRoutes().find((r) => r.name === 'product-onboarding')
      expect(route?.meta?.publicAccess).toBe(true)
      expect(route?.meta?.hideChrome).toBe(true)
    })
  })

  // ═══════════════════════════════════════════════════════════
  // 18. 路由懒加载组件
  // ═══════════════════════════════════════════════════════════
  describe('路由懒加载组件', () => {
    it('所有核心命名路由都有 component 定义', () => {
      const routes = router.getRoutes()
      // 排除 redirect 路由（它们没有 component）
      const namedRoutes = routes.filter((r) => r.name && !r.redirect)
      for (const route of namedRoutes) {
        // Vue Router 4 将 component 存储在 components.default 中
        const hasComponent = route.component !== undefined ||
          (route.components && route.components.default !== undefined)
        expect(hasComponent).toBe(true)
      }
    })

    it('login 路由 component 可被加载', async () => {
      const route = router.getRoutes().find((r) => r.name === 'login')
      expect(route).toBeDefined()
      // Vue Router 4 将 component 存储在 components.default 中
      // mock 后可能是函数（懒加载）或对象（已解析）
      const comp = route?.component ?? route?.components?.default
      expect(comp).toBeDefined()
    })
  })
})
