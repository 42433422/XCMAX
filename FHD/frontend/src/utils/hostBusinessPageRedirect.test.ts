import { describe, it, expect, beforeEach, vi } from 'vitest'

// Mock all the page path resolvers
const erpPathMock = vi.fn()
const erpRedirectMock = vi.fn()
const approvalPathMock = vi.fn()
const approvalRedirectMock = vi.fn()
const lanPathMock = vi.fn()
const lanRedirectMock = vi.fn()
const plannerPathMock = vi.fn()
const plannerRedirectMock = vi.fn()
const customerServicePathMock = vi.fn()
const customerServiceRedirectMock = vi.fn()
const modelPaymentPathMock = vi.fn()
const modelPaymentRedirectMock = vi.fn()
const officeEmployeePathMock = vi.fn()
const officeEmployeeRedirectMock = vi.fn()
const workflowRedirectMock = vi.fn()
const isAdminConsoleSpaMock = vi.fn()

vi.mock('@/utils/erpPagePaths', () => ({
  resolveErpPagePath: (p: string) => erpPathMock(p),
  resolveErpPageRedirectForRouteName: (n: string) => erpRedirectMock(n),
}))
vi.mock('@/utils/approvalPagePaths', () => ({
  resolveApprovalPagePath: (p: string) => approvalPathMock(p),
  resolveApprovalPageRedirectForRouteName: (n: string) => approvalRedirectMock(n),
}))
vi.mock('@/utils/lanPagePaths', () => ({
  resolveLanPagePath: (p: string) => lanPathMock(p),
  resolveLanPageRedirectForRouteName: (n: string) => lanRedirectMock(n),
}))
vi.mock('@/utils/plannerPagePaths', () => ({
  resolvePlannerPagePath: (p: string) => plannerPathMock(p),
  resolvePlannerPageRedirectForRouteName: (n: string) => plannerRedirectMock(n),
}))
vi.mock('@/utils/customerServicePagePaths', () => ({
  resolveCustomerServicePagePath: (p: string) => customerServicePathMock(p),
  resolveCustomerServicePageRedirectForRouteName: (n: string) => customerServiceRedirectMock(n),
}))
vi.mock('@/utils/modelPaymentPagePaths', () => ({
  resolveModelPaymentPagePath: (p: string) => modelPaymentPathMock(p),
  resolveModelPaymentPageRedirectForRouteName: (n: string) => modelPaymentRedirectMock(n),
}))
vi.mock('@/utils/officeEmployeePagePaths', () => ({
  resolveOfficeEmployeePagePath: (p: string) => officeEmployeePathMock(p),
  resolveOfficeEmployeePageRedirectForRouteName: (n: string) => officeEmployeeRedirectMock(n),
}))
vi.mock('@/utils/workflowPagePaths', () => ({
  resolveWorkflowPageRedirectForRouteName: (n: string) => workflowRedirectMock(n),
}))
vi.mock('@/utils/adminConsoleUrl', () => ({
  isAdminConsoleSpa: () => isAdminConsoleSpaMock(),
}))

import {
  resolveHostBusinessPagePath,
  resolveHostBusinessPageRedirect,
} from './hostBusinessPageRedirect'

