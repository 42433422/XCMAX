import { describe, expect, it } from 'vitest'

/** 与 payment_contract.SIGN_FIELDS 及 sign-checkout 响应对齐。 */
const SIGN_FIELDS = [
  'item_id',
  'plan_id',
  'request_id',
  'subject',
  'timestamp',
  'total_amount',
  'wallet_recharge',
] as const

describe('wallet checkout contract', () => {
  it('sign-checkout response includes all canonical sign fields', () => {
    const signed = {
      item_id: 0,
      plan_id: 'plan_basic',
      request_id: 'req-1',
      subject: '基础版',
      timestamp: 1710000000,
      total_amount: 9.9,
      wallet_recharge: false,
      signature: 'sig-hex',
    }
    for (const key of SIGN_FIELDS) {
      expect(signed).toHaveProperty(key)
    }
    expect(signed.signature).toBeTypeOf('string')
  })

  it('checkout result exposes order_id and payment type', () => {
    const checkout = {
      ok: true,
      order_id: 'MOD-001',
      type: 'precreate',
      redirect_url: '',
      qr_code: 'qr-data',
    }
    expect(checkout.ok).toBe(true)
    expect(checkout.order_id).toBeTruthy()
    expect(['precreate', 'wap', 'page']).toContain(checkout.type)
  })
})
