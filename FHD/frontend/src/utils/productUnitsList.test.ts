import { describe, expect, it } from 'vitest'
import { productUnitsArrayFromApi } from './productUnitsList'

describe('productUnitsList', () => {
  it('returns empty for non-object', () => {
    expect(productUnitsArrayFromApi(null)).toEqual([])
    expect(productUnitsArrayFromApi('x')).toEqual([])
  })

  it('reads data array', () => {
    expect(productUnitsArrayFromApi({ data: [{ id: 1 }] })).toEqual([{ id: 1 }])
  })

  it('reads units array', () => {
    expect(productUnitsArrayFromApi({ units: ['A'] })).toEqual(['A'])
  })

  it('reads nested data.units', () => {
    expect(productUnitsArrayFromApi({ data: { units: ['B'] } })).toEqual(['B'])
  })
})
