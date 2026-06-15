import { describe, expect, it, vi, beforeEach } from 'vitest'
import * as customerServiceMod from '@/constants/customerServiceMod'
import {
  customerServiceHostPathFromModPath,
  resolveCustomerServicePagePath,
} from './customerServicePagePaths'

describe('customerServicePagePaths', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('maps customer service pages when mod pages enabled and routes available', () => {
    vi.spyOn(customerServiceMod, 'customerServiceModFrontendRoutesAvailable').mockReturnValue(
      true,
    )
    vi.stubGlobal('localStorage', { getItem: () => '1' })
    expect(resolveCustomerServicePagePath('/enterprise-customer-service')).toBe(
      '/mod/xcagi-customer-service-bridge/enterprise-customer-service',
    )
  })

  it('keeps host path when mod routes are not bundled', () => {
    vi.spyOn(customerServiceMod, 'customerServiceModFrontendRoutesAvailable').mockReturnValue(
      false,
    )
    vi.stubGlobal('localStorage', { getItem: () => '1' })
    expect(resolveCustomerServicePagePath('/enterprise-customer-service')).toBe(
      '/enterprise-customer-service',
    )
  })

  it('maps mod customer service paths back to host paths', () => {
    expect(
      customerServiceHostPathFromModPath(
        '/mod/xcagi-customer-service-bridge/enterprise-customer-service',
      ),
    ).toBe('/enterprise-customer-service')
    expect(
      customerServiceHostPathFromModPath(
        '/mod/xcagi-customer-service-bridge/internal-customer-service',
      ),
    ).toBe('/internal-customer-service')
  })
})
