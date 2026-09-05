import { req } from './shared'
import type {
  PaymentCheckoutBody,
  PaymentCheckoutInput,
  PaymentCheckoutResponse,
  PaymentOrder,
  PaymentSignResponse,
  RefundApplyResponse,
} from '../types/api'
import type { AccountLicensePlan } from '../domain/payment/types'

export interface WalletBalanceResponse extends Record<string, unknown> {
  balance?: number | string
  membership_reference_yuan?: number | string
}

export interface WalletTransactionResponse extends Record<string, unknown> {
  id: string | number
  created_at?: string | null
  type?: string | null
  amount?: number | string
  description?: string
  order_no?: string
  refund_no?: string
}

export interface WalletRefundResponse extends Record<string, unknown> {
  id: string | number
  refund_no?: string
  order_no: string
  amount: number | string
  reason?: string
  status?: string
  created_at?: string
}

export interface WalletOverviewResponse extends Record<string, unknown> {
  wallet?: WalletBalanceResponse
  transactions?: WalletTransactionResponse[]
  orders?: PaymentOrder[]
  order_total?: number
  refunds?: WalletRefundResponse[]
}

export interface PaymentMyPlanResponse extends Record<string, unknown> {
  plan?: PaymentPlan | null
  quotas?: Array<{ quota_type: string; remaining?: number; total?: number }>
}

export interface PaymentPlan extends Record<string, unknown> {
  id: string
  name?: string
  price: number
  description?: string
  features?: string[]
  requires_plan?: string | boolean | null
  expires_at?: string | null
}

export interface PaymentPlansResponse extends Record<string, unknown> {
  plans?: PaymentPlan[]
}

export interface AccountLicensePlansResponse extends Record<string, unknown> {
  plans?: AccountLicensePlan[]
}

export interface PaymentQueryResponse extends Record<string, unknown> {
  status?: string
}

export interface PaymentOrdersResponse extends Record<string, unknown> {
  orders?: PaymentOrder[]
}

export interface RefundListResponse extends Record<string, unknown> {
  refunds?: WalletRefundResponse[]
}

export const WALLET_READ_TIMEOUT_MS = 10_000
const walletReadOptions = { timeoutMs: WALLET_READ_TIMEOUT_MS }

export const wallet = {
  balance: () => req<WalletBalanceResponse>('/api/wallet/balance', walletReadOptions),
  walletOverview: (limit = 20, offset = 0) => req<WalletOverviewResponse>(`/api/wallet/overview?limit=${limit}&offset=${offset}`, walletReadOptions),
  walletAdminSelfCredit: (amount: number, description = '') =>
    req('/api/wallet/admin-self-credit', {
      method: 'POST',
      body: JSON.stringify({ amount, description }),
    }),
  recharge: (amount: number, description = '') =>
    req('/api/wallet/recharge', { method: 'POST', body: JSON.stringify({ amount, description }) }),
  transactions: (limit = 50, offset = 0) =>
    req<{ transactions?: WalletTransactionResponse[] }>(`/api/wallet/transactions?limit=${limit}&offset=${offset}`, walletReadOptions),
}

export const payment = {
  paymentPlans: () => req<PaymentPlansResponse>('/api/payment/plans'),
  paymentAccountPlans: () => req<AccountLicensePlansResponse>('/api/payment/account-plans'),
  paymentMyPlan: () => req<PaymentMyPlanResponse>('/api/payment/my-plan', walletReadOptions),
  paymentQuery: (orderId: string, options?: { reconcile?: boolean }) => {
    const r = options?.reconcile ? '?reconcile=true' : ''
    return req<PaymentQueryResponse>(`/api/payment/query/${encodeURIComponent(orderId)}${r}`)
  },
  paymentOrders: (status = '', limit = 50, offset = 0, options?: { timeoutMs: number }) => {
    const q = new URLSearchParams({ limit: String(limit), offset: String(offset) })
    if (status) q.set('status', status)
    return options ? req<PaymentOrdersResponse>(`/api/payment/orders?${q}`, options) : req<PaymentOrdersResponse>(`/api/payment/orders?${q}`)
  },
  paymentDismissNonActiveOrders: () =>
    req<{ ok?: boolean; message?: string; dismissed?: number }>('/api/payment/orders/dismiss-non-active', { method: 'POST', body: '{}' }),
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
    const res = (await req('/api/refunds/apply', {
      method: 'POST',
      body: JSON.stringify({ order_no: orderNo, reason }),
    })) as RefundApplyResponse
    if (res?.ok === false) throw new Error(res.message || '退款申请失败')
    return res
  },
  refundsMy: (options?: { timeoutMs: number }) => options
    ? req<RefundListResponse>('/api/refunds/my', options)
    : req<RefundListResponse>('/api/refunds/my'),
  refundsAdminPending: () => req<RefundListResponse>('/api/refunds/admin/pending'),
  refundsAdminReview: (refundId: number, action: string, adminNote = '') =>
    req(`/api/refunds/admin/${encodeURIComponent(String(refundId))}/review`, {
      method: 'POST',
      body: JSON.stringify({ action, admin_note: adminNote }),
    }),
}
