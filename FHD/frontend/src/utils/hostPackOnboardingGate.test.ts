import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { IndustryBaselinePlan, OnboardingIndustryCatalog } from '@/constants/platformShell'
import { LS_PRODUCT_FLOW_COMPLETED } from '@/constants/productFlow'
import { writeTenantScopedStorageItem } from '@/utils/tenantStorageScope'
import {
  clearHostPackSkippedSession,
  invalidateHostPackCompletionCache,
  isHostPackSkippedThisSession,
  markHostPackSkippedThisSession,
  needsHostPackCompletion,
  resolveHostPackOnboardingStep,
  shouldRouteToHostPackOnboarding,
} from './hostPackOnboardingGate'

vi.mock('@/api/auth', () => ({
  authApi: {
    validateSession: vi.fn(async () => ({
      success: true,
      data: { account_kind: 'enterprise', market_is_admin: false },
    })),
  },
}))

vi.mock('@/utils/productSku', () => ({
  fetchProductSku: vi.fn(async () => 'enterprise'),
  isEnterpriseEdition: (sku: string) => sku === 'enterprise',
}))

vi.mock('@/utils/platformShellApi', () => ({
  fetchOnboardingIndustryCatalog: vi.fn(async () => ({ selected_industry_id: '涂料' })),
  fetchIndustryBaseline: vi.fn(async () => ({ baseline_ready: false })),
}))

vi.mock('@/utils/workspacePrefsApi', () => ({
  fetchWorkspacePrefs: vi.fn(),
}))

import { authApi } from '@/api/auth'
import { fetchIndustryBaseline, fetchOnboardingIndustryCatalog } from '@/utils/platformShellApi'
import { fetchProductSku } from '@/utils/productSku'
import { fetchWorkspacePrefs } from '@/utils/workspacePrefsApi'

function industryCatalog(selectedIndustryId = '涂料'): OnboardingIndustryCatalog {
  return {
    owner_id: 'tenant:10',
    selected_industry_id: selectedIndustryId,
    open_industry_ids: ['涂料'],
    open_packages: [{ industry_id: '涂料', mod_id: 'coating-industry', product_name: '涂料', selectable: true }],
  }
}

