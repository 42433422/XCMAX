import { apiFetch, DEFAULT_MOD_API_TIMEOUT_MS } from '@/utils/apiBase'
import { workflowAiEmployeesStorageKey } from '@/stores/workflowAiEmployees'
import { resolveTenantStorageScopeFromRuntime, writeTenantScopedStorageItem } from '@/utils/tenantStorageScope'

const LS_PRODUCT_FLOW_COMPLETED = 'xcagi_product_flow_completed'
const LS_PRODUCT_FLOW_HOST_ACK = 'xcagi_product_flow_host_ack'

export interface WorkspacePrefs {
  selected_industry_id?: string
  industry_mod_id?: string
  workflow_ai_employees?: Record<string, boolean>
  product_flow_completed?: boolean
  host_pack_acknowledged?: boolean
  _revision?: number
}

export interface WorkspacePrefsResponse {
  success?: boolean
  data?: WorkspacePrefs
  owner_id?: string | null
  revision?: number
}

let syncTimer: ReturnType<typeof setTimeout> | null = null
let pendingPatch: WorkspacePrefs = {}
let pendingScope: string | null = null
let observedSnapshot: { scope: string; owner: string; revision: number } | null = null

export class WorkspacePrefsConflictError extends Error {
  constructor() {
    super('workspace_prefs_version_conflict')
    this.name = 'WorkspacePrefsConflictError'
  }
}

function readRevision(data: WorkspacePrefsResponse): number {
  if (typeof data.revision !== 'number' || !Number.isSafeInteger(data.revision) || data.revision < 0) {
    throw new Error('workspace_prefs_revision_missing')
  }
  return data.revision
}

function assertScopeUnchanged(scope: string): void {
  if (resolveTenantStorageScopeFromRuntime(true) !== scope) {
    throw new Error('workspace_prefs_account_changed')
  }
}

function notifyWorkspaceSyncFailed(error: unknown): void {
  if (typeof window === 'undefined') return
  window.dispatchEvent(new CustomEvent('xcagi:workspace-prefs-sync-failed', {
    detail: {
      code: error instanceof WorkspacePrefsConflictError
        ? 'workspace_prefs_version_conflict'
        : error instanceof Error ? error.message : 'workspace_prefs_sync_unknown',
    },
  }))
}

export async function fetchWorkspacePrefs(): Promise<WorkspacePrefsResponse> {
  const r = await apiFetch('/api/workspace/prefs', {
    timeoutMs: DEFAULT_MOD_API_TIMEOUT_MS,
  })
  if (!r.ok) throw new Error(`workspace/prefs HTTP ${r.status}`)
  return (await r.json()) as WorkspacePrefsResponse
}

export async function patchWorkspacePrefs(
  partial: WorkspacePrefs,
  scope = resolveTenantStorageScopeFromRuntime(true),
): Promise<WorkspacePrefsResponse> {
  assertScopeUnchanged(scope)
  // Always read an authoritative server token. No cached revision or a second
  // client-side version source may authorize a write after another device acts.
  const before = await fetchWorkspacePrefs()
  if (!before.owner_id) throw new Error('workspace_prefs_owner_missing')
  const serverRevision = readRevision(before)
  const observed = observedSnapshot?.scope === scope ? observedSnapshot : null
  if (observed && (observed.owner !== before.owner_id || observed.revision !== serverRevision)) {
    // Do not quietly fetch a newer revision to overwrite another device's edit.
    // The caller must explicitly reconcile and hydrate the new snapshot.
    throw new WorkspacePrefsConflictError()
  }
  const expected_revision = observed?.revision ?? serverRevision
  assertScopeUnchanged(scope)
  const fields = { ...partial }
  delete fields._revision
  const r = await apiFetch('/api/workspace/prefs', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...fields, expected_revision, expected_owner_id: before.owner_id }),
    timeoutMs: DEFAULT_MOD_API_TIMEOUT_MS,
  })
  if (r.status === 409) throw new WorkspacePrefsConflictError()
  if (!r.ok) throw new Error(`workspace/prefs PATCH HTTP ${r.status}`)
  const after = (await r.json()) as WorkspacePrefsResponse
  if (after.owner_id !== before.owner_id || readRevision(after) !== expected_revision + 1) {
    throw new Error('workspace_prefs_write_receipt_mismatch')
  }
  assertScopeUnchanged(scope)
  observedSnapshot = { scope, owner: before.owner_id, revision: expected_revision + 1 }
  return after
}

