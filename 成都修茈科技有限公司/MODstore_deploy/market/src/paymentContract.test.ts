import { describe, expect, it, vi } from 'vitest'

function installLocalStorage() {
  const store = new Map<string, string>()
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: unknown) => store.set(key, String(value)),
    removeItem: (key: string) => store.delete(key),
    clear: () => store.clear(),
  })
}

describe('payment API contract helpers', () => {
  it(
    'calls sign-checkout before checkout with canonical fields',
    { timeout: 30_000 },
    async () => {
      vi.resetModules()
      installLocalStorage()
      const calls: Array<{ url: unknown; body: unknown }> = []
      vi.stubGlobal(
        'fetch',
        vi.fn(async (url: RequestInfo | URL, opts: RequestInit = {}) => {
          calls.push({
            url,
            body: typeof opts.body === 'string' ? JSON.parse(opts.body) : null,
          })
          if (String(url).endsWith('/api/payment/sign-checkout')) {
            return new Response(
              JSON.stringify({
                plan_id: 'plan_basic',
                item_id: 0,
                total_amount: 9.9,
                subject: '基础版 MOD',
                wallet_recharge: false,
                request_id: 'req-1',
                timestamp: 1710000000,
                signature: 'sig',
              }),
              { status: 200, headers: { 'Content-Type': 'application/json' } },
            )
          }
          return new Response(
            JSON.stringify({ ok: true, order_id: 'MOD1', type: 'precreate', redirect_url: '', qr_code: 'qr' }),
            {
              status: 200,
              headers: { 'Content-Type': 'application/json' },
            },
          )
        }),
      )

      const { api } = await import('./api')
      const result = await api.paymentCheckout({ plan_id: 'plan_basic' })

      expect(result).toEqual({
        ok: true,
        order_id: 'MOD1',
        type: 'precreate',
        redirect_url: '',
        qr_code: 'qr',
      })
      expect(calls.map((c) => c.url)).toEqual([
        '/api/payment/sign-checkout',
        '/api/payment/checkout',
      ])
      expect(calls[1]?.body).toEqual({
        plan_id: 'plan_basic',
        item_id: 0,
        total_amount: 9.9,
        subject: '基础版 MOD',
        wallet_recharge: false,
        request_id: 'req-1',
        timestamp: 1710000000,
        signature: 'sig',
      })
    },
  )
})
