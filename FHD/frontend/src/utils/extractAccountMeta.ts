/** 合并 login / session/validate / auth/me 顶层与 data 内的账号字段 */
const ACCOUNT_META_KEYS = [
  'account_kind',
  'company_brand',
  'market_is_admin',
  'market_is_enterprise',
  'impersonating_market_user_id',
  'impersonating_username',
] as const

export function extractAccountMeta(raw: Record<string, unknown> | null | undefined): Record<string, unknown> {
  if (!raw || typeof raw !== 'object') return {}
  const nested =
    raw.data && typeof raw.data === 'object' && !Array.isArray(raw.data)
      ? ({ ...(raw.data as Record<string, unknown>) } as Record<string, unknown>)
      : ({} as Record<string, unknown>)
  const out: Record<string, unknown> = { ...nested }
  for (const key of ACCOUNT_META_KEYS) {
    if (raw[key] !== undefined && raw[key] !== null && raw[key] !== '') {
      out[key] = raw[key]
    }
  }
  return out
}
