import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MODEL_PAYMENT_BRIDGE_ID } from '@/constants/modelServiceNavigation'
import { useDesktopNavigationContext } from './useDesktopNavigationContext'

const state = vi.hoisted(() => ({
  desktop: true,
  adminConsole: false,
  ecosystem: false,
  account: { workspaceReady: true, localUserId: 2, userRole: 'tenant:user', accountKind: 'enterprise',
    tenantId: 1, marketIsEnterprise: true, permissions: [] as string[], marketUsername: 'hidden-account-name' },
  mods: { mods: [] as { id: string }[], isLoaded: true, loadedAccountEpoch: 3, clientModsUiOff: false },
  epoch: { value: 3 },
}))

vi.mock('@/utils/desktopShell', () => ({ isDesktopShell: () => state.desktop }))
vi.mock('@/utils/adminConsoleUrl', () => ({ isAdminConsoleSpa: () => state.adminConsole }))
vi.mock('@/utils/productReadAccountScope', () => ({ productReadAccountEpoch: state.epoch }))
vi.mock('@/stores/accountProfile', () => ({ useAccountProfileStore: () => state.account }))
vi.mock('@/stores/mods', () => ({ useModsStore: () => state.mods }))
vi.mock('./useVisibleNavItems', () => ({
  useVisibleNavItems: () => ({ visibleNavItems: { get value() { return [
    { key: 'settings', name: '系统设置' },
    { key: 'employee-workflow', name: '编制工作台' },
    { key: 'employee-space', name: '员工空间', parentKey: 'employee-workflow', modPath: '/private-route' },
    { key: 'invalid', name: 'https://example.com/wallet' },
    ...(state.ecosystem ? [{ key: 'ai-ecosystem', name: '智能生态' }] : []),
  ] } } }),
}))

describe('desktop navigation supplied to chat', () => {
  beforeEach(() => {
    state.desktop = state.account.workspaceReady = state.mods.isLoaded = true
    state.mods.loadedAccountEpoch = state.epoch.value = 3
    state.mods.mods = []
    state.account.userRole = 'tenant:user'
    state.account.permissions = []
    state.adminConsole = state.ecosystem = false
  })

  it('uses display-only navigation and exposes wallet controls only with the bridge', () => {
    const read = useDesktopNavigationContext()
    expect(read()).toContainEqual({
      id: 'model-payment', label: '模型服务', breadcrumb: ['系统设置', '智能与数据'], kind: 'page',
    })
    expect(read()).toContainEqual({
      id: 'employee-space', label: '员工空间', breadcrumb: ['编制工作台'], kind: 'page',
    })
    expect(read().some(row => row.kind === 'user_action' || row.id === 'invalid')).toBe(false)

    state.mods.mods = [{ id: MODEL_PAYMENT_BRIDGE_ID }]
    expect(read().filter(row => row.kind === 'user_action')).toEqual([
      { id: 'open-model-wallet', label: '打开修茈钱包', breadcrumb: ['系统设置', '智能与数据', '模型服务', '钱包与套餐'], kind: 'user_action' },
      { id: 'open-model-plans', label: '会员套餐', breadcrumb: ['系统设置', '智能与数据', '模型服务', '钱包与套餐'], kind: 'user_action' },
    ])
  })

  it('keeps the settings order and only includes sections available to this account', () => {
    const read = useDesktopNavigationContext()
    const settings = () => read().filter(row => row.breadcrumb[0] === '系统设置').map(row => row.id)
    expect(settings()).toEqual([
      'settings-group-account', 'profile-home',
      'settings-group-intelligence', 'model-payment', 'model-service-billing', 'intent', 'memory-v2',
      'settings-group-system', 'basic', 'mobile-pairing', 'extensions',
      'settings-group-about', 'distillation-versions', 'about',
    ])
    state.account.permissions = ['tenant.manage_roles']
    state.account.userRole = 'admin'
    state.mods.mods = [{ id: MODEL_PAYMENT_BRIDGE_ID }]
    expect(settings().slice(0, 16)).toEqual([
      'settings-group-account', 'profile-home', 'tenant-roles', 'settings-group-intelligence',
      'model-payment', 'model-service-billing', 'open-model-wallet', 'open-model-plans',
      'model-payment-balance', 'model-payment-recharge', 'model-payment-membership', 'model-payment-catalog',
      'audit-logs', 'intent', 'memory-v2', 'settings-group-system',
    ])
    expect(JSON.stringify(read())).not.toContain(state.account.marketUsername)
  })

  it('withholds stale or unverified workspace navigation and skips web clients', () => {
    const read = useDesktopNavigationContext()
    state.epoch.value++
    expect(read()).toEqual([])
    state.mods.loadedAccountEpoch = state.epoch.value
    state.account.workspaceReady = false
    expect(read()).toEqual([])
    state.account.workspaceReady = true
    state.desktop = false
    expect(useDesktopNavigationContext()()).toEqual([])
  })

  it('projects the actual employee market launcher only when visible in the current shell', () => {
    const read = useDesktopNavigationContext()
    const catalog = () => read().filter(item => item.id.startsWith('mod-store'))
    expect(catalog()).toEqual([])
    state.ecosystem = true
    expect(catalog()).toEqual([])
    state.account.userRole = 'user'
    expect(catalog()).toEqual([
      { id: 'mod-store', label: 'AI 市场', breadcrumb: ['智能生态'], kind: 'page' },
      { id: 'mod-store-employee', label: '员工', breadcrumb: ['智能生态', 'AI 市场'], kind: 'page' },
    ])
    state.adminConsole = true
    expect(catalog()).toEqual([])
  })
})
