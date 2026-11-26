/**
 * Local UI hints, never a server authorization receipt. A tool's persistent
 * grant cannot be restored from unowned browser storage. Until the backend
 * supplies a versioned authorization projection, both scopes are retained
 * only in the authenticated browser session that explicitly recorded them.
 */
import { captureAuthSession } from '@/utils/authSessionCache'
import { getRuntimeTenantStorageScopeInput } from '@/utils/tenantStorageScopeRuntime'

export type ToolPermissionScope = 'session' | 'persistent'

type Grant = { scope: ToolPermissionScope; grantedAt: number }
let owner: { principal: string; current: () => boolean } | null = null
const grants = new Map<string, Grant>()

function activePrincipal(): string | null {
  const identity = getRuntimeTenantStorageScopeInput()
  if (!identity || (identity.localUserId == null && identity.marketUserId == null)) return null
  return JSON.stringify([identity.tenantId ?? null, identity.localUserId ?? null,
    identity.marketUserId ?? null, identity.accountKind ?? '', identity.marketUsername ?? ''])
}

function ensureCurrentOwner(): boolean {
  const principal = activePrincipal()
  if (!principal || !owner || owner.principal !== principal || !owner.current()) {
    grants.clear()
    owner = principal ? { principal, current: captureAuthSession() } : null
  }
  return owner !== null
}

export function getToolPermission(toolId: string): ToolPermissionScope | null {
  if (!ensureCurrentOwner()) return null
  return grants.get(String(toolId || '').trim())?.scope ?? null
}

export function setToolPermission(toolId: string, scope: ToolPermissionScope): void {
  const id = String(toolId || '').trim()
  if (!id || !ensureCurrentOwner() || (scope !== 'session' && scope !== 'persistent')) return
  grants.set(id, { scope, grantedAt: Date.now() })
}

export function clearToolPermission(toolId: string): void {
  if (ensureCurrentOwner()) grants.delete(String(toolId || '').trim())
}

/** Explicit invalidation for a revoked server permission projection or logout. */
export function clearSessionPermissions(): void {
  grants.clear()
  owner = null
  // Retire the legacy global, unowned grants without adopting any of them.
  try { sessionStorage.removeItem('xcagi_tool_permissions_session') } catch { /* storage unavailable */ }
  try { localStorage.removeItem('xcagi_tool_permissions_persistent') } catch { /* storage unavailable */ }
}

export function listAuthorizedTools(): { tool_id: string; scope: ToolPermissionScope }[] {
  if (!ensureCurrentOwner()) return []
  return [...grants.entries()].map(([tool_id, grant]) => ({ tool_id, scope: grant.scope }))
}
