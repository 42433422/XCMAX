/** 太阳鸟已归并到统一考勤行业包；旧 id 只在 entitlement 兼容层做别名解析。 */
export const SUNBIRD_CLIENT_MOD_ID = 'attendance-industry'

const SUNBIRD_USERNAMES = new Set(['sunbird', 'SUNBIRD'])

export function isSunbirdAccountUsername(username: string | null | undefined): boolean {
  const u = String(username || '').trim()
  if (!u) return false
  return SUNBIRD_USERNAMES.has(u) || u.toUpperCase() === 'SUNBIRD'
}

/** 登录/会话权益列表合并账号级默认 Mod */
export function augmentEntitledModIdsForAccount(username: string | null | undefined, entitledModIds: string[] | undefined): string[] {
  void username
  const seen = new Set<string>()
  const out: string[] = []
  for (const id of entitledModIds || []) {
    const s = String(id || '').trim()
    if (!s || seen.has(s)) continue
    seen.add(s)
    out.push(s)
  }
  return out
}

export function preferredClientModIdForAccount(username: string | null | undefined): string {
  void username
  return ''
}

/** 客户主 ERP 不再按用户名自动绑定，统一由服务端 entitlement 显式授权。 */
export function shouldBindClientPrimaryErpMod(username: string | null | undefined, options?: { isAdminAccount?: boolean }): boolean {
  void username
  void options
  return false
}
