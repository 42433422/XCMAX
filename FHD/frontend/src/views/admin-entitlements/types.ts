// AdminEntitlementsView 拆分出的共享类型与常量

export type AdminUser = {
  id: number
  username: string
  email?: string
  is_admin?: boolean
  is_enterprise?: boolean
  mod_ids?: string[]
  tier?: string
  industry_id?: string
  account_tier?: string
  budget_range?: string
  entitled_industries?: string[]
}

export type LocalProfile = {
  market_user_id?: number | null
  tier: string
  industry_id: string
  account_tier?: string
  budget_range?: string
  entitled_industries?: string[]
}

export type WalletRow = {
  id?: number
  user_id?: number
  balance?: number | string | null
  updated_at?: string
}

export type AssignableMod = { id: string; name?: string }
export type WorkflowEmployeeRow = {
  id?: string
  label?: string
  name?: string
  title?: string
  panel_title?: string
  panel_summary?: string
}
export type LocalModRow = {
  id?: string
  name?: string
  version?: string
  is_installed?: boolean
  workflow_employees?: WorkflowEmployeeRow[]
}
export type EntitlementEmployeePreview = {
  id: string
  label: string
  modId: string
  modName: string
  summary: string
}

export const TIER_OPTIONS: { value: string; label: string }[] = [
  { value: 'personal', label: '个人' },
  { value: 'enterprise', label: '企业' },
  { value: 'admin', label: '管理员' },
]
export const ACCOUNT_TIER_OPTIONS: { value: string; label: string }[] = [
  { value: 'normal', label: '普通' },
  { value: 'pro', label: 'Pro' },
  { value: 'max', label: 'Max' },
  { value: 'ultra', label: 'Ultra' },
]
export const BUDGET_RANGE_OPTIONS = ['1–5 万', '5–10 万', '10–50 万', '50–100 万']
export const CREDIT_QUICK_AMOUNTS = [50, 100, 500, 1000]