describe('hostBusinessPageRedirect', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Default: not admin console, all resolvers return input unchanged
    isAdminConsoleSpaMock.mockReturnValue(false)
    erpPathMock.mockImplementation((p: string) => p)
    approvalPathMock.mockImplementation((p: string) => p)
    lanPathMock.mockImplementation((p: string) => p)
    plannerPathMock.mockImplementation((p: string) => p)
    customerServicePathMock.mockImplementation((p: string) => p)
    modelPaymentPathMock.mockImplementation((p: string) => p)
    officeEmployeePathMock.mockImplementation((p: string) => p)
    // Default: all redirect resolvers return null
    erpRedirectMock.mockReturnValue(null)
    approvalRedirectMock.mockReturnValue(null)
    lanRedirectMock.mockReturnValue(null)
    plannerRedirectMock.mockReturnValue(null)
    customerServiceRedirectMock.mockReturnValue(null)
    modelPaymentRedirectMock.mockReturnValue(null)
    officeEmployeeRedirectMock.mockReturnValue(null)
    workflowRedirectMock.mockReturnValue(null)
  })

  describe('resolveHostBusinessPagePath', () => {
    it('returns path as-is when admin console SPA and path starts with /', () => {
      isAdminConsoleSpaMock.mockReturnValue(true)
      const result = resolveHostBusinessPagePath('/admin/path')
      expect(result).toBe('/admin/path')
    })

    it('prepends / when admin console SPA and path does not start with /', () => {
      isAdminConsoleSpaMock.mockReturnValue(true)
      const result = resolveHostBusinessPagePath('admin/path')
      expect(result).toBe('/admin/path')
    })

    it('returns ERP path when ERP resolver returns different path', () => {
      erpPathMock.mockReturnValue('/mod/erp/products')
      const result = resolveHostBusinessPagePath('/products')
      expect(result).toBe('/mod/erp/products')
    })

    it('returns approval path when approval resolver returns different path', () => {
      approvalPathMock.mockReturnValue('/mod/approval/hub')
      const result = resolveHostBusinessPagePath('/approval-hub')
      expect(result).toBe('/mod/approval/hub')
    })

    it('returns model payment path when resolver returns different path', () => {
      modelPaymentPathMock.mockReturnValue('/mod/model-payment')
      const result = resolveHostBusinessPagePath('/model-payment')
      expect(result).toBe('/mod/model-payment')
    })

    it('returns LAN path when LAN resolver returns different path', () => {
      lanPathMock.mockReturnValue('/mod/lan-gate')
      const result = resolveHostBusinessPagePath('/lan-gate')
      expect(result).toBe('/mod/lan-gate')
    })

    it('returns planner path when planner resolver returns different path', () => {
      plannerPathMock.mockReturnValue('/mod/planner/chat')
      const result = resolveHostBusinessPagePath('/chat')
      expect(result).toBe('/mod/planner/chat')
    })

    it('returns office employee path when resolver returns different path', () => {
      officeEmployeePathMock.mockReturnValue('/mod/office/employees')
      const result = resolveHostBusinessPagePath('/office-employees')
      expect(result).toBe('/mod/office/employees')
    })

    it('returns customer service path as final fallback', () => {
      customerServicePathMock.mockReturnValue('/mod/customer-service')
      const result = resolveHostBusinessPagePath('/customer-service')
      expect(result).toBe('/mod/customer-service')
    })

    it('returns input when all resolvers return same path', () => {
      const result = resolveHostBusinessPagePath('/unknown')
      expect(result).toBe('/unknown')
    })

    it('checks ERP before approval', () => {
      erpPathMock.mockReturnValue('/erp-result')
      approvalPathMock.mockReturnValue('/approval-result')
      const result = resolveHostBusinessPagePath('/path')
      expect(result).toBe('/erp-result')
    })
  })

  describe('resolveHostBusinessPageRedirect', () => {
    it('returns null when admin console SPA', () => {
      isAdminConsoleSpaMock.mockReturnValue(true)
      const result = resolveHostBusinessPageRedirect('route-name')
      expect(result).toBeNull()
    })

    it('returns ERP redirect when available', () => {
      erpRedirectMock.mockReturnValue('/mod/erp')
      const result = resolveHostBusinessPageRedirect('erp-route')
      expect(result).toBe('/mod/erp')
    })

    it('returns approval redirect when ERP is null', () => {
      approvalRedirectMock.mockReturnValue('/mod/approval')
      const result = resolveHostBusinessPageRedirect('approval-route')
      expect(result).toBe('/mod/approval')
    })

    it('returns model payment redirect when ERP and approval are null', () => {
      modelPaymentRedirectMock.mockReturnValue('/mod/payment')
      const result = resolveHostBusinessPageRedirect('payment-route')
      expect(result).toBe('/mod/payment')
    })

    it('returns LAN redirect when earlier resolvers are null', () => {
      lanRedirectMock.mockReturnValue('/mod/lan')
      const result = resolveHostBusinessPageRedirect('lan-route')
      expect(result).toBe('/mod/lan')
    })

    it('returns planner redirect when earlier resolvers are null', () => {
      plannerRedirectMock.mockReturnValue('/mod/planner')
      const result = resolveHostBusinessPageRedirect('planner-route')
      expect(result).toBe('/mod/planner')
    })

    it('returns office employee redirect when earlier resolvers are null', () => {
      officeEmployeeRedirectMock.mockReturnValue('/mod/office')
      const result = resolveHostBusinessPageRedirect('office-route')
      expect(result).toBe('/mod/office')
    })

    it('returns workflow redirect when earlier resolvers are null', () => {
      workflowRedirectMock.mockReturnValue('/mod/workflow')
      const result = resolveHostBusinessPageRedirect('workflow-route')
      expect(result).toBe('/mod/workflow')
    })

    it('returns customer service redirect as final fallback', () => {
      customerServiceRedirectMock.mockReturnValue('/mod/customer-service')
      const result = resolveHostBusinessPageRedirect('cs-route')
      expect(result).toBe('/mod/customer-service')
    })

    it('returns null when all resolvers return null', () => {
      const result = resolveHostBusinessPageRedirect('unknown-route')
      expect(result).toBeNull()
    })

    it('returns first non-null redirect (ERP priority)', () => {
      erpRedirectMock.mockReturnValue('/erp')
      approvalRedirectMock.mockReturnValue('/approval')
      const result = resolveHostBusinessPageRedirect('route')
      expect(result).toBe('/erp')
    })
  })
})
