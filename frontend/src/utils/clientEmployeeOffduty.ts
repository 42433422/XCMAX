/** 客户端「下岗」：不调用 MODstore，仅 XCmax 浏览器本地持久化。 */
export const CLIENT_EMPLOYEE_OFFDUTY_KEY = 'xcmax_client_employee_offduty'

function parseIds(raw: string | null): Set<string> {
  if (!raw) return new Set()
  try {
    const arr = JSON.parse(raw) as unknown
    if (!Array.isArray(arr)) return new Set()
    return new Set(arr.map((x) => String(x ?? '').trim()).filter(Boolean))
  } catch {
    return new Set()
  }
}

export function loadClientOffdutyIds(): Set<string> {
  if (typeof window === 'undefined') return new Set()
  return parseIds(window.localStorage.getItem(CLIENT_EMPLOYEE_OFFDUTY_KEY))
}

export function saveClientOffdutyIds(ids: Set<string>): void {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(CLIENT_EMPLOYEE_OFFDUTY_KEY, JSON.stringify([...ids]))
  } catch {
    /* ignore */
  }
}

export function isClientOffduty(pkgId: string): boolean {
  const id = String(pkgId || '').trim()
  if (!id) return false
  return loadClientOffdutyIds().has(id)
}

export function setClientOffduty(pkgId: string, off: boolean): void {
  const id = String(pkgId || '').trim()
  if (!id) return
  const next = loadClientOffdutyIds()
  if (off) next.add(id)
  else next.delete(id)
  saveClientOffdutyIds(next)
}
