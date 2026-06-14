import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { LS_PLANNER_MOD_FACADE_ENABLED } from '@/constants/plannerMod'
import { invalidateTenantStorageScopeCache } from '@/utils/tenantStorageScope'
import {
  resolvePlannerToolsRegistryPath,
  resolvePlannerToolsExecutePath,
  usePlannerModToolsFacade,
} from './plannerToolsPaths'

describe('plannerToolsPaths', () => {
  beforeEach(() => {
    invalidateTenantStorageScopeCache()
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('returns null registry path when facade off', () => {
    vi.stubGlobal('localStorage', { getItem: () => null })
    expect(usePlannerModToolsFacade()).toBe(false)
    expect(resolvePlannerToolsRegistryPath()).toBeNull()
    expect(resolvePlannerToolsExecutePath()).toBe('/api/tools/execute')
  })

  it('returns mod paths when facade on', () => {
    const store: Record<string, string> = { [LS_PLANNER_MOD_FACADE_ENABLED]: '1' }
    vi.stubGlobal('localStorage', { getItem: (k: string) => store[k] ?? null })
    expect(usePlannerModToolsFacade()).toBe(true)
    expect(resolvePlannerToolsRegistryPath()).toBe('/api/mod/xcagi-planner-bridge/tools/registry')
    expect(resolvePlannerToolsExecutePath()).toBe('/api/mod/xcagi-planner-bridge/tools/execute')
  })
})
