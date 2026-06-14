import { describe, it, expect } from 'vitest'
import { collectDeskEmployeeIdsFromCatalogItem } from './workflowEmployeeOnboard'

describe('workflowEmployeeOnboard', () => {
  it('collects ids from workflow_employees', () => {
    const ids = collectDeskEmployeeIdsFromCatalogItem({
      workflow_employees: [{ id: 'label_print' }, { id: 'wechat_msg' }],
    })
    expect(ids).toContain('label_print')
    expect(ids).toContain('wechat_msg')
  })

  it('falls back to employee.id', () => {
    const ids = collectDeskEmployeeIdsFromCatalogItem({
      employee: { id: 'shipment_mgmt' },
    })
    expect(ids).toEqual(['shipment_mgmt'])
  })

  it('returns empty for missing item', () => {
    expect(collectDeskEmployeeIdsFromCatalogItem(undefined)).toEqual([])
  })

  it('includes yuangong_runtime when listed in catalog', () => {
    const ids = collectDeskEmployeeIdsFromCatalogItem({
      workflow_employees: [{ id: 'yuangong_runtime' }],
    })
    expect(ids).toEqual(['yuangong_runtime'])
  })
})