describe('hostPackOnboardingGate', () => {
  beforeEach(() => {
    sessionStorage.clear()
    localStorage.clear()
    invalidateHostPackCompletionCache()
    vi.mocked(fetchProductSku).mockResolvedValue('enterprise')
    vi.mocked(fetchOnboardingIndustryCatalog).mockResolvedValue(industryCatalog())
    vi.mocked(fetchWorkspacePrefs).mockResolvedValue({ success: true, owner_id: 'tenant:10', data: {} })
    vi.mocked(fetchIndustryBaseline).mockResolvedValue({
      baseline_ready: false,
    } as IndustryBaselinePlan)
    vi.mocked(authApi.validateSession).mockResolvedValue({
      success: true,
      data: { account_kind: 'enterprise', market_is_admin: false },
    })
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  it('exempts onboarding and mod-store routes', () => {
    expect(shouldRouteToHostPackOnboarding('product-onboarding')).toBe(false)
    expect(shouldRouteToHostPackOnboarding('mod-store')).toBe(false)
    expect(shouldRouteToHostPackOnboarding('employee-workflow')).toBe(false)
    expect(shouldRouteToHostPackOnboarding('workflow-employee-space')).toBe(false)
    expect(shouldRouteToHostPackOnboarding('workflow-employee-stitch-full')).toBe(false)
    expect(shouldRouteToHostPackOnboarding('chat')).toBe(true)
  })

  it('requires host pack when enterprise baseline not ready', async () => {
    await expect(needsHostPackCompletion(true)).resolves.toBe(true)
  })

  it('does not require host pack when baseline ready', async () => {
    vi.mocked(fetchIndustryBaseline).mockResolvedValue({
      baseline_ready: true,
    } as IndustryBaselinePlan)
    await expect(needsHostPackCompletion(true)).resolves.toBe(false)
  })

  it('reuses the short session cache for a deep-link reload', async () => {
    vi.mocked(fetchIndustryBaseline).mockResolvedValue({
      baseline_ready: true,
    } as IndustryBaselinePlan)
    await expect(needsHostPackCompletion(false)).resolves.toBe(false)
    await expect(needsHostPackCompletion(false)).resolves.toBe(false)
    expect(fetchIndustryBaseline).toHaveBeenCalledTimes(1)
    expect(sessionStorage.getItem('xcagi_host_pack_needs_cache_v2')).toContain('"needs":false')
  })

  it('skips gate for admin account session', async () => {
    vi.mocked(authApi.validateSession).mockResolvedValue({
      success: true,
      data: { account_kind: 'admin', market_is_admin: true },
    })
    await expect(needsHostPackCompletion(true)).resolves.toBe(false)
  })

  it('honors skip-this-session after user defers', async () => {
    markHostPackSkippedThisSession()
    expect(isHostPackSkippedThisSession()).toBe(true)
    await expect(needsHostPackCompletion(true)).resolves.toBe(false)
  })

  it('clears skip flag on login reset helper', async () => {
    markHostPackSkippedThisSession()
    clearHostPackSkippedSession()
    await expect(needsHostPackCompletion(true)).resolves.toBe(true)
  })

  it('resolves host-pack step when industry already selected', async () => {
    await expect(resolveHostPackOnboardingStep(true)).resolves.toBe('host-pack')
  })

  it('resolves industry step when no selected industry', async () => {
    vi.mocked(fetchOnboardingIndustryCatalog).mockResolvedValue(industryCatalog(''))
    await expect(resolveHostPackOnboardingStep(true)).resolves.toBe('industry')
  })

  it('returns null when baseline ready', async () => {
    vi.mocked(fetchIndustryBaseline).mockResolvedValue({
      baseline_ready: true,
    } as IndustryBaselinePlan)
    await expect(resolveHostPackOnboardingStep(true)).resolves.toBe(null)
  })

  it('asks a new enterprise workspace to choose an industry even with all required mods preinstalled', async () => {
    vi.mocked(fetchOnboardingIndustryCatalog).mockResolvedValue(industryCatalog(''))
    vi.mocked(fetchIndustryBaseline).mockResolvedValue({ baseline_ready: true, missing_required_mod_ids: [] } as unknown as IndustryBaselinePlan)
    await expect(resolveHostPackOnboardingStep(true)).resolves.toBe('industry')
    await expect(resolveHostPackOnboardingStep()).resolves.toBe('industry')
    expect(fetchWorkspacePrefs).toHaveBeenCalledTimes(1)
    expect(fetchIndustryBaseline).not.toHaveBeenCalled()
  })

  it('keeps an already completed workspace usable while its local preference hydration is pending', async () => {
    vi.mocked(fetchOnboardingIndustryCatalog).mockResolvedValue(industryCatalog(''))
    vi.mocked(fetchIndustryBaseline).mockResolvedValue({ baseline_ready: true } as IndustryBaselinePlan)
    let releasePrefs!: (value: Awaited<ReturnType<typeof fetchWorkspacePrefs>>) => void
    vi.mocked(fetchWorkspacePrefs).mockReturnValue(new Promise((resolve) => { releasePrefs = resolve }))
    const result = resolveHostPackOnboardingStep(true)
    await vi.waitFor(() => expect(fetchWorkspacePrefs).toHaveBeenCalledTimes(1))
    expect(localStorage.getItem(`${LS_PRODUCT_FLOW_COMPLETED}:tenant:10`)).toBeNull()
    expect(sessionStorage.getItem('xcagi_host_pack_needs_cache_v2')).toBeNull()

    releasePrefs({ success: true, owner_id: 'tenant:10', data: { product_flow_completed: true } })
    await expect(result).resolves.toBeNull()
  })

  it('uses a persisted industry binding when the catalog has not refreshed yet', async () => {
    vi.mocked(fetchOnboardingIndustryCatalog).mockResolvedValue(industryCatalog(''))
    vi.mocked(fetchWorkspacePrefs).mockResolvedValue({ success: true, owner_id: 'tenant:10', data: { selected_industry_id: '考勤' } })
    await expect(resolveHostPackOnboardingStep(true)).resolves.toBe('host-pack')
    expect(fetchIndustryBaseline).toHaveBeenCalledWith('考勤', true)
    await expect(resolveHostPackOnboardingStep()).resolves.toBe('host-pack')
    expect(fetchWorkspacePrefs).toHaveBeenCalledTimes(1)
  })

  it('preserves a fixed customer delivery industry without asking the customer to choose again', async () => {
    vi.mocked(fetchOnboardingIndustryCatalog).mockResolvedValue(industryCatalog('饰品包装'))
    vi.mocked(fetchIndustryBaseline).mockResolvedValue({ baseline_ready: true } as IndustryBaselinePlan)
    await expect(resolveHostPackOnboardingStep(true)).resolves.toBeNull()
    expect(fetchIndustryBaseline).toHaveBeenCalledWith('饰品包装', true)
    expect(fetchWorkspacePrefs).not.toHaveBeenCalled()
  })

  it.each([[], [{ industry_id: '涂料', mod_id: 'coating-industry', product_name: '涂料', selectable: false }]])(
    'does not send an unbound account into an industry picker with no permitted choice (%j)',
    async (packages) => {
      vi.mocked(fetchOnboardingIndustryCatalog).mockResolvedValue({ ...industryCatalog(''), open_packages: packages })
      await expect(resolveHostPackOnboardingStep(true)).resolves.toBeNull()
      expect(fetchWorkspacePrefs).not.toHaveBeenCalled()
      expect(fetchIndustryBaseline).not.toHaveBeenCalled()
    },
  )

  it('allows an offline workspace through and retries the first-use check after connectivity returns', async () => {
    vi.mocked(fetchOnboardingIndustryCatalog).mockResolvedValue(industryCatalog(''))
    vi.mocked(fetchWorkspacePrefs).mockRejectedValueOnce(new Error('offline'))
    await expect(resolveHostPackOnboardingStep(true)).resolves.toBeNull()
    expect(sessionStorage.getItem('xcagi_host_pack_needs_cache_v2')).toBeNull()
    await expect(resolveHostPackOnboardingStep()).resolves.toBe('industry')
  })

  it('allows an unavailable industry catalog through without changing onboarding state', async () => {
    vi.mocked(fetchOnboardingIndustryCatalog).mockRejectedValueOnce(new Error('offline'))
    await expect(resolveHostPackOnboardingStep(true)).resolves.toBeNull()
    expect(fetchWorkspacePrefs).not.toHaveBeenCalled()
    expect(sessionStorage.getItem('xcagi_host_pack_needs_cache_v2')).toBeNull()
  })

  it.each([null, 'tenant:20'])('does not classify a workspace when preference ownership is unresolved (%s)', async (ownerId) => {
    vi.mocked(fetchOnboardingIndustryCatalog).mockResolvedValue(industryCatalog(''))
    vi.mocked(fetchWorkspacePrefs).mockResolvedValue({ success: true, owner_id: ownerId, data: {} })
    await expect(resolveHostPackOnboardingStep(true)).resolves.toBeNull()
    expect(sessionStorage.getItem('xcagi_host_pack_needs_cache_v2')).toBeNull()
  })

  it('does not inherit completion from another workspace and preserves completion for the matching owner', async () => {
    vi.mocked(fetchOnboardingIndustryCatalog).mockResolvedValue(industryCatalog(''))
    vi.mocked(fetchIndustryBaseline).mockResolvedValue({ baseline_ready: true } as IndustryBaselinePlan)
    writeTenantScopedStorageItem(LS_PRODUCT_FLOW_COMPLETED, '1', 'tenant:20')
    await expect(resolveHostPackOnboardingStep(true)).resolves.toBe('industry')
    writeTenantScopedStorageItem(LS_PRODUCT_FLOW_COMPLETED, '1', 'tenant:10')
    await expect(resolveHostPackOnboardingStep(true)).resolves.toBeNull()
  })

  it('does not apply an in-flight first-use result after the user skips or the session changes', async () => {
    vi.mocked(fetchOnboardingIndustryCatalog).mockResolvedValue(industryCatalog(''))
    let releasePrefs!: (value: Awaited<ReturnType<typeof fetchWorkspacePrefs>>) => void
    vi.mocked(fetchWorkspacePrefs).mockReturnValue(new Promise((resolve) => { releasePrefs = resolve }))
    const result = resolveHostPackOnboardingStep(true)
    await vi.waitFor(() => expect(fetchWorkspacePrefs).toHaveBeenCalledTimes(1))
    markHostPackSkippedThisSession()
    releasePrefs({ success: true, owner_id: 'tenant:10', data: {} })
    await expect(result).resolves.toBeNull()
    await expect(resolveHostPackOnboardingStep(true)).resolves.toBeNull()
    expect(sessionStorage.getItem('xcagi_host_pack_needs_cache_v2')).toBeNull()
  })
})
