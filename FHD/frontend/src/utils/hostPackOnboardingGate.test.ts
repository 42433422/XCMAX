import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { IndustryBaselinePlan, OnboardingIndustryCatalog } from '@/constants/platformShell'
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

vi.mock('@/constants/productFlow', () => ({
  defaultOnboardingIndustryId: () => '涂料',
  readProductFlowCompleted: vi.fn(() => false),
}))

import { authApi } from '@/api/auth'
import { readProductFlowCompleted } from '@/constants/productFlow'
import { fetchIndustryBaseline, fetchOnboardingIndustryCatalog } from '@/utils/platformShellApi'
import { fetchProductSku } from '@/utils/productSku'

describe('hostPackOnboardingGate', () => {
  beforeEach(() => {
    sessionStorage.clear()
    invalidateHostPackCompletionCache()
    vi.mocked(fetchProductSku).mockResolvedValue('enterprise')
    vi.mocked(fetchOnboardingIndustryCatalog).mockResolvedValue({
      selected_industry_id: '涂料',
    } as OnboardingIndustryCatalog)
    vi.mocked(fetchIndustryBaseline).mockResolvedValue({ baseline_ready: false } as IndustryBaselinePlan)
    vi.mocked(readProductFlowCompleted).mockReturnValue(false)
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
    vi.mocked(fetchIndustryBaseline).mockResolvedValue({ baseline_ready: true } as IndustryBaselinePlan)
    await expect(needsHostPackCompletion(true)).resolves.toBe(false)
  })

  it('keeps a completed product flow out of host onboarding after an update', async () => {
    vi.mocked(readProductFlowCompleted).mockReturnValue(true)

    await expect(needsHostPackCompletion(true)).resolves.toBe(false)

    expect(fetchProductSku).not.toHaveBeenCalled()
    expect(authApi.validateSession).not.toHaveBeenCalled()
    expect(fetchOnboardingIndustryCatalog).not.toHaveBeenCalled()
    expect(fetchIndustryBaseline).not.toHaveBeenCalled()
    expect(sessionStorage.getItem('xcagi_host_pack_needs_cache_v1')).toContain('"needs":false')
  })

  it('reuses the short session cache for a deep-link reload', async () => {
    vi.mocked(fetchIndustryBaseline).mockResolvedValue({ baseline_ready: true } as IndustryBaselinePlan)
    await expect(needsHostPackCompletion(false)).resolves.toBe(false)
    await expect(needsHostPackCompletion(false)).resolves.toBe(false)
    expect(fetchIndustryBaseline).toHaveBeenCalledTimes(1)
    expect(sessionStorage.getItem('xcagi_host_pack_needs_cache_v1')).toContain('"needs":false')
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
    vi.mocked(fetchOnboardingIndustryCatalog).mockResolvedValue({
      selected_industry_id: '',
    } as OnboardingIndustryCatalog)
    await expect(resolveHostPackOnboardingStep(true)).resolves.toBe('industry')
  })

  it('returns null when baseline ready', async () => {
    vi.mocked(fetchIndustryBaseline).mockResolvedValue({ baseline_ready: true } as IndustryBaselinePlan)
    await expect(resolveHostPackOnboardingStep(true)).resolves.toBe(null)
  })
})
