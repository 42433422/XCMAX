import { describe, expect, it, vi, beforeEach } from 'vitest'
import { wallet, payment, refunds } from './wallet'
import { req } from './shared'

vi.mock('./shared', () => ({
  req: vi.fn(),
}))

beforeEach(() => {
  vi.clearAllMocks()
})

describe('wallet api', () => {
  it('balance calls req', async () => {
    vi.mocked(req).mockResolvedValue({ balance: 100 })
    const res = await wallet.balance()
    expect(req).toHaveBeenCalledWith('/api/wallet/balance')
    expect(res).toEqual({ balance: 100 })
  })

  it('walletOverview uses default limit and offset', async () => {
    vi.mocked(req).mockResolvedValue({})
    await wallet.walletOverview()
    expect(req).toHaveBeenCalledWith('/api/wallet/overview?limit=20&offset=0')
  })

  it('walletOverview passes custom limit and offset', async () => {
    vi.mocked(req).mockResolvedValue({})
    await wallet.walletOverview(10, 5)
    expect(req).toHaveBeenCalledWith('/api/wallet/overview?limit=10&offset=5')
  })

  it('walletAdminSelfCredit calls req with POST', async () => {
    vi.mocked(req).mockResolvedValue({})
    await wallet.walletAdminSelfCredit(50, 'test')
    expect(req).toHaveBeenCalledWith('/api/wallet/admin-self-credit', expect.objectContaining({ method: 'POST' }))
  })

  it('recharge calls req with POST', async () => {
    vi.mocked(req).mockResolvedValue({})
    await wallet.recharge(100, 'desc')
    expect(req).toHaveBeenCalledWith('/api/wallet/recharge', expect.objectContaining({ method: 'POST' }))
  })

  it('transactions uses default limit and offset', async () => {
    vi.mocked(req).mockResolvedValue({})
    await wallet.transactions()
    expect(req).toHaveBeenCalledWith('/api/wallet/transactions?limit=50&offset=0')
  })
})

