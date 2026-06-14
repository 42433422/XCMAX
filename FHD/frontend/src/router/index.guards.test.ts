import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('@/composables/useLanGate', () => ({
  useLanGate: () => ({
    refresh: vi.fn().mockResolvedValue({ enabled: false, authorized: true }),
    openLanGateModal: vi.fn(),
  }),
}))

vi.mock('@/composables/useProductFlow', () => ({
  shouldRouteToProductOnboarding: () => false,
}))

vi.mock('@/utils/hostPackOnboardingGate', () => ({
  resolveHostPackOnboardingStep: vi.fn().mockResolvedValue(null),
  shouldRouteToHostPackOnboarding: () => false,
}))

vi.mock('@/utils/hostBusinessPageRedirect', () => ({
  resolveHostBusinessPageRedirect: () => null,
}))

vi.mock('@/utils/customerServicePagePaths', () => ({
  customerServiceHostPathFromModPath: () => null,
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
  resolvePlannerChatHomePath: () => '/',
  resolvePlannerPagePath: (p: string) => p,
}))

vi.mock('@/utils/erpDomainPaths', () => ({
  readActiveExtensionModId: () => '',
}))

vi.mock('@/constants/protectedMods', () => ({
  isProtectedClientModId: () => false,
}))

vi.mock('@/utils/productSku', () => ({
  fetchProductSku: vi.fn().mockResolvedValue('generic'),
  isEnterpriseEdition: () => false,
}))

vi.mock('@/utils/authSessionCache', () => ({
  validateEnterpriseSessionCached: vi.fn().mockResolvedValue(true),
}))

vi.mock('@/utils/adminConsoleUrl', () => ({
  isAdminConsoleSpa: () => false,
  resolveAdminConsoleHomeUrl: () => '/admin',
}))

vi.mock('@/constants/platformShellMode', () => ({
  isPlatformShellModeEnabled: () => false,
  isShellEditionBuild: () => false,
  SHELL_CORE_ROUTE_NAMES: new Set(['login', 'chat']),
}))

vi.mock('@/constants/genericModPack', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/constants/genericModPack')>()
  return {
    ...actual,
    isClientErpSidebarContext: () => false,
  }
})

vi.mock('@/utils/roleMenuProfile', () => ({
  buildRoleMenuProfile: vi.fn(),
  canShowCoreMenuKey: () => true,
}))

vi.mock('@/constants/adminOperatorNav', () => ({
  ADMIN_OPERATOR_BLOCKED_ROUTE_NAMES: new Set(),
  ADMIN_OPERATOR_HOME_ROUTE: 'admin-home',
}))

vi.mock('@admin-console-inject/adminHostRoutes', () => ({
  ADMIN_HOST_ROUTE_RECORDS: [],
}))

vi.mock('@/stores/mods', () => ({
  useModsStore: () => ({
    clientModsUiOff: false,
    mods: [],
    activeModId: '',
  }),
}))

vi.mock('../views/LoginView.vue', () => ({ default: { template: '<div>Login</div>' } }))
vi.mock('../views/LoginHelpView.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../views/RegisterView.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../views/ForgotAccountView.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../views/ForgotPasswordView.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../views/ChatView.vue', () => ({ default: { template: '<div>Chat</div>' } }))
vi.mock('../views/LanGateView.vue', () => ({ default: { template: '<div />' } }))

import router from './index'

describe('router/index guards', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('exports router with core routes', () => {
    const names = router.getRoutes().map((r) => r.name)
    expect(names).toContain('login')
    expect(names).toContain('chat')
  })

  it('allows navigation to public login route', async () => {
    await router.push('/login')
    expect(router.currentRoute.value.name).toBe('login')
  })

  it('allows navigation to chat home', async () => {
    await router.push('/')
    expect(router.currentRoute.value.name).toBe('chat')
  })

  it('redirects /index.html to /', async () => {
    await router.push('/index.html')
    expect(router.currentRoute.value.path).toBe('/')
  })

  it('sets document title after navigation', async () => {
    await router.push('/login')
    expect(document.title).toContain('登录')
  })

  it('navigates to lan-gate public route', async () => {
    await router.push('/lan-gate')
    expect(router.currentRoute.value.name).toBe('lan-gate')
  })
})
