import { describe, expect, it } from 'vitest'
import { deliverySeedModIds } from './deliverySeedPackages'

describe('delivery seed deferral', () => {
  it('excludes both legacy and runtime IDs while retaining delivered seeds', () => {
    expect(deliverySeedModIds({
      deferred_account_custom_mod_ids: ['legacy'],
      groups: [{ items: [{ mod_id: 'legacy', runtime_mod_id: 'runtime', delivery_deferred: true }] }],
      account_delivery_seed_packages: [{ mod_id: 'legacy' }, { mod_id: 'runtime' }, { mod_id: 'ready' }, { mod_id: 'ready' }],
    })).toEqual(['ready'])
  })
  it('also honors an item-level deferral and handles missing plans', () => {
    expect(deliverySeedModIds(undefined)).toEqual([])
    expect(deliverySeedModIds({
      groups: [{ items: [{ mod_id: 'legacy', runtime_mod_id: 'runtime', delivery_deferred: true }] }],
      account_delivery_seed_packages: [{ mod_id: 'runtime' }],
    })).toEqual([])
  })
})
