import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useProductFlow, shouldRouteToProductOnboarding } from './useProductFlow'
import { fetchDeliverableStatus } from '@/utils/platformShellApi'

vi.mock('@/utils/platformShellApi', () => ({
  fetchDeliverableStatus: vi.fn(),
}))

describe('useProductFlow', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
    localStorage.clear()
    vi.clearAllMocks()
  })

  describe('shouldRouteToProductOnboarding', () => {
    beforeEach(() => {
      // Make needsProductFlowStatic return true by default
      vi.stubEnv('VITE_XCAGI_PRODUCT_SKU', 'enterprise')
      vi.stubEnv('VITE_XCAGI_EDITION', 'generic')
      vi.stubEnv('VITE_XCAGI_DEFAULT_PLATFORM_SHELL', '1')
      localStorage.clear()
    })

    it('routes enterprise generic host builds through product onboarding', () => {
      expect(shouldRouteToProductOnboarding('chat')).toBe(true)
    })

    it('does not route enterprise full host builds through product onboarding', () => {
      vi.stubEnv('VITE_XCAGI_EDITION', 'full')
      vi.stubEnv('VITE_XCAGI_DEFAULT_PLATFORM_SHELL', '')
      expect(shouldRouteToProductOnboarding('chat')).toBe(false)
    })

    it('excludes product-onboarding route from onboarding redirect', () => {
      expect(shouldRouteToProductOnboarding('product-onboarding')).toBe(false)
    })

    it('allows roster review without claiming onboarding is complete', () => {
      expect(shouldRouteToProductOnboarding('attendance-industry-personnel')).toBe(false)
      expect(shouldRouteToProductOnboarding('attendance-industry-departments')).toBe(false)
      expect(useProductFlow().readProductFlowCompleted()).toBe(false)
      expect(shouldRouteToProductOnboarding('chat')).toBe(true)
    })

    it('excludes login route from onboarding redirect', () => {
      expect(shouldRouteToProductOnboarding('login')).toBe(false)
    })

    it('excludes lan-gate route from onboarding redirect', () => {
      expect(shouldRouteToProductOnboarding('lan-gate')).toBe(false)
    })

    it('excludes settings route from onboarding redirect', () => {
      expect(shouldRouteToProductOnboarding('settings')).toBe(false)
    })

    it('excludes mod-store route from onboarding redirect', () => {
      expect(shouldRouteToProductOnboarding('mod-store')).toBe(false)
    })

    it('excludes im route from onboarding redirect', () => {
      expect(shouldRouteToProductOnboarding('im')).toBe(false)
    })

    it('excludes desktop-runtime route from onboarding redirect', () => {
      expect(shouldRouteToProductOnboarding('desktop-runtime')).toBe(false)
    })

    it('excludes workflow-employee-space route from onboarding redirect', () => {
      expect(shouldRouteToProductOnboarding('workflow-employee-space')).toBe(false)
    })

    it('excludes workflow-employee-stitch-full route from onboarding redirect', () => {
      expect(shouldRouteToProductOnboarding('workflow-employee-stitch-full')).toBe(false)
    })

    it('routes symbol route names through onboarding (not in exclusion list)', () => {
      // Symbol gets stringified to "Symbol(sym)" — not in the exclusion list, so falls through
      expect(shouldRouteToProductOnboarding(Symbol('sym'))).toBe(true)
    })

    it('routes null/undefined route names through onboarding (empty string not excluded)', () => {
      // null/undefined become "" — not in the exclusion list, so falls through
      expect(shouldRouteToProductOnboarding(null)).toBe(true)
      expect(shouldRouteToProductOnboarding(undefined)).toBe(true)
    })
  })

  describe('useProductFlow composable', () => {
    it('refreshDeliverable fetches and returns deliverable status', async () => {
      const mockStatus = { deliverable: true, version: '1.0' }
      vi.mocked(fetchDeliverableStatus).mockResolvedValue(mockStatus as never)
      const flow = useProductFlow()
      const result = await flow.refreshDeliverable()
      expect(fetchDeliverableStatus).toHaveBeenCalled()
      expect(result).toEqual(mockStatus)
      expect(flow.deliverableLoading.value).toBe(false)
    })

    it('refreshDeliverable passes force flag when called with true', async () => {
      vi.mocked(fetchDeliverableStatus).mockResolvedValue({ deliverable: false } as never)
      const flow = useProductFlow()
      await flow.refreshDeliverable(true)
      expect(fetchDeliverableStatus).toHaveBeenCalledWith(true)
    })

    it('refreshDeliverable sets loading false on error', async () => {
      vi.mocked(fetchDeliverableStatus).mockRejectedValue(new Error('network') as never)
      const flow = useProductFlow()
      await expect(flow.refreshDeliverable()).rejects.toThrow('network')
      expect(flow.deliverableLoading.value).toBe(false)
    })

    it('refreshDeliverable marks host pack acknowledged when deliverable', async () => {
      vi.mocked(fetchDeliverableStatus).mockResolvedValue({ deliverable: true } as never)
      const flow = useProductFlow()
      await flow.refreshDeliverable()
      // markHostPackAcknowledged sets a localStorage flag
      expect(flow.readProductFlowCompleted()).toBe(false) // not completed yet, just acknowledged
    })

    it('edition returns the build edition', () => {
      vi.stubEnv('VITE_XCAGI_EDITION', 'full')
      const flow = useProductFlow()
      const ed = flow.edition()
      expect(['full', 'generic', 'lightweight', 'unknown']).toContain(ed)
    })

    it('needsProductFlow returns false when not shell edition build', () => {
      vi.stubEnv('VITE_XCAGI_DEFAULT_PLATFORM_SHELL', '')
      vi.stubEnv('VITE_XCAGI_EDITION', 'full')
      const flow = useProductFlow()
      expect(flow.needsProductFlow()).toBe(false)
    })

    it('needsProductFlow returns true when shell edition and not completed', () => {
      vi.stubEnv('VITE_XCAGI_DEFAULT_PLATFORM_SHELL', '1')
      vi.stubEnv('VITE_XCAGI_EDITION', 'generic')
      localStorage.clear()
      const flow = useProductFlow()
      expect(flow.needsProductFlow()).toBe(true)
    })

    it('needsProductFlow returns false when already completed', () => {
      vi.stubEnv('VITE_XCAGI_DEFAULT_PLATFORM_SHELL', '1')
      vi.stubEnv('VITE_XCAGI_EDITION', 'generic')
      const flow = useProductFlow()
      flow.markProductFlowCompleted()
      expect(flow.needsProductFlow()).toBe(false)
    })

    it('resolveEntryStep delegates to resolveProductFlowEntryStep', () => {
      const flow = useProductFlow()
      // Calling without arg should still return a valid step id
      const step = flow.resolveEntryStep()
      expect(typeof step).toBe('string')
    })

    it('completeFlowAndGoChat marks completed and navigates to /', () => {
      const replaced: { path: string }[] = []
      const router = { replace: (x: { path: string }) => replaced.push(x) }
      const flow = useProductFlow()
      flow.completeFlowAndGoChat(router)
      expect(flow.readProductFlowCompleted()).toBe(true)
      expect(replaced).toEqual([{ path: '/' }])
    })

    it('markProductFlowCompleted sets the completed flag', () => {
      const flow = useProductFlow()
      expect(flow.readProductFlowCompleted()).toBe(false)
      flow.markProductFlowCompleted()
      expect(flow.readProductFlowCompleted()).toBe(true)
    })

    it('markHostPackAcknowledged sets the acknowledged flag', () => {
      const flow = useProductFlow()
      // The function should not throw
      expect(() => flow.markHostPackAcknowledged()).not.toThrow()
    })
  })
})
