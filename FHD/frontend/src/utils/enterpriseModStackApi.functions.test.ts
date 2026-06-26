import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

const {
  mockFetchWorkspacePrefs,
  mockFetchOnboardingIndustryCatalog,
  mockFetchIndustryBaseline,
  mockBuildEnterpriseModStack,
} = vi.hoisted(() => ({
  mockFetchWorkspacePrefs: vi.fn(),
  mockFetchOnboardingIndustryCatalog: vi.fn(),
  mockFetchIndustryBaseline: vi.fn(),
  mockBuildEnterpriseModStack: vi.fn(),
}))

vi.mock('./workspacePrefsApi', () => ({
  fetchWorkspacePrefs: mockFetchWorkspacePrefs,
}))

vi.mock('./platformShellApi', () => ({
  fetchIndustryBaseline: mockFetchIndustryBaseline,
  fetchOnboardingIndustryCatalog: mockFetchOnboardingIndustryCatalog,
}))

vi.mock('@/constants/enterpriseModStack', () => ({
  buildEnterpriseModStack: mockBuildEnterpriseModStack,
}))

import {
  resolveEnterpriseModStack,
  invalidateEnterpriseModStackCache,
} from './enterpriseModStackApi'

function makeStack(overrides: Record<string, unknown> = {}) {
  return {
    industryId: 'retail',
    industryModId: null,
    industryLabel: 'Retail',
    customModIds: [],
    customLabels: {},
    packageModIds: [],
    hostLineModIds: [],
    stackLabel: 'Retail',
    stackShortLabel: 'Retail',
    ...overrides,
  }
}

