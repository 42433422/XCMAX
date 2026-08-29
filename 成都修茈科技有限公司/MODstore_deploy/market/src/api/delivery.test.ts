import { beforeEach, describe, expect, it, vi } from 'vitest'
import { delivery } from './delivery'
import { get, post } from './http'
import { requestStreamResponse } from './shared'

vi.mock('./http', () => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('./shared', () => ({ requestStreamResponse: vi.fn() }))

describe('delivery api', () => {
  beforeEach(() => vi.clearAllMocks())

  it('读取客户本人的交付工单并提交验收', async () => {
    vi.mocked(get).mockResolvedValue({ items: [] })
    vi.mocked(post).mockResolvedValue({})
    await delivery.customerDeliveryList(20)
    await delivery.customerDeliveryDecision(17, 'accept', '客户本人验收通过')
    expect(get).toHaveBeenCalledWith('/api/customer-service/custom-deliveries', { limit: 20 })
    expect(post).toHaveBeenCalledWith('/api/customer-service/custom-deliveries/17/decision', { action: 'accept', note: '客户本人验收通过' })
  })

  it('从响应头保留一次性安装回执令牌', async () => {
    vi.mocked(requestStreamResponse).mockResolvedValue(
      new Response(new Blob(['employee']), {
        status: 200,
        headers: {
          'Content-Disposition': 'attachment; filename="review-pack.xcemp"',
          'X-Delivery-Receipt-Token': 'delivery-receipt-token-123',
        },
      }),
    )
    const result = await delivery.customerDeliveryDownload(17, {
      kind: 'employee',
      id: 'review-pack',
    })
    expect(requestStreamResponse).toHaveBeenCalledWith('/api/customer-service/custom-deliveries/17/artifacts/employee/download', {
      method: 'GET',
    })
    expect(result.filename).toBe('review-pack.xcemp')
    expect(result.receiptToken).toBe('delivery-receipt-token-123')
  })

  it('从定制交付工单发起真实支付单', async () => {
    vi.mocked(post).mockResolvedValue({ ok: true, order_id: 'CDP-001' })
    await delivery.customerDeliveryCheckout(17, 'alipay')
    expect(post).toHaveBeenCalledWith('/api/customer-service/custom-deliveries/17/payment-checkout', {
      pay_channel: 'alipay',
    })
  })

  it('拒绝没有回执令牌的下载响应', async () => {
    vi.mocked(requestStreamResponse).mockResolvedValue(new Response(new Blob(['bad'])))
    await expect(delivery.customerDeliveryDownload(17, { kind: 'module', id: 'review-mod' })).rejects.toThrow('缺少安装回执令牌')
  })
})
