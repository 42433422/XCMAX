import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { useAccountProfileStore } from '@/stores/accountProfile'
import { useVisibleNavItems } from './useVisibleNavItems'

// Match the admin build alias; exercise its real role whitelist and child filtering.
vi.mock('@/constants/adminOperatorNav', () => import('../../../admin-console/src/constants/adminOperatorNav'))
vi.mock('@/composables/useModRoutes', () => ({
  useModRoutes: () => ({ modMenuItems: ref([]) }),
}))

describe('employee surfaces after sidebar role filtering', () => {
  beforeEach(() => {
    localStorage.clear()
    setActivePinia(createPinia())
  })
  afterEach(() => vi.unstubAllEnvs())

  it.each(['enterprise', 'admin'] as const)('keeps all three distinct entries for %s', (kind) => {
    vi.stubEnv('VITE_XCMAX_ADMIN_CONSOLE', kind === 'admin' ? '1' : '')
    const account = useAccountProfileStore()
    account.accountKind = kind
    account.marketIsAdmin = kind === 'admin'
    account.marketIsEnterprise = kind === 'enterprise'
    const { menuItems, visibleNavItems } = useVisibleNavItems()
    const parent = menuItems.value.find(item => item.key === 'employee-workflow')
    const expected = ['employee-workbench', 'workflow-employee-space', 'workflow-employee-stitch-full']
    expect(parent?.children?.map(child => child.key)).toEqual(expected)
    expect(visibleNavItems.value.filter(item => item.parentKey === 'employee-workflow')
      .map(item => item.routeName)).toEqual(expected)
    expect(visibleNavItems.value.find(item => item.key === 'employee-workflow')?.routeName).toBe('employee-workbench')
  })

  it('preserves the invited tenant member permission boundary', () => {
    vi.stubEnv('VITE_XCMAX_ADMIN_CONSOLE', '')
    const account = useAccountProfileStore()
    account.accountKind = 'enterprise'
    account.userRole = 'tenant:7:member'
    account.tenantId = 7
    const { visibleNavItems } = useVisibleNavItems()
    expect(visibleNavItems.value.some(item => item.key === 'employee-workflow' || item.parentKey === 'employee-workflow')).toBe(false)
  })
})
