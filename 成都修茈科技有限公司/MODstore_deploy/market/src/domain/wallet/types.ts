/**
 * 与 modstore_server/market_api.py `api_wallet_balance` 字段对齐；
 * 经 Java 网关回传可能附加 `membership_reference_yuan`（见后端 WalletService#getMembershipReferenceLineYuan）。
 */
export interface WalletBalance {
  balance: number
  /** ISO 字符串；后端无更新时间则为空串 */
  updated_at?: string
  /** 会员随单赠送累计参考（元，整数） */
  membership_reference_yuan?: number
}

/**
 * 与 modstore_server/market_api.py `api_wallet_transactions` 单行字段对齐。
 * - `type` 即后端 `Transaction.txn_type`，前端历史代码也保留 `txn_type` 别名供兼容。
 */
export interface WalletTransaction {
  id?: number
  amount: number
  /** 后端字段名为 `type`，源自 `Transaction.txn_type` */
  type?: string
  /** 旧前端使用的别名，避免视图层立即改动 */
  txn_type?: string
  status?: string
  description?: string
  created_at?: string
}

export interface WalletTransactionList {
  transactions: WalletTransaction[]
  total: number
}
