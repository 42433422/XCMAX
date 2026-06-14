import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { LS_OFFICE_EMPLOYEE_PACK_MOD_PAGES_ENABLED } from '@/constants/officeEmployeePackMod'
import { invalidateTenantStorageScopeCache } from '@/utils/tenantStorageScope'
import {
  resolveOfficeEmployeePagePath,
  resolveOfficeEmployeePageRedirectForRouteName,
  useOfficeEmployeePackModPages,
} from './officeEmployeePagePaths'

describe('officeEmployeePagePaths', () => {
  beforeEach(() => {
    invalidateTenantStorageScopeCache()
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('keeps host path when mod pages off', () => {
    vi.stubGlobal('localStorage', { getItem: () => null })
    expect(useOfficeEmployeePackModPages()).toBe(false)
    expect(resolveOfficeEmployeePagePath('/tools')).toBe('/tools')
    expect(resolveOfficeEmployeePageRedirectForRouteName('tools')).toBeNull()
  })

  it('maps tools when mod pages on', () => {
    const store: Record<string, string> = { [LS_OFFICE_EMPLOYEE_PACK_MOD_PAGES_ENABLED]: '1' }
    vi.stubGlobal('localStorage', { getItem: (k: string) => store[k] ?? null })
    expect(useOfficeEmployeePackModPages()).toBe(true)
    expect(resolveOfficeEmployeePagePath('/tools')).toBe(
      '/mod/xcagi-office-employee-pack-bridge/tools',
    )
    expect(resolveOfficeEmployeePageRedirectForRouteName('other-tools')).toBe(
      '/mod/xcagi-office-employee-pack-bridge/other-tools',
    )
  })
})
