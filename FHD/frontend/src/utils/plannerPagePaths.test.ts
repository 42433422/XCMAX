import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { LS_PLANNER_MOD_FACADE_ENABLED } from '@/constants/plannerMod'
import * as xcagiStorageKeys from '@/utils/xcagiStorageKeys'
import { invalidateTenantStorageScopeCache } from '@/utils/tenantStorageScope'
import { resolvePlannerPagePath } from './plannerPagePaths'

describe('plannerPagePaths', () => {
  beforeEach(() => {
    invalidateTenantStorageScopeCache()
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('maps planner pages when facade on', () => {
    const store: Record<string, string> = {
      [LS_PLANNER_MOD_FACADE_ENABLED]: '1',
    }
    vi.stubGlobal('localStorage', {
      getItem: (k: string) => store[k] ?? null,
    })
    vi.spyOn(xcagiStorageKeys, 'readActiveExtensionModIdFromStorage').mockReturnValue('')
    expect(resolvePlannerPagePath('/')).toBe('/mod/xcagi-planner-bridge/chat')
    expect(resolvePlannerPagePath('/brain')).toBe('/mod/xcagi-planner-bridge/brain')
  })

  it('keeps host chat when taiyangniao-pro is active extension', () => {
    const store: Record<string, string> = {
      [LS_PLANNER_MOD_FACADE_ENABLED]: '1',
    }
    vi.stubGlobal('localStorage', {
      getItem: (k: string) => store[k] ?? null,
    })
    vi.spyOn(xcagiStorageKeys, 'readActiveExtensionModIdFromStorage').mockReturnValue('taiyangniao-pro')
    expect(resolvePlannerPagePath('/')).toBe('/')
  })
})
