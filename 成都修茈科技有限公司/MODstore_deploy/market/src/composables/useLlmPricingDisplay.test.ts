import { describe, expect, it } from 'vitest'
import {
  formatPricePer1kLine,
  formatPricingDetail,
  modelOptionLabelWithPricing,
  providerTileMinPriceHint,
} from './useLlmPricingDisplay'

describe('useLlmPricingDisplay', () => {
  it('formatPricePer1kLine uses effective prices', () => {
    const line = formatPricePer1kLine({
      effective_input_per_1k: 0.009,
      effective_output_per_1k: 0.027,
    })
    expect(line).toContain('0.009')
    expect(line).toContain('0.027')
  })

  it('formatPricingDetail includes source and min charge', () => {
    const s = formatPricingDetail({
      source: 'db',
      input_price_per_1k: 0.006,
      output_price_per_1k: 0.018,
      min_charge: 0.02,
      service_fee_multiplier: 1.5,
      effective_input_per_1k: 0.009,
      effective_output_per_1k: 0.027,
      platform_billing_ok: true,
    })
    expect(s).toContain('已登记定价')
    expect(s).toContain('最低')
  })

  it('modelOptionLabelWithPricing appends price line', () => {
    const label = modelOptionLabelWithPricing(
      { id: 'gpt-4', pricing: { effective_input_per_1k: 0.01, effective_output_per_1k: 0.03 } },
      'gpt-4',
    )
    expect(label).toContain('gpt-4')
    expect(label).toContain('¥')
  })

  it('providerTileMinPriceHint picks minimum', () => {
    const hint = providerTileMinPriceHint(
      [
        { pricing: { min_charge: 0.05, effective_input_per_1k: 0.02 } },
        { pricing: { min_charge: 0.02, effective_input_per_1k: 0.05 } },
      ],
      null,
    )
    expect(hint).toBe('起价 ¥0.02')
  })
})
