/**
 * 数据库管理视图共享类型与格式化辅助（原单文件机械迁出）。
 */

export interface RefundAdminRow {
  id: number | string
  user_id?: number | string
  order_no?: string
  amount?: number
  reason?: string
  created_at?: string
}

export interface AssignableModRow {
  id: string
  name: string
}

export interface AdminUserRow {
  id: number | string
  username?: string
  email?: string
  is_admin?: boolean
  is_enterprise?: boolean
  mod_ids?: string[]
  created_at?: string
}

export type UserFilterMode = 'all' | 'enterprise' | 'non-enterprise'

export interface WalletRow {
  id: number | string
  user_id?: number | string
  balance: number
  updated_at?: string
}

export interface CatalogRow {
  id: number | string
  name?: string
  pkg_id?: string
  version?: string
  price: number
  downloads?: number
  created_at?: string
}

export interface TransactionRow {
  id: number | string
  user_id?: number | string
  amount: number
  txn_type?: string
  status?: string
  description?: string
  created_at?: string
}

export function formatTime(iso: string | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleString('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
}

export function errMsg(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}
