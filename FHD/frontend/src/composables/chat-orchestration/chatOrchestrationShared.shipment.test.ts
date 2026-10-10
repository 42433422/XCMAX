import { afterEach, describe, expect, it } from 'vitest'
import { buildShipmentDownloadUrl } from './chatOrchestrationShared'

const ERP_LS = 'xcagi_erp_domain_mod_facade_enabled'
const BRIDGE = '/api/mod/xcagi-erp-domain-bridge/shipment/download/'

describe('buildShipmentDownloadUrl tenant-safe routing', () => {
  afterEach(() => localStorage.removeItem(ERP_LS))

  it('routes doc_name downloads to the tenant-scoped bridge path when the ERP facade is on', () => {
    localStorage.setItem(ERP_LS, '1')
    expect(buildShipmentDownloadUrl({ data: { doc_name: '发货单 1.xlsx' } })).toBe(
      `${BRIDGE}${encodeURIComponent('发货单 1.xlsx')}`,
    )
  })

  it('rewrites a legacy download_url returned by the backend instead of linking the 403 route', () => {
    localStorage.setItem(ERP_LS, '1')
    expect(buildShipmentDownloadUrl({ download_url: '/api/shipment/download/a.xlsx' })).toBe(`${BRIDGE}a.xlsx`)
  })

  it('keeps unrelated direct URLs untouched', () => {
    localStorage.setItem(ERP_LS, '1')
    expect(buildShipmentDownloadUrl({ download_url: '/api/ai/kitten/document/pickup/t1' })).toBe(
      '/api/ai/kitten/document/pickup/t1',
    )
  })

  it('returns an empty string when no document is present', () => {
    expect(buildShipmentDownloadUrl({ data: {} })).toBe('')
  })
})
