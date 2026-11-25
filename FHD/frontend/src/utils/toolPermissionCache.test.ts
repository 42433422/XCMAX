import { beforeEach, describe, expect, it, vi } from 'vitest'
import { setRuntimeTenantStorageScopeInput } from './tenantStorageScopeRuntime'
import { clearSessionPermissions, clearToolPermission, getToolPermission, listAuthorizedTools, setToolPermission } from './toolPermissionCache'

const state = vi.hoisted(() => ({ epoch: 0 }))
vi.mock('@/utils/authSessionCache', () => ({
  captureAuthSession: () => {
    const epoch = state.epoch
    return () => state.epoch === epoch
  },
}))

describe('account-scoped local tool permission hints', () => {
  beforeEach(() => {
    clearSessionPermissions()
    localStorage.clear()
    sessionStorage.clear()
    state.epoch++
    setRuntimeTenantStorageScopeInput({ tenantId: 9, localUserId: 1 })
  })

  it('never adopts a global persistent or session grant', () => {
    localStorage.setItem('xcagi_tool_permissions_persistent', JSON.stringify({ tool: { scope: 'persistent' } }))
    sessionStorage.setItem('xcagi_tool_permissions_session', JSON.stringify({ tool: { scope: 'session' } }))
    expect(getToolPermission('tool')).toBeNull()
    expect(listAuthorizedTools()).toEqual([])
  })

  it('isolates two accounts in the same tenant and does not revive old grants', () => {
    setToolPermission('tool', 'persistent')
    expect(getToolPermission('tool')).toBe('persistent')
    setRuntimeTenantStorageScopeInput({ tenantId: 9, localUserId: 2 })
    state.epoch++
    expect(getToolPermission('tool')).toBeNull()
    setToolPermission('tool', 'session')
    setRuntimeTenantStorageScopeInput({ tenantId: 9, localUserId: 1 })
    state.epoch++
    expect(getToolPermission('tool')).toBeNull()
    expect(listAuthorizedTools()).toEqual([])
  })

  it('retires grants on a new auth generation even if the account is unchanged', () => {
    setToolPermission('tool', 'persistent')
    state.epoch++
    expect(getToolPermission('tool')).toBeNull()
  })

  it('does not accept grants without a resolved account', () => {
    setRuntimeTenantStorageScopeInput({ tenantId: 9 })
    setToolPermission('tool', 'session')
    expect(getToolPermission('tool')).toBeNull()
    expect(listAuthorizedTools()).toEqual([])
  })

  it('supports explicit single tool removal and authorization projection invalidation', () => {
    setToolPermission('a', 'session')
    setToolPermission('b', 'persistent')
    clearToolPermission('a')
    expect(listAuthorizedTools()).toEqual([{ tool_id: 'b', scope: 'persistent' }])
    clearSessionPermissions()
    expect(listAuthorizedTools()).toEqual([])
  })
})