describe('enterpriseModStackApi', () => {
  beforeEach(() => {
    mockFetchWorkspacePrefs.mockReset()
    mockFetchOnboardingIndustryCatalog.mockReset()
    mockFetchIndustryBaseline.mockReset()
    mockBuildEnterpriseModStack.mockReset()
    invalidateEnterpriseModStackCache()
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  describe('resolveEnterpriseModStack', () => {
    it('fetches baseline and builds stack with industry from prefs', async () => {
      mockFetchWorkspacePrefs.mockResolvedValueOnce({ data: { selected_industry_id: 'retail' } })
      mockFetchIndustryBaseline.mockResolvedValueOnce({ industry_id: 'retail' })
      const stack = makeStack({ industryId: 'retail' })
      mockBuildEnterpriseModStack.mockReturnValueOnce(stack)

      const result = await resolveEnterpriseModStack()

      expect(mockFetchWorkspacePrefs).toHaveBeenCalledTimes(1)
      expect(mockFetchIndustryBaseline).toHaveBeenCalledWith('retail', false)
      expect(mockBuildEnterpriseModStack).toHaveBeenCalled()
      expect(result).toBe(stack)
    })

    it('returns cached stack on second call without force', async () => {
      mockFetchWorkspacePrefs.mockResolvedValueOnce({ data: { selected_industry_id: 'retail' } })
      mockFetchIndustryBaseline.mockResolvedValueOnce({ industry_id: 'retail' })
      mockBuildEnterpriseModStack.mockReturnValueOnce(makeStack())

      await resolveEnterpriseModStack()
      const result = await resolveEnterpriseModStack()

      expect(mockFetchWorkspacePrefs).toHaveBeenCalledTimes(1)
      expect(result).toBeDefined()
    })

    it('refetches when force=true', async () => {
      mockFetchWorkspacePrefs.mockResolvedValue({ data: { selected_industry_id: 'retail' } })
      mockFetchIndustryBaseline.mockResolvedValue({ industry_id: 'retail' })
      mockBuildEnterpriseModStack.mockReturnValue(makeStack())

      await resolveEnterpriseModStack()
      await resolveEnterpriseModStack(true)

      expect(mockFetchWorkspacePrefs).toHaveBeenCalledTimes(2)
    })

    it('falls back to catalog when prefs industry is "通用"', async () => {
      mockFetchWorkspacePrefs.mockResolvedValueOnce({ data: { selected_industry_id: '' } })
      mockFetchOnboardingIndustryCatalog.mockResolvedValueOnce({ selected_industry_id: 'food' })
      mockFetchIndustryBaseline.mockResolvedValueOnce({ industry_id: 'food' })
      mockBuildEnterpriseModStack.mockReturnValueOnce(makeStack({ industryId: 'food' }))

      await resolveEnterpriseModStack()

      expect(mockFetchOnboardingIndustryCatalog).toHaveBeenCalledTimes(1)
      expect(mockFetchIndustryBaseline).toHaveBeenCalledWith('food', false)
    })

    it('falls back to catalog when prefs industry is whitespace', async () => {
      mockFetchWorkspacePrefs.mockResolvedValueOnce({ data: { selected_industry_id: '   ' } })
      mockFetchOnboardingIndustryCatalog.mockResolvedValueOnce({ selected_industry_id: 'food' })
      mockFetchIndustryBaseline.mockResolvedValueOnce({ industry_id: 'food' })
      mockBuildEnterpriseModStack.mockReturnValueOnce(makeStack({ industryId: 'food' }))

      await resolveEnterpriseModStack()

      expect(mockFetchOnboardingIndustryCatalog).toHaveBeenCalledTimes(1)
    })

    it('uses "通用" when prefs throws and catalog returns nothing', async () => {
      mockFetchWorkspacePrefs.mockRejectedValueOnce(new Error('network'))
      mockFetchOnboardingIndustryCatalog.mockResolvedValueOnce({})
      mockFetchIndustryBaseline.mockResolvedValueOnce({ industry_id: '通用' })
      mockBuildEnterpriseModStack.mockReturnValueOnce(makeStack({ industryId: '通用' }))

      await resolveEnterpriseModStack()

      expect(mockFetchIndustryBaseline).toHaveBeenCalledWith('通用', false)
    })

    it('uses catalog industry when prefs throws', async () => {
      mockFetchWorkspacePrefs.mockRejectedValueOnce(new Error('network'))
      mockFetchOnboardingIndustryCatalog.mockResolvedValueOnce({ selected_industry_id: 'food' })
      mockFetchIndustryBaseline.mockResolvedValueOnce({ industry_id: 'food' })
      mockBuildEnterpriseModStack.mockReturnValueOnce(makeStack({ industryId: 'food' }))

      await resolveEnterpriseModStack()

      expect(mockFetchIndustryBaseline).toHaveBeenCalledWith('food', false)
    })

    it('falls back to offline stack when fetchIndustryBaseline throws', async () => {
      mockFetchWorkspacePrefs.mockResolvedValueOnce({ data: { selected_industry_id: 'retail' } })
      mockFetchIndustryBaseline.mockRejectedValueOnce(new Error('network'))
      mockBuildEnterpriseModStack.mockReturnValueOnce(makeStack({ industryId: 'retail' }))

      const result = await resolveEnterpriseModStack()

      expect(result).toBeDefined()
      expect(mockBuildEnterpriseModStack).toHaveBeenCalled()
    })

    it('falls back to offline stack when fetchIndustryBaseline throws with "通用"', async () => {
      mockFetchWorkspacePrefs.mockResolvedValueOnce({ data: {} })
      mockFetchOnboardingIndustryCatalog.mockResolvedValueOnce({})
      mockFetchIndustryBaseline.mockRejectedValueOnce(new Error('network'))
      mockBuildEnterpriseModStack.mockReturnValueOnce(makeStack({ industryId: '通用' }))

      const result = await resolveEnterpriseModStack()

      expect(result).toBeDefined()
      // buildOfflineEnterpriseModStack calls buildEnterpriseModStack with industry_id '通用'
      const callArg = mockBuildEnterpriseModStack.mock.calls[0][0]
      expect(callArg.industry_id).toBe('通用')
    })

    it('uses "通用" when prefs data is null', async () => {
      mockFetchWorkspacePrefs.mockResolvedValueOnce(null)
      mockFetchOnboardingIndustryCatalog.mockResolvedValueOnce({ selected_industry_id: 'food' })
      mockFetchIndustryBaseline.mockResolvedValueOnce({ industry_id: 'food' })
      mockBuildEnterpriseModStack.mockReturnValueOnce(makeStack({ industryId: 'food' }))

      await resolveEnterpriseModStack()

      expect(mockFetchOnboardingIndustryCatalog).toHaveBeenCalledTimes(1)
    })

    it('uses "通用" when catalog throws', async () => {
      mockFetchWorkspacePrefs.mockResolvedValueOnce({ data: {} })
      mockFetchOnboardingIndustryCatalog.mockRejectedValueOnce(new Error('network'))
      mockFetchIndustryBaseline.mockResolvedValueOnce({ industry_id: '通用' })
      mockBuildEnterpriseModStack.mockReturnValueOnce(makeStack({ industryId: '通用' }))

      await resolveEnterpriseModStack()

      expect(mockFetchIndustryBaseline).toHaveBeenCalledWith('通用', false)
    })
  })

  describe('invalidateEnterpriseModStackCache', () => {
    it('does not throw', () => {
      expect(() => invalidateEnterpriseModStackCache()).not.toThrow()
    })

    it('forces next resolveEnterpriseModStack to refetch', async () => {
      mockFetchWorkspacePrefs.mockResolvedValue({ data: { selected_industry_id: 'retail' } })
      mockFetchIndustryBaseline.mockResolvedValue({ industry_id: 'retail' })
      mockBuildEnterpriseModStack.mockReturnValue(makeStack())

      await resolveEnterpriseModStack()
      invalidateEnterpriseModStackCache()
      await resolveEnterpriseModStack()

      expect(mockFetchWorkspacePrefs).toHaveBeenCalledTimes(2)
    })
  })
})
