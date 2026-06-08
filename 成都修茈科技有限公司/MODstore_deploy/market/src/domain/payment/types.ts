export interface PaymentPlan {
  id: string
  name: string
  description?: string
  price: number
  features?: string[]
}

export interface OrderSummary {
  out_trade_no?: string
  order_id?: string
  status: string
  total_amount?: number
  subject?: string
}

/**
 * 与 modstore_server/payment_api.py `api_payment_entitlements` 字段对齐。
 */
export interface EntitlementItem {
  purchase_id: number
  catalog_id: number
  pkg_id?: string
  version?: string
  name: string
  /** 实付金额（元） */
  price_paid?: number
  /** ISO 字符串；后端无购买时间则为空串 */
  purchased_at?: string
}

export interface EntitlementList {
  items: EntitlementItem[]
  total: number
}
