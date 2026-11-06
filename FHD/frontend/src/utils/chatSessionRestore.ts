/** Restore the signed-in conversation after the tenant scope becomes known. */

export function isDurableChatScope(scope: string): boolean {
  const value = String(scope || '').trim()
  if (!value || value === 'local' || value.endsWith('owner-pending')) return false
  return /^(tenant|user|session|platform):/.test(value)
}

export function sessionIdForScope(scope: string, stored: string, current: string): { id: string; persist: boolean } {
  const existing = String(current || '').trim()
  if (!isDurableChatScope(scope)) return { id: existing, persist: false }
  const saved = String(stored || '').trim()
  if (saved) return { id: saved, persist: false }
  return { id: existing, persist: Boolean(existing) }
}
