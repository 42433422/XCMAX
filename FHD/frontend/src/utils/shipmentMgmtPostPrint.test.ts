import { describe, expect, it } from 'vitest'
import { summarizeShipmentRecordsForAudit } from './shipmentMgmtPostPrint'

describe('shipmentMgmtPostPrint', () => {
  const rows = [
    {
      id: 42,
      purchase_unit: '客户A',
      model_number: 'M1',
      status: 'printed',
      created_at: new Date().toISOString(),
    },
    {
      id: 1,
      purchase_unit: '客户A',
      model_number: 'M0',
      status: 'draft',
      created_at: '2020-01-01T00:00:00.000Z',
    },
  ]

  it('summarizes totals and today count', () => {
    const r = summarizeShipmentRecordsForAudit(rows, '客户A', 42)
    expect(r.total).toBe(2)
    expect(r.todayCount).toBeGreaterThanOrEqual(1)
    expect(r.matchedRecord?.id).toBe(42)
    expect(r.headline).toContain('客户A')
  })

  it('handles missing order id', () => {
    const r = summarizeShipmentRecordsForAudit(rows, '', null)
    expect(r.detailLines.some((l) => l.includes('未带回 record_id'))).toBe(true)
  })

  it('handles empty rows', () => {
    const r = summarizeShipmentRecordsForAudit([], '单位', null)
    expect(r.total).toBe(0)
    expect(r.matchedRecord).toBeNull()
  })
})
