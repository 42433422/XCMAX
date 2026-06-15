import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { LS_LAN_MOD_FACADE_ENABLED } from '@/constants/lanMod'
import { invalidateTenantStorageScopeCache } from '@/utils/tenantStorageScope'
import {
  resolveLanPagePath,
  resolveLanPageRedirectForRouteName,
  useLanModPages,
} from './lanPagePaths'

describe('lanPagePaths', () => {
  beforeEach(() => {
    invalidateTenantStorageScopeCache()
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('keeps host path when facade off', () => {
    vi.stubGlobal('localStorage', { getItem: () => null })
    expect(useLanModPages()).toBe(false)
    expect(resolveLanPagePath('/lan-gate')).toBe('/lan-gate')
    expect(resolveLanPageRedirectForRouteName('lan-gate')).toBeNull()
  })

  it('maps lan-gate when facade on', () => {
    const store: Record<string, string> = { [LS_LAN_MOD_FACADE_ENABLED]: '1' }
    vi.stubGlobal('localStorage', { getItem: (k: string) => store[k] ?? null })
    expect(useLanModPages()).toBe(true)
    expect(resolveLanPagePath('/lan-gate')).toBe('/mod/xcagi-lan-license-bridge/lan-gate')
    expect(resolveLanPageRedirectForRouteName('lan-gate')).toBe(
      '/mod/xcagi-lan-license-bridge/lan-gate',
    )
  })

  it('preserves query string', () => {
    const store: Record<string, string> = { [LS_LAN_MOD_FACADE_ENABLED]: '1' }
    vi.stubGlobal('localStorage', { getItem: (k: string) => store[k] ?? null })
    expect(resolveLanPagePath('/lan-gate?foo=1')).toBe(
      '/mod/xcagi-lan-license-bridge/lan-gate?foo=1',
    )
  })
})
