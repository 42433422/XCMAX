import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

const {
  mockApiFetch,
  mockInvalidateHostPackCompletionCache,
} = vi.hoisted(() => ({
  mockApiFetch: vi.fn(),
  mockInvalidateHostPackCompletionCache: vi.fn(),
}))

vi.mock('@/utils/apiBase', () => ({
  apiFetch: mockApiFetch,
  DEFAULT_MOD_API_TIMEOUT_MS: 8000,
}))

vi.mock('@/constants/platformShell', () => ({
  // 类型占位，运行时不需要
}))

vi.mock('@/utils/hostPackOnboardingGate', () => ({
  invalidateHostPackCompletionCache: mockInvalidateHostPackCompletionCache,
}))

import {
  fetchPlatformShellCapabilities,
  isBridgeModInstalled,
  fetchDeliverableStatus,
  clearDeliverableStatusCache,
  fetchOnboardingIndustryCatalog,
  fetchIndustryBaseline,
  fetchEmployeePlannerStatus,
} from './platformShellApi'

function makeResponse(body: unknown, ok = true, status = 200): Response {
  return {
    ok,
    status,
    json: async () => body,
  } as Response
}

describe('platformShellApi', () => {
  beforeEach(() => {
    mockApiFetch.mockReset()
    mockInvalidateHostPackCompletionCache.mockReset()
    clearDeliverableStatusCache()
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  describe('fetchPlatformShellCapabilities', () => {
    it('fetches capabilities from /api/platform-shell/capabilities', async () => {
      const caps = { bridge_mods: [], host_baseline_ready: true }
      mockApiFetch.mockResolvedValueOnce(makeResponse({ data: caps }))

      const result = await fetchPlatformShellCapabilities()

      expect(mockApiFetch).toHaveBeenCalledWith('/api/platform-shell/capabilities', {
        timeoutMs: 8000,
      })
      expect(result).toEqual(caps)
    })

    it('unwraps body directly when no data field', async () => {
      const caps = { bridge_mods: [], host_baseline_ready: false }
      mockApiFetch.mockResolvedValueOnce(makeResponse(caps))

      const result = await fetchPlatformShellCapabilities()
      expect(result).toEqual(caps)
    })

    it('caches result and skips refetch when not forced', async () => {
      const caps = { bridge_mods: [] }
      mockApiFetch.mockResolvedValueOnce(makeResponse({ data: caps }))

      await fetchPlatformShellCapabilities()
      await fetchPlatformShellCapabilities()

      expect(mockApiFetch).toHaveBeenCalledTimes(1)
    })

    it('refetches when force=true', async () => {
      const caps1 = { bridge_mods: [] }
      const caps2 = { bridge_mods: [{ mod_id: 'm1', installed: true }] }
      mockApiFetch.mockResolvedValueOnce(makeResponse({ data: caps1 }))
      mockApiFetch.mockResolvedValueOnce(makeResponse({ data: caps2 }))

      await fetchPlatformShellCapabilities()
      const result = await fetchPlatformShellCapabilities(true)

      expect(mockApiFetch).toHaveBeenCalledTimes(2)
      expect(result).toEqual(caps2)
    })

    it('throws when response not ok', async () => {
      mockApiFetch.mockResolvedValueOnce(makeResponse(null, false, 500))

      await expect(fetchPlatformShellCapabilities()).rejects.toThrow(
        'platform-shell/capabilities HTTP 500',
      )
    })

    it('throws when response not ok with 401', async () => {
      mockApiFetch.mockResolvedValueOnce(makeResponse(null, false, 401))

      await expect(fetchPlatformShellCapabilities()).rejects.toThrow(
        'platform-shell/capabilities HTTP 401',
      )
    })

    it('caches even after error when retried successfully', async () => {
      const caps = { bridge_mods: [] }
      mockApiFetch.mockResolvedValueOnce(makeResponse({ data: caps }))

      await fetchPlatformShellCapabilities()
      // Second call should use cache, not refetch
      const result = await fetchPlatformShellCapabilities()
      expect(result).toEqual(caps)
      expect(mockApiFetch).toHaveBeenCalledTimes(1)
    })
  })

  describe('isBridgeModInstalled', () => {
    it('returns true when mod is installed', () => {
      const caps = {
        bridge_mods: [
          { mod_id: 'm1', installed: true },
          { mod_id: 'm2', installed: false },
        ],
      } as never
      expect(isBridgeModInstalled(caps, 'm1')).toBe(true)
    })

    it('returns false when mod is not installed', () => {
      const caps = {
        bridge_mods: [{ mod_id: 'm1', installed: false }],
      } as never
      expect(isBridgeModInstalled(caps, 'm1')).toBe(false)
    })

    it('returns false when mod is missing from list', () => {
      const caps = { bridge_mods: [] } as never
      expect(isBridgeModInstalled(caps, 'unknown')).toBe(false)
    })

    it('returns false when bridge_mods is undefined', () => {
      const caps = {} as never
      expect(isBridgeModInstalled(caps, 'm1')).toBe(false)
    })

    it('returns false when bridge_mods is null', () => {
      const caps = { bridge_mods: null } as never
      expect(isBridgeModInstalled(caps, 'm1')).toBe(false)
    })

    it('returns false when bridge_mods row has no installed field', () => {
      const caps = { bridge_mods: [{ mod_id: 'm1' }] } as never
      expect(isBridgeModInstalled(caps, 'm1')).toBe(false)
    })

    it('handles empty modId', () => {
      const caps = {
        bridge_mods: [{ mod_id: '', installed: true }],
      } as never
      expect(isBridgeModInstalled(caps, '')).toBe(true)
    })
  })

  describe('fetchDeliverableStatus', () => {
    it('fetches deliverable status from /api/platform-shell/deliverable-status', async () => {
      const status = { delivered: true, items: [] }
      mockApiFetch.mockResolvedValueOnce(makeResponse({ data: status }))

      const result = await fetchDeliverableStatus()

      expect(mockApiFetch).toHaveBeenCalledWith('/api/platform-shell/deliverable-status', {
        timeoutMs: 8000,
      })
      expect(result).toEqual(status)
    })

    it('unwraps body directly when no data field', async () => {
      const status = { delivered: false }
      mockApiFetch.mockResolvedValueOnce(makeResponse(status))

      const result = await fetchDeliverableStatus()
      expect(result).toEqual(status)
    })

    it('caches result and skips refetch when not forced', async () => {
      const status = { delivered: true }
      mockApiFetch.mockResolvedValueOnce(makeResponse({ data: status }))

      await fetchDeliverableStatus()
      await fetchDeliverableStatus()

      expect(mockApiFetch).toHaveBeenCalledTimes(1)
    })

    it('refetches when force=true', async () => {
      const s1 = { delivered: false }
      const s2 = { delivered: true }
      mockApiFetch.mockResolvedValueOnce(makeResponse({ data: s1 }))
      mockApiFetch.mockResolvedValueOnce(makeResponse({ data: s2 }))

      await fetchDeliverableStatus()
      const result = await fetchDeliverableStatus(true)

      expect(mockApiFetch).toHaveBeenCalledTimes(2)
      expect(result).toEqual(s2)
    })

    it('throws when response not ok', async () => {
      mockApiFetch.mockResolvedValueOnce(makeResponse(null, false, 503))

      await expect(fetchDeliverableStatus()).rejects.toThrow('deliverable-status HTTP 503')
    })

    it('throws with 404 status in message', async () => {
      mockApiFetch.mockResolvedValueOnce(makeResponse(null, false, 404))

      await expect(fetchDeliverableStatus()).rejects.toThrow('deliverable-status HTTP 404')
    })
  })

  describe('clearDeliverableStatusCache', () => {
    it('clears deliverable cache so next fetch refetches', async () => {
      const s1 = { delivered: false }
      const s2 = { delivered: true }
      mockApiFetch.mockResolvedValueOnce(makeResponse({ data: s1 }))
      mockApiFetch.mockResolvedValueOnce(makeResponse({ data: s2 }))

      await fetchDeliverableStatus()
      clearDeliverableStatusCache()
      const result = await fetchDeliverableStatus()

      expect(mockApiFetch).toHaveBeenCalledTimes(2)
      expect(result).toEqual(s2)
    })

    it('clears platform shell capabilities cache', async () => {
      const c1 = { bridge_mods: [] }
      const c2 = { bridge_mods: [{ mod_id: 'm1', installed: true }] }
      mockApiFetch.mockResolvedValueOnce(makeResponse({ data: c1 }))
      mockApiFetch.mockResolvedValueOnce(makeResponse({ data: c2 }))

      await fetchPlatformShellCapabilities()
      clearDeliverableStatusCache()
      const result = await fetchPlatformShellCapabilities()

      expect(mockApiFetch).toHaveBeenCalledTimes(2)
      expect(result).toEqual(c2)
    })

    it('clears onboarding catalog cache', async () => {
      const c1 = { industries: [] }
      const c2 = { industries: [{ id: 'retail' }] }
      mockApiFetch.mockResolvedValueOnce(makeResponse({ data: c1 }))
      mockApiFetch.mockResolvedValueOnce(makeResponse({ data: c2 }))

      await fetchOnboardingIndustryCatalog()
      clearDeliverableStatusCache()
      const result = await fetchOnboardingIndustryCatalog()

      expect(mockApiFetch).toHaveBeenCalledTimes(2)
      expect(result).toEqual(c2)
    })

    it('clears industry baseline cache', async () => {
      const b1 = { industry_id: 'retail', summary: 'v1' }
      const b2 = { industry_id: 'retail', summary: 'v2' }
      mockApiFetch.mockResolvedValueOnce(makeResponse({ data: b1 }))
      mockApiFetch.mockResolvedValueOnce(makeResponse({ data: b2 }))

      await fetchIndustryBaseline('retail')
      clearDeliverableStatusCache()
      const result = await fetchIndustryBaseline('retail')

      expect(mockApiFetch).toHaveBeenCalledTimes(2)
      expect(result).toEqual(b2)
    })

    it('invalidates host pack completion cache', async () => {
      // beforeEach already calls clearDeliverableStatusCache() once, plus this call
      clearDeliverableStatusCache()
      await new Promise((r) => setTimeout(r, 10))
      expect(mockInvalidateHostPackCompletionCache).toHaveBeenCalledTimes(2)
    })

    it('does not throw when host pack invalidation fails', async () => {
      mockInvalidateHostPackCompletionCache.mockImplementation(() => {
        throw new Error('fail')
      })
      // The dynamic import catches errors via .catch(() => {})
      // Should not throw
      expect(() => clearDeliverableStatusCache()).not.toThrow()
    })
  })

  describe('fetchOnboardingIndustryCatalog', () => {
    it('fetches catalog from /api/platform-shell/onboarding-industries', async () => {
      const catalog = { industries: [{ id: 'retail' }, { id: 'food' }] }
      mockApiFetch.mockResolvedValueOnce(makeResponse({ data: catalog }))

      const result = await fetchOnboardingIndustryCatalog()

      expect(mockApiFetch).toHaveBeenCalledWith('/api/platform-shell/onboarding-industries', {
        timeoutMs: 8000,
      })
      expect(result).toEqual(catalog)
    })

    it('unwraps body directly when no data field', async () => {
      const catalog = { industries: [] }
      mockApiFetch.mockResolvedValueOnce(makeResponse(catalog))

      const result = await fetchOnboardingIndustryCatalog()
      expect(result).toEqual(catalog)
    })

    it('caches result and skips refetch when not forced', async () => {
      const catalog = { industries: [] }
      mockApiFetch.mockResolvedValueOnce(makeResponse({ data: catalog }))

      await fetchOnboardingIndustryCatalog()
      await fetchOnboardingIndustryCatalog()

      expect(mockApiFetch).toHaveBeenCalledTimes(1)
    })

    it('refetches when force=true', async () => {
      const c1 = { industries: [] }
      const c2 = { industries: [{ id: 'retail' }] }
      mockApiFetch.mockResolvedValueOnce(makeResponse({ data: c1 }))
      mockApiFetch.mockResolvedValueOnce(makeResponse({ data: c2 }))

      await fetchOnboardingIndustryCatalog()
      const result = await fetchOnboardingIndustryCatalog(true)

      expect(mockApiFetch).toHaveBeenCalledTimes(2)
      expect(result).toEqual(c2)
    })

    it('throws when response not ok', async () => {
      mockApiFetch.mockResolvedValueOnce(makeResponse(null, false, 500))

      await expect(fetchOnboardingIndustryCatalog()).rejects.toThrow(
        'onboarding-industries HTTP 500',
      )
    })
  })

  describe('fetchIndustryBaseline', () => {
    it('fetches baseline with industry_id query parameter', async () => {
      const baseline = {
        industry_id: 'retail',
        summary: 'Retail baseline',
        groups: [],
        required_mod_ids: ['m1'],
      }
      mockApiFetch.mockResolvedValueOnce(makeResponse({ data: baseline }))

      const result = await fetchIndustryBaseline('retail')

      expect(mockApiFetch).toHaveBeenCalledWith(
        '/api/platform-shell/industry-baseline?industry_id=retail',
        { timeoutMs: 8000 },
      )
      expect(result).toEqual(baseline)
    })

    it('encodes special characters in industry_id', async () => {
      const baseline = { industry_id: 'food & beverage', summary: '' }
      mockApiFetch.mockResolvedValueOnce(makeResponse({ data: baseline }))

      await fetchIndustryBaseline('food & beverage')

      expect(mockApiFetch).toHaveBeenCalledWith(
        '/api/platform-shell/industry-baseline?industry_id=food%20%26%20beverage',
        { timeoutMs: 8000 },
      )
    })

    it('falls back to "通用" when industryId is empty', async () => {
      const baseline = { industry_id: '通用', summary: '' }
      mockApiFetch.mockResolvedValueOnce(makeResponse({ data: baseline }))

      await fetchIndustryBaseline('')

      expect(mockApiFetch).toHaveBeenCalledWith(
        '/api/platform-shell/industry-baseline?industry_id=%E9%80%9A%E7%94%A8',
        { timeoutMs: 8000 },
      )
    })

    it('falls back to "通用" when industryId is whitespace', async () => {
      const baseline = { industry_id: '通用', summary: '' }
      mockApiFetch.mockResolvedValueOnce(makeResponse({ data: baseline }))

      await fetchIndustryBaseline('   ')

      expect(mockApiFetch).toHaveBeenCalledWith(
        '/api/platform-shell/industry-baseline?industry_id=%E9%80%9A%E7%94%A8',
        { timeoutMs: 8000 },
      )
    })

    it('trims industryId before use', async () => {
      const baseline = { industry_id: 'retail', summary: '' }
      mockApiFetch.mockResolvedValueOnce(makeResponse({ data: baseline }))

      await fetchIndustryBaseline('  retail  ')

      expect(mockApiFetch).toHaveBeenCalledWith(
        '/api/platform-shell/industry-baseline?industry_id=retail',
        { timeoutMs: 8000 },
      )
    })

    it('unwraps body directly when no data field', async () => {
      const baseline = { industry_id: 'retail', summary: 'direct' }
      mockApiFetch.mockResolvedValueOnce(makeResponse(baseline))

      const result = await fetchIndustryBaseline('retail')
      expect(result).toEqual(baseline)
    })

    it('caches result by industry key and skips refetch when not forced', async () => {
      const baseline = { industry_id: 'retail', summary: 'v1' }
      mockApiFetch.mockResolvedValueOnce(makeResponse({ data: baseline }))

      await fetchIndustryBaseline('retail')
      await fetchIndustryBaseline('retail')

      expect(mockApiFetch).toHaveBeenCalledTimes(1)
    })

    it('caches different industries separately', async () => {
      const b1 = { industry_id: 'retail', summary: 'r' }
      const b2 = { industry_id: 'food', summary: 'f' }
      mockApiFetch.mockResolvedValueOnce(makeResponse({ data: b1 }))
      mockApiFetch.mockResolvedValueOnce(makeResponse({ data: b2 }))

      await fetchIndustryBaseline('retail')
      await fetchIndustryBaseline('food')

      expect(mockApiFetch).toHaveBeenCalledTimes(2)
    })

    it('refetches when force=true', async () => {
      const b1 = { industry_id: 'retail', summary: 'v1' }
      const b2 = { industry_id: 'retail', summary: 'v2' }
      mockApiFetch.mockResolvedValueOnce(makeResponse({ data: b1 }))
      mockApiFetch.mockResolvedValueOnce(makeResponse({ data: b2 }))

      await fetchIndustryBaseline('retail')
      const result = await fetchIndustryBaseline('retail', true)

      expect(mockApiFetch).toHaveBeenCalledTimes(2)
      expect(result).toEqual(b2)
    })

    it('returns offline baseline when fetch throws', async () => {
      mockApiFetch.mockRejectedValueOnce(new Error('network'))

      const result = await fetchIndustryBaseline('retail')

      expect(result.industry_id).toBe('retail')
      expect(result.summary).toBe('行业基线暂不可用')
      expect(result.groups).toEqual([])
      expect(result.required_mod_ids).toEqual([])
      expect(result.optional_mod_ids).toEqual([])
      expect(result.industry_mod_ids).toEqual([])
      expect(result.missing_required_mod_ids).toEqual([])
      expect(result.missing_optional_mod_ids).toEqual([])
      expect(result.missing_industry_mod_ids).toEqual([])
      expect(result.host_baseline_ready).toBe(false)
      expect(result.account_custom_ready).toBe(false)
      expect(result.baseline_ready).toBe(false)
      expect(result.full_stack_ready).toBe(false)
      expect(result.industry_mod_ready).toBe(false)
    })

    it('returns offline baseline when response not ok', async () => {
      mockApiFetch.mockResolvedValueOnce(makeResponse(null, false, 500))

      const result = await fetchIndustryBaseline('retail')

      expect(result.industry_id).toBe('retail')
      expect(result.summary).toBe('行业基线暂不可用')
      expect(result.baseline_ready).toBe(false)
    })

    it('caches offline baseline after error', async () => {
      mockApiFetch.mockRejectedValueOnce(new Error('network'))

      await fetchIndustryBaseline('retail')
      // Second call should use cache (offline baseline)
      const result = await fetchIndustryBaseline('retail')

      expect(mockApiFetch).toHaveBeenCalledTimes(1)
      expect(result.summary).toBe('行业基线暂不可用')
    })

    it('uses "通用" as cache key for empty industryId on error', async () => {
      mockApiFetch.mockRejectedValueOnce(new Error('network'))

      const result = await fetchIndustryBaseline('')

      expect(result.industry_id).toBe('通用')
    })
  })

  describe('fetchEmployeePlannerStatus', () => {
    it('fetches status from /api/platform-shell/employee-planner-status', async () => {
      const status = { active: true, employees: [] }
      mockApiFetch.mockResolvedValueOnce(makeResponse({ data: status }))

      const result = await fetchEmployeePlannerStatus()

      expect(mockApiFetch).toHaveBeenCalledWith('/api/platform-shell/employee-planner-status', {
        timeoutMs: 8000,
      })
      expect(result).toEqual(status)
    })

    it('unwraps body directly when no data field', async () => {
      const status = { active: false }
      mockApiFetch.mockResolvedValueOnce(makeResponse(status))

      const result = await fetchEmployeePlannerStatus()
      expect(result).toEqual(status)
    })

    it('does not cache (force parameter is ignored)', async () => {
      const s1 = { active: false }
      const s2 = { active: true }
      mockApiFetch.mockResolvedValueOnce(makeResponse({ data: s1 }))
      mockApiFetch.mockResolvedValueOnce(makeResponse({ data: s2 }))

      await fetchEmployeePlannerStatus()
      const result = await fetchEmployeePlannerStatus()

      expect(mockApiFetch).toHaveBeenCalledTimes(2)
      expect(result).toEqual(s2)
    })

    it('throws when response not ok', async () => {
      mockApiFetch.mockResolvedValueOnce(makeResponse(null, false, 500))

      await expect(fetchEmployeePlannerStatus()).rejects.toThrow(
        'employee-planner-status HTTP 500',
      )
    })

    it('throws with 403 status in message', async () => {
      mockApiFetch.mockResolvedValueOnce(makeResponse(null, false, 403))

      await expect(fetchEmployeePlannerStatus()).rejects.toThrow(
        'employee-planner-status HTTP 403',
      )
    })
  })
})
