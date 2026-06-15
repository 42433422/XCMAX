import { describe, it, expect, beforeEach } from 'vitest'
import {
  buildTenantScopedStorageKey,
  resolveTenantStorageScope,
  setTenantStorageScopeCache,
  invalidateTenantStorageScopeCache,
} from './tenantStorageScope'

describe('tenantStorageScope', () => {
  beforeEach(() => {
    invalidateTenantStorageScopeCache()
  })

  it('uses FHD session user id when tenant and market user missing', () => {
    expect(
      resolveTenantStorageScope({
        localUserId: 42,
        accountKind: 'enterprise',
      }),
    ).toBe('session:42')
  })

  it('prefers tenant_id over market user', () => {
    expect(
      resolveTenantStorageScope({
        tenantId: 42,
        marketUserId: 9,
        accountKind: 'enterprise',
      }),
    ).toBe('tenant:42')
  })

  it('falls back to market user id', () => {
    expect(
      resolveTenantStorageScope({
        marketUserId: 7,
        marketUsername: 'demo',
      }),
    ).toBe('user:7')
  })

  it('uses platform:admin for admin without tenant', () => {
    expect(resolveTenantStorageScope({ accountKind: 'admin' })).toBe('platform:admin')
  })

  it('buildTenantScopedStorageKey appends scope suffix', () => {
    setTenantStorageScopeCache('tenant:3')
    expect(buildTenantScopedStorageKey('xcagi_workflow_ai_employees')).toBe(
      'xcagi_workflow_ai_employees:tenant:3',
    )
  })
})
