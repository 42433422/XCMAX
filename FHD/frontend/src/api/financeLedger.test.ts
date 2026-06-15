import { describe, it, expect } from 'vitest'
import { getUnifiedLedger } from './financeLedger'

describe('financeLedger', () => {
  it('getUnifiedLedger returns empty items by default', async () => {
    const result = await getUnifiedLedger()
    expect(result).toEqual({ items: [] })
  })

  it('getUnifiedLedger accepts params without error', async () => {
    const result = await getUnifiedLedger({ market_user_id: 1, limit: 10 })
    expect(result).toEqual({ items: [] })
  })

  it('getUnifiedLedger accepts empty params', async () => {
    const result = await getUnifiedLedger({})
    expect(result).toEqual({ items: [] })
  })
})
