import { describe, it, expect, vi } from 'vitest'

vi.mock('@/api/core', () => ({
  api: {
    post: vi.fn().mockResolvedValue({ success: true, filename: 'price_list.docx' }),
  },
}))

import { generate, type GeneratePriceListParams } from './priceList'
import { api } from '@/api/core'

describe('priceList', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('generate calls api.post with params', async () => {
    const params: GeneratePriceListParams = {
      customer_name: 'Test Customer',
      products: [
        { model_number: 'M001', name: 'Product A', spec: '100ml', unit: '瓶', unit_price: '10.00' },
      ],
    }
    const result = await generate(params)
    expect(api.post).toHaveBeenCalledWith('/api/price-list/generate', params)
    expect(result.success).toBe(true)
  })

  it('generate includes optional printer_name', async () => {
    const params: GeneratePriceListParams = {
      customer_name: 'Test Customer',
      products: [],
      printer_name: 'HP LaserJet',
    }
    await generate(params)
    expect(api.post).toHaveBeenCalledWith('/api/price-list/generate', params)
  })

  it('generate works with empty products', async () => {
    const params: GeneratePriceListParams = {
      customer_name: 'Test Customer',
      products: [],
    }
    await generate(params)
    expect(api.post).toHaveBeenCalled()
  })
})
