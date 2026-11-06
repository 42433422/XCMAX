import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { IndustryBaselinePlan, OnboardingIndustryCatalog } from '@/constants/platformShell'
import { LS_PRODUCT_FLOW_COMPLETED } from '@/constants/productFlow'
import { writeTenantScopedStorageItem } from '@/utils/tenantStorageScope'
import {
  clearHostPackSkippedSession,
  invalidateHostPackCompletionCache,
  isHostPackSkippedThisSession,
  isOnboardingEntryReady,
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

vi.mock('@/api/chat', () => ({
  default: { getConversations: vi.fn(async () => ({ success: true, sessions: [] })) },
}))

import { authApi } from '@/api/auth'
import { fetchIndustryBaseline, fetchOnboardingIndustryCatalog } from '@/utils/platformShellApi'
import { fetchProductSku } from '@/utils/productSku'
import { fetchWorkspacePrefs } from '@/utils/workspacePrefsApi'
import chatApi from '@/api/chat'

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
    vi.mocked(chatApi.getConversations).mockResolvedValue({ success: true, sessions: [] } as never)
  })

  afterEach(() => {
    vi.clearAllMocks()
    vi.restoreAllMocks()
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

  it('does not send a completed workspace back to setup when the baseline is missing', async () => {
    vi.mocked(fetchWorkspacePrefs).mockResolvedValue({
      success: true, owner_id: 'tenant:10', data: { product_flow_completed: true },
    })
    vi.mocked(fetchOnboardingIndustryCatalog).mockResolvedValue(industryCatalog(''))
    await expect(resolveHostPackOnboardingStep(true)).resolves.toBeNull()
  })

  it('does not send an account that already has conversations through first-run setup', async () => {
    vi.mocked(chatApi.getConversations).mockResolvedValue({ success: true, sessions: [{ session_id: 'kept' }] } as never)
    await expect(needsHostPackCompletion(true)).resolves.toBe(false)
  })

  it('does not require host pack when baseline ready', async () => {
    vi.mocked(fetchIndustryBaseline).mockResolvedValue({
      baseline_ready: true,
    } as IndustryBaselinePlan)
    await expect(needsHostPackCompletion(true)).resolves.toBe(false)
  })

  it('returns an expired host-pack result immediately and refreshes in the background', async () => {
    const start = 1_700_000_000_000
    vi.spyOn(Date, 'now').mockReturnValue(start)
    await expect(needsHostPackCompletion(false)).resolves.toBe(true)
    expect(fetchIndustryBaseline).toHaveBeenCalledTimes(1)
    vi.spyOn(Date, 'now').mockReturnValue(start + 65_000)
    let releaseBaseline!: (value: IndustryBaselinePlan) => void
    vi.mocked(fetchIndustryBaseline).mockReturnValue(new Promise((resolve) => { releaseBaseline = resolve }))
    await expect(needsHostPackCompletion(false)).resolves.toBe(true)
    await vi.waitFor(() => expect(fetchIndustryBaseline).toHaveBeenCalledTimes(2))
    releaseBaseline({ baseline_ready: true } as IndustryBaselinePlan)
    await vi.waitFor(() => expect(sessionStorage.getItem('xcagi_host_pack_needs_cache_v2')).toContain('"needs":false'))
    vi.restoreAllMocks()
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

  it('retains confirmed readiness when a background baseline refresh fails', async () => {
    vi.spyOn(Date, 'now').mockReturnValue(1_700_000_000_000)
    vi.mocked(fetchIndustryBaseline).mockResolvedValue({ baseline_ready: true } as IndustryBaselinePlan)
    await expect(needsHostPackCompletion()).resolves.toBe(false)
    const confirmed = sessionStorage.getItem('xcagi_host_pack_needs_cache_v2')
    vi.mocked(Date.now).mockReturnValue(1_700_000_065_000)
    vi.mocked(fetchIndustryBaseline).mockRejectedValue(new Error('industry-baseline HTTP 503'))

    await expect(needsHostPackCompletion()).resolves.toBe(false)
    await vi.waitFor(() => expect(fetchIndustryBaseline).toHaveBeenCalledTimes(2))
    expect(fetchIndustryBaseline).toHaveBeenLastCalledWith('涂料', true, { requireAvailable: true })
    expect(sessionStorage.getItem('xcagi_host_pack_needs_cache_v2')).toBe(confirmed)
  })

  it('requires onboarding when a background refresh confirms required packages are missing', async () => {
    vi.spyOn(Date, 'now').mockReturnValue(1_700_000_000_000)
    vi.mocked(fetchIndustryBaseline).mockResolvedValue({ baseline_ready: true } as IndustryBaselinePlan)
    await expect(needsHostPackCompletion()).resolves.toBe(false)
    vi.mocked(Date.now).mockReturnValue(1_700_000_065_000)
    vi.mocked(fetchIndustryBaseline).mockResolvedValue({
      baseline_ready: false, missing_required_mod_ids: ['required-mod'],
    } as IndustryBaselinePlan)

    await expect(needsHostPackCompletion()).resolves.toBe(false)
    await vi.waitFor(() => expect(sessionStorage.getItem('xcagi_host_pack_needs_cache_v2')).toContain('"needs":true'))
    await expect(resolveHostPackOnboardingStep()).resolves.toBe('host-pack')
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

  it('resolves company step when no selected industry', async () => {
    vi.mocked(fetchOnboardingIndustryCatalog).mockResolvedValue(industryCatalog(''))
    await expect(resolveHostPackOnboardingStep(true)).resolves.toBe('welcome')
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
    await expect(resolveHostPackOnboardingStep(true)).resolves.toBe('welcome')
    await expect(resolveHostPackOnboardingStep()).resolves.toBe('welcome')
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
    expect(fetchIndustryBaseline).toHaveBeenCalledWith('考勤', true, { requireAvailable: true })
    await expect(resolveHostPackOnboardingStep()).resolves.toBe('host-pack')
    expect(fetchWorkspacePrefs).toHaveBeenCalledTimes(1)
  })

  it('preserves a fixed customer delivery industry without asking the customer to choose again', async () => {
    vi.mocked(fetchOnboardingIndustryCatalog).mockResolvedValue(industryCatalog('饰品包装'))
    vi.mocked(fetchIndustryBaseline).mockResolvedValue({ baseline_ready: true } as IndustryBaselinePlan)
    await expect(resolveHostPackOnboardingStep(true)).resolves.toBeNull()
    expect(fetchIndustryBaseline).toHaveBeenCalledWith('饰品包装', true, { requireAvailable: true })
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
    await expect(resolveHostPackOnboardingStep()).resolves.toBe('welcome')
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
    await expect(resolveHostPackOnboardingStep(true)).resolves.toBe('welcome')
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

describe('isOnboardingEntryReady（账号定制待供应商交付不阻塞进入）', () => {
  it('宿主基础线装齐、仅账号定制待交付 → 就绪', () => {
    expect(
      isOnboardingEntryReady({
        baseline_ready: true,
        missing_required_mod_ids: [],
        missing_account_custom_mod_ids: ['taiyangniao-pro'],
      }),
    ).toBe(true)
  })

  it('产品侧必需项缺失 → 未就绪', () => {
    expect(
      isOnboardingEntryReady({
        baseline_ready: false,
        missing_required_mod_ids: ['xcagi-erp-domain-bridge'],
        missing_account_custom_mod_ids: [],
      }),
    ).toBe(false)
  })

  it('必需项里混有非账号定制项 → 未就绪', () => {
    expect(
      isOnboardingEntryReady({
        baseline_ready: false,
        missing_required_mod_ids: ['taiyangniao-pro', 'xcagi-erp-domain-bridge'],
        missing_account_custom_mod_ids: ['taiyangniao-pro'],
      }),
    ).toBe(false)
  })

  it('baseline_ready 为真 → 就绪', () => {
    expect(
      isOnboardingEntryReady({
        baseline_ready: true,
        missing_required_mod_ids: [],
        missing_account_custom_mod_ids: [],
      }),
    ).toBe(true)
  })

  it('plan 缺失或缺少必需项列表 → 未就绪', () => {
    expect(isOnboardingEntryReady(null)).toBe(false)
    expect(isOnboardingEntryReady({ baseline_ready: false, missing_required_mod_ids: [] })).toBe(false)
  })

  it('needsHostPackCompletion：仅账号定制待交付时不拦截', async () => {
    invalidateHostPackCompletionCache()
    clearHostPackSkippedSession()
    vi.mocked(fetchOnboardingIndustryCatalog).mockResolvedValue(industryCatalog('涂料'))
    vi.mocked(fetchIndustryBaseline).mockResolvedValue({
      baseline_ready: true,
      missing_required_mod_ids: [],
      missing_account_custom_mod_ids: ['taiyangniao-pro'],
    } as IndustryBaselinePlan)
    await expect(needsHostPackCompletion(true)).resolves.toBe(false)
  })
})


describe('required custom delivery remains enforced', () => {
  it.each([false, true])('does not exempt required packages merely because custom (ready=%s)', (ready) => {
    expect(isOnboardingEntryReady({ baseline_ready: ready,
      missing_required_mod_ids: ['private'], missing_account_custom_mod_ids: ['private'],
    })).toBe(false)
  })
})