/** 登录/换租户后：服务器 → localStorage 缓存 */
export function applyWorkspacePrefsToLocalCache(prefs: WorkspacePrefs, scope?: string): void {
  if (typeof localStorage === 'undefined') return
  try {
    const tenantScope = scope || resolveTenantStorageScopeFromRuntime()
    if (typeof prefs.product_flow_completed === 'boolean') {
      writeTenantScopedStorageItem(LS_PRODUCT_FLOW_COMPLETED, prefs.product_flow_completed ? '1' : '0', tenantScope)
      if (tenantScope === 'local') {
        localStorage.setItem(LS_PRODUCT_FLOW_COMPLETED, prefs.product_flow_completed ? '1' : '0')
      }
    }
    if (typeof prefs.host_pack_acknowledged === 'boolean') {
      writeTenantScopedStorageItem(LS_PRODUCT_FLOW_HOST_ACK, prefs.host_pack_acknowledged ? '1' : '0', tenantScope)
      if (tenantScope === 'local') {
        localStorage.setItem(LS_PRODUCT_FLOW_HOST_ACK, prefs.host_pack_acknowledged ? '1' : '0')
      }
    }
    if (prefs.workflow_ai_employees && typeof prefs.workflow_ai_employees === 'object') {
      const key = workflowAiEmployeesStorageKey(scope)
      const raw = localStorage.getItem(key)
      let cur: Record<string, boolean> = {}
      if (raw) {
        try {
          const parsed = JSON.parse(raw) as Record<string, unknown>
          if (parsed && typeof parsed === 'object') {
            for (const [k, v] of Object.entries(parsed)) {
              if (typeof v === 'boolean') cur[k] = v
            }
          }
        } catch {
          cur = {}
        }
      }
      for (const [k, v] of Object.entries(prefs.workflow_ai_employees)) {
        if (typeof v === 'boolean') cur[k] = v
      }
      localStorage.setItem(key, JSON.stringify(cur))
    }
  } catch {
    /* quota / private mode */
  }
}

export async function hydrateWorkspacePrefsFromServer(scope?: string, isCurrent: () => boolean = () => true): Promise<WorkspacePrefs | null> {
  try {
    const startedScope = scope || resolveTenantStorageScopeFromRuntime(true)
    const resp = await fetchWorkspacePrefs()
    const prefs = resp.data || {}
    if (resp.owner_id && isCurrent() && resolveTenantStorageScopeFromRuntime(true) === startedScope) {
      if (typeof resp.revision === 'number' && Number.isSafeInteger(resp.revision) && resp.revision >= 0) {
        observedSnapshot = {
          scope: scope || resolveTenantStorageScopeFromRuntime(true),
          owner: resp.owner_id,
          revision: resp.revision,
        }
      } else {
        // Read-only legacy server response: display data, but cannot use it
        // as a write token until a versioned server becomes available.
        observedSnapshot = null
      }
      applyWorkspacePrefsToLocalCache(prefs, scope)
    }
    return prefs
  } catch {
    return null
  }
}

/** Queue only for the originating account scope; unknown outcomes never auto-replay. */
export function queueWorkspacePrefsSync(partial: WorkspacePrefs, delayMs = 400): void {
  const scope = resolveTenantStorageScopeFromRuntime(true)
  if (pendingScope !== null && pendingScope !== scope) {
    pendingPatch = {} // Never send a previous account's queued settings.
    notifyWorkspaceSyncFailed(new Error('workspace_prefs_account_changed'))
  }
  pendingScope = scope
  const employees = {
    ...(pendingPatch.workflow_ai_employees || {}),
    ...(partial.workflow_ai_employees || {}),
  }
  pendingPatch = { ...pendingPatch, ...partial }
  if (partial.workflow_ai_employees) pendingPatch.workflow_ai_employees = employees
  if (syncTimer) clearTimeout(syncTimer)
  syncTimer = setTimeout(() => {
    const payload = { ...pendingPatch }
    pendingPatch = {}
    pendingScope = null
    syncTimer = null
    if (resolveTenantStorageScopeFromRuntime(true) !== scope) {
      notifyWorkspaceSyncFailed(new Error('workspace_prefs_account_changed'))
      return
    }
    void patchWorkspacePrefs(payload, scope).catch(notifyWorkspaceSyncFailed)
  }, delayMs)
}


/** Clear pending work on explicit logout/account teardown; never replay unknown writes. */
export function resetWorkspacePrefsSyncState(): void {
  if (syncTimer) clearTimeout(syncTimer)
  syncTimer = null
  pendingPatch = {}
  pendingScope = null
  observedSnapshot = null
}