describe('payment api', () => {
  it('paymentPlans calls req', async () => {
    vi.mocked(req).mockResolvedValue([])
    await payment.paymentPlans()
    expect(req).toHaveBeenCalledWith('/api/payment/plans')
  })

  it('paymentMyPlan calls req', async () => {
    vi.mocked(req).mockResolvedValue({})
    await payment.paymentMyPlan()
    expect(req).toHaveBeenCalledWith('/api/payment/my-plan')
  })

  it('paymentQuery encodes orderId', async () => {
    vi.mocked(req).mockResolvedValue({})
    await payment.paymentQuery('ORD/123')
    expect(req).toHaveBeenCalledWith('/api/payment/query/ORD%2F123')
  })

  it('paymentQuery appends reconcile param', async () => {
    vi.mocked(req).mockResolvedValue({})
    await payment.paymentQuery('ORD1', { reconcile: true })
    expect(req).toHaveBeenCalledWith('/api/payment/query/ORD1?reconcile=true')
  })

  it('paymentOrders builds query string with status', async () => {
    vi.mocked(req).mockResolvedValue({})
    await payment.paymentOrders('paid', 10, 0)
    const call = vi.mocked(req).mock.calls[0] as any[]
    const url = call[0] as string
    expect(url).toContain('status=paid')
    expect(url).toContain('limit=10')
  })

  it('paymentDismissNonActiveOrders calls req with POST', async () => {
    vi.mocked(req).mockResolvedValue({})
    await payment.paymentDismissNonActiveOrders()
    expect(req).toHaveBeenCalledWith('/api/payment/orders/dismiss-non-active', expect.objectContaining({ method: 'POST' }))
  })

  it('paymentCancelOrder encodes orderNo', async () => {
    vi.mocked(req).mockResolvedValue({})
    await payment.paymentCancelOrder('ORD/1')
    expect(req).toHaveBeenCalledWith('/api/payment/cancel/ORD%2F1', expect.objectContaining({ method: 'POST' }))
  })

  it('paymentDiagnostics calls req', async () => {
    vi.mocked(req).mockResolvedValue({})
    await payment.paymentDiagnostics()
    expect(req).toHaveBeenCalledWith('/api/payment/diagnostics')
  })

  it('paymentEntitlements calls req', async () => {
    vi.mocked(req).mockResolvedValue({})
    await payment.paymentEntitlements()
    expect(req).toHaveBeenCalledWith('/api/payment/entitlements')
  })

  it('paymentCheckout throws when ok is not true and not false', async () => {
    vi.mocked(req)
      .mockResolvedValueOnce({ plan_id: 'p', request_id: 'r', timestamp: 1, signature: 's' })
      .mockResolvedValueOnce({ ok: null })
    await expect(payment.paymentCheckout({ plan_id: 'p' })).rejects.toThrow('支付下单返回异常')
  })

  it('paymentCheckout throws when type is empty', async () => {
    vi.mocked(req)
      .mockResolvedValueOnce({ plan_id: 'p', request_id: 'r', timestamp: 1, signature: 's' })
      .mockResolvedValueOnce({ ok: true, type: '' })
    await expect(payment.paymentCheckout({ plan_id: 'p' })).rejects.toThrow('缺少支付类型')
  })

  it('paymentCheckout throws for page type without redirect_url', async () => {
    vi.mocked(req)
      .mockResolvedValueOnce({ plan_id: 'p', request_id: 'r', timestamp: 1, signature: 's' })
      .mockResolvedValueOnce({ ok: true, type: 'page', redirect_url: '' })
    await expect(payment.paymentCheckout({ plan_id: 'p' })).rejects.toThrow('缺少跳转地址')
  })

  it('paymentCheckout throws for precreate type without order_id', async () => {
    vi.mocked(req)
      .mockResolvedValueOnce({ plan_id: 'p', request_id: 'r', timestamp: 1, signature: 's' })
      .mockResolvedValueOnce({ ok: true, type: 'precreate', order_id: '' })
    await expect(payment.paymentCheckout({ plan_id: 'p' })).rejects.toThrow('缺少订单号')
  })

  it('paymentCheckout returns checkout on success with page type', async () => {
    const checkout = { ok: true, type: 'page', redirect_url: 'https://pay.example.com' }
    vi.mocked(req)
      .mockResolvedValueOnce({ plan_id: 'p', request_id: 'r', timestamp: 1, signature: 's' })
      .mockResolvedValueOnce(checkout)
    const res = await payment.paymentCheckout({ plan_id: 'p' })
    expect(res).toEqual(checkout)
  })

  it('paymentCheckout returns checkout on success with precreate type', async () => {
    const checkout = { ok: true, type: 'precreate', order_id: 'ORD123' }
    vi.mocked(req)
      .mockResolvedValueOnce({ plan_id: 'p', request_id: 'r', timestamp: 1, signature: 's' })
      .mockResolvedValueOnce(checkout)
    const res = await payment.paymentCheckout({ plan_id: 'p' })
    expect(res).toEqual(checkout)
  })

  it('paymentCheckout returns ok:false without throwing', async () => {
    vi.mocked(req)
      .mockResolvedValueOnce({ plan_id: 'p', request_id: 'r', timestamp: 1, signature: 's' })
      .mockResolvedValueOnce({ ok: false, message: '余额不足' })
    const res = await payment.paymentCheckout({ plan_id: 'p' })
    expect(res.ok).toBe(false)
  })

  it('paymentCheckout passes pay_channel and pay_type', async () => {
    const checkout = { ok: true, type: 'page', redirect_url: 'https://pay.example.com' }
    vi.mocked(req)
      .mockResolvedValueOnce({ plan_id: 'p', request_id: 'r', timestamp: 1, signature: 's' })
      .mockResolvedValueOnce(checkout)
    await payment.paymentCheckout({ plan_id: 'p', pay_channel: 'alipay', pay_type: 'wap' })
    const secondCall = vi.mocked(req).mock.calls[1] as any[]
    const body = JSON.parse(secondCall[1].body as string)
    expect(body.pay_channel).toBe('alipay')
    expect(body.pay_type).toBe('wap')
  })
})

describe('refunds api', () => {
  it('refundsApply throws on ok:false', async () => {
    vi.mocked(req).mockResolvedValue({ ok: false, message: '不可退款' })
    await expect(refunds.refundsApply('ORD1', 'reason')).rejects.toThrow('不可退款')
  })

  it('refundsApply returns result on ok:true', async () => {
    vi.mocked(req).mockResolvedValue({ ok: true, refund_id: 1 })
    const res = await refunds.refundsApply('ORD1', 'reason')
    expect(res.ok).toBe(true)
  })

  it('refundsMy calls req', async () => {
    vi.mocked(req).mockResolvedValue([])
    await refunds.refundsMy()
    expect(req).toHaveBeenCalledWith('/api/refunds/my')
  })

  it('refundsAdminPending calls req', async () => {
    vi.mocked(req).mockResolvedValue([])
    await refunds.refundsAdminPending()
    expect(req).toHaveBeenCalledWith('/api/refunds/admin/pending')
  })

  it('refundsAdminReview calls req with POST', async () => {
    vi.mocked(req).mockResolvedValue({})
    await refunds.refundsAdminReview(1, 'approve', 'ok')
    expect(req).toHaveBeenCalledWith('/api/refunds/admin/1/review', expect.objectContaining({ method: 'POST' }))
  })
})
