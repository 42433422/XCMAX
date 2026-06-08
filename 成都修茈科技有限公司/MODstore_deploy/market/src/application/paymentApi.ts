import { requestJson } from '../infrastructure/http/client'
import type { EntitlementList, OrderSummary, PaymentPlan } from '../domain/payment/types'
import type { WalletBalance, WalletTransaction } from '../domain/wallet/types'

export function listPlans(): Promise<{ plans: PaymentPlan[] }> {
  return requestJson('/api/payment/plans')
}

export function queryOrder(outTradeNo: string): Promise<OrderSummary> {
  return requestJson(`/api/payment/query/${encodeURIComponent(outTradeNo)}`)
}

export function listEntitlements(): Promise<EntitlementList> {
  return requestJson('/api/payment/entitlements')
}

export function walletBalance(): Promise<WalletBalance> {
  return requestJson('/api/wallet/balance')
}

export function walletTransactions(limit = 50, offset = 0): Promise<{ transactions: WalletTransaction[]; total?: number }> {
  return requestJson(`/api/wallet/transactions?limit=${limit}&offset=${offset}`)
}
