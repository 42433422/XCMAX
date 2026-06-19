import { req } from './shared'
import type {
  PaymentCheckoutBody,
  PaymentCheckoutInput,
  PaymentCheckoutResponse,
  PaymentSignResponse,
  RefundApplyResponse,
} from '../types/api'

export const wallet = {
  balance: () => req('/api/wallet/balance'),
  walletOverview: (limit = 20, offset = 0) =>
    req(`/api/wallet/overview?limit=${limit}&offset=${offset}`),
  walletAdminSelfCredit: (amount: number, description = '') =>
    req('/api/wallet/admin-self-credit', { method: 'POST', body: JSON.stringify({ amount, description }) }),
  recharge: (amount: number, description = '') => req('/api/wallet/recharge', { method: 'POST', body: JSON.stringify({ amount, description }) }),
  transactions: (limit = 50, offset = 0) => req(`/api/wallet/transactions?limit=${limit}&offset=${offset}`),
}

export const payment = {
  paymentPlans: () => req('/api/payment/plans'),
  paymentMyPlan: () => req('/api/payment/my-plan'),
  paymentQuery: (orderId: string, options?: { reconcile?: boolean }) => {
    const r = options?.reconcile ? '?reconcile=true' : ''
    return req(`/api/payment/query/${encodeURIComponent(orderId)}${r}`)
  },
  paymentOrders: (status = '', limit = 50, offset = 0) => {
    const q = new URLSearchParams({ limit: String(limit), offset: String(offset) })
    if (status) q.set('status', status)
    return req(`/api/payment/orders?${q}`)
  },
  paymentDismissNonActiveOrders: () =>
    req('/api/payment/orders/dismiss-non-active', { method: 'POST', body: '{}' }),
  paymentCancelOrder: (orderNo: string) => req(`/api/payment/cancel/${encodeURIComponent(orderNo)}`, { method: 'POST', body: '{}' }),
  paymentDiagnostics: () => req('/api/payment/diagnostics'),
  paymentEntitlements: () => req('/api/payment/entitlements'),
  paymentCheckout: async (data: PaymentCheckoutInput): Promise<PaymentCheckoutResponse> => {
    const sign = (await req('/api/payment/sign-checkout', {
      method: 'POST',
      body: JSON.stringify({
        plan_id: data?.plan_id ?? '',
        item_id: Number(data?.item_id ?? 0) || 0,
        total_amount: Number(data?.total_amount ?? 0) || 0,
        subject: data?.subject ?? '',
        wallet_recharge: Boolean(data?.wallet_recharge),
      }),
    })) as PaymentSignResponse
    const checkoutBody: PaymentCheckoutBody = {
      plan_id: sign.plan_id ?? '',
      item_id: sign.item_id ?? 0,
      total_amount: sign.total_amount ?? 0,
      subject: sign.subject ?? '',
      wallet_recharge: Boolean(sign.wallet_recharge),
      request_id: sign.request_id,
      timestamp: sign.timestamp,
      signature: sign.signature,
    }
    if (data?.pay_channel) checkoutBody.pay_channel = data.pay_channel
    if (data?.pay_type) checkoutBody.pay_type = data.pay_type
    const checkout = (await req('/api/payment/checkout', {
      method: 'POST',
      body: JSON.stringify(checkoutBody),
    })) as PaymentCheckoutResponse
    if (checkout?.ok === false) {
      return checkout
    }
    if (checkout?.ok !== true) {
      throw new Error('支付下单返回异常：缺少成功标识')
    }
    const payType = String(checkout.type || '').trim()
    if (!payType) {
      throw new Error('支付下单返回异常：缺少支付类型')
    }
    if (payType === 'page' || payType === 'wap') {
      const u = checkout.redirect_url
      if (!u || String(u).trim() === '') {
        throw new Error('支付下单返回异常：缺少跳转地址')
      }
    }
    if (payType === 'precreate' || payType === 'wechat_native') {
      const oid = checkout.order_id
      if (!oid || String(oid).trim() === '') {
        throw new Error('支付下单返回异常：缺少订单号')
      }
    }
    return checkout
  },
}

export const refunds = {
  refundsApply: async (orderNo: string, reason: string): Promise<RefundApplyResponse> => {
    const res = (await req('/api/refunds/apply', { method: 'POST', body: JSON.stringify({ order_no: orderNo, reason }) })) as RefundApplyResponse
    if (res?.ok === false) throw new Error(res.message || '退款申请失败')
    return res
  },
  refundsMy: () => req('/api/refunds/my'),
  refundsAdminPending: () => req('/api/refunds/admin/pending'),
  refundsAdminReview: (refundId: number, action: string, adminNote = '') =>
    req(`/api/refunds/admin/${encodeURIComponent(String(refundId))}/review`, {
      method: 'POST',
      body: JSON.stringify({ action, admin_note: adminNote }),
    }),
}
