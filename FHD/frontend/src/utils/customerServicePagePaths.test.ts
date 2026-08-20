import { describe, expect, it, vi, beforeEach } from 'vitest'
import * as customerServiceMod from '@/constants/customerServiceMod'
import {
  customerServiceHostPathFromModPath,
  resolveCustomerServicePagePath,
  resolveCustomerServicePageRedirectForRouteName,
} from './customerServicePagePaths'

describe('customerServicePagePaths', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('maps customer service pages when mod pages enabled and routes available', () => {
    vi.spyOn(customerServiceMod, 'customerServiceModFrontendRoutesAvailable').mockReturnValue(true)
    vi.stubGlobal('localStorage', { getItem: () => '1' })
    expect(resolveCustomerServicePagePath('/enterprise-customer-service')).toBe(
      '/mod/xcagi-customer-service-bridge/enterprise-customer-service',
    )
  })

  it('keeps host path when mod routes are not bundled', () => {
    vi.spyOn(customerServiceMod, 'customerServiceModFrontendRoutesAvailable').mockReturnValue(false)
    vi.stubGlobal('localStorage', { getItem: () => '1' })
    expect(resolveCustomerServicePagePath('/enterprise-customer-service')).toBe('/enterprise-customer-service')
  })

  it('maps mod customer service paths back to host paths', () => {
    expect(customerServiceHostPathFromModPath('/mod/xcagi-customer-service-bridge/enterprise-customer-service')).toBe(
      '/enterprise-customer-service',
    )
    expect(customerServiceHostPathFromModPath('/mod/xcagi-customer-service-bridge/internal-customer-service')).toBe(
      '/internal-customer-service',
    )
  })

  it('normalizes a host path without a leading slash', () => {
    vi.spyOn(customerServiceMod, 'customerServiceModFrontendRoutesAvailable').mockReturnValue(true)
    vi.stubGlobal('localStorage', { getItem: () => '1' })
    expect(resolveCustomerServicePagePath('enterprise-customer-service')).toBe(
      '/mod/xcagi-customer-service-bridge/enterprise-customer-service',
    )
  })

  it('keeps host path when mod pages disabled', () => {
    vi.spyOn(customerServiceMod, 'customerServiceModFrontendRoutesAvailable').mockReturnValue(true)
    vi.stubGlobal('localStorage', { getItem: () => null })
    expect(resolveCustomerServicePagePath('/enterprise-customer-service')).toBe('/enterprise-customer-service')
    expect(resolveCustomerServicePageRedirectForRouteName('enterprise-customer-service')).toBeNull()
  })

  it('keeps unknown host path unchanged when mod pages on', () => {
    vi.spyOn(customerServiceMod, 'customerServiceModFrontendRoutesAvailable').mockReturnValue(true)
    vi.stubGlobal('localStorage', { getItem: () => '1' })
    expect(resolveCustomerServicePagePath('/unknown/page')).toBe('/unknown/page')
  })

  it('maps redirect route name when mod pages on', () => {
    vi.spyOn(customerServiceMod, 'customerServiceModFrontendRoutesAvailable').mockReturnValue(true)
    vi.stubGlobal('localStorage', { getItem: () => '1' })
    expect(resolveCustomerServicePageRedirectForRouteName('internal-customer-service')).toBe(
      '/mod/xcagi-customer-service-bridge/internal-customer-service',
    )
    expect(resolveCustomerServicePageRedirectForRouteName('some-unknown-route')).toBeNull()
  })

  it('returns null for empty or unrecognized mod path', () => {
    expect(customerServiceHostPathFromModPath('')).toBeNull()
    expect(customerServiceHostPathFromModPath('/other-mod/path')).toBeNull()
  })
})
