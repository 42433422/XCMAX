import { apiFetch, DEFAULT_MOD_API_TIMEOUT_MS } from '@/utils/apiBase'
import { workflowAiEmployeesStorageKey } from '@/stores/workflowAiEmployees'
import {
  resolveTenantStorageScopeFromRuntime,
  writeTenantScopedStorageItem,
} from '@/utils/tenantStorageScope'

const LS_PRODUCT_FLOW_COMPLETED = 'xcagi_product_flow_completed'
const LS_PRODUCT_FLOW_HOST_ACK = 'xcagi_product_flow_host_ack'

export interface WorkspacePrefs {
  selected_industry_id?: string
  industry_mod_id?: string
  workflow_ai_employees?: Record<string, boolean>
  product_flow_completed?: boolean
  host_pack_acknowledged?: boolean
}

export interface WorkspacePrefsResponse {
  success?: boolean
  data?: WorkspacePrefs
  owner_id?: string | null
}

let syncTimer: ReturnType<typeof setTimeout> | null = null
let pendingPatch: WorkspacePrefs = {}

export async function fetchWorkspacePrefs(): Promise<WorkspacePrefsResponse> {
  const r = await apiFetch('/api/workspace/prefs', {
    timeoutMs: DEFAULT_MOD_API_TIMEOUT_MS,
  })
  if (!r.ok) throw new Error(`workspace/prefs HTTP ${r.status}`)
  return (await r.json()) as WorkspacePrefsResponse
}

export async function patchWorkspacePrefs(partial: WorkspacePrefs): Promise<WorkspacePrefsResponse> {
  const r = await apiFetch('/api/workspace/prefs', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(partial),
    timeoutMs: DEFAULT_MOD_API_TIMEOUT_MS,
  })
  if (!r.ok) throw new Error(`workspace/prefs PATCH HTTP ${r.status}`)
  return (await r.json()) as WorkspacePrefsResponse
}

/** 登录/换租户后：服务器 → localStorage 缓存 */
export function applyWorkspacePrefsToLocalCache(prefs: WorkspacePrefs, scope?: string): void {
  if (typeof localStorage === 'undefined') return
  try {
    const tenantScope = scope || resolveTenantStorageScopeFromRuntime()
    if (typeof prefs.product_flow_completed === 'boolean') {
      writeTenantScopedStorageItem(
        LS_PRODUCT_FLOW_COMPLETED,
        prefs.product_flow_completed ? '1' : '0',
        tenantScope,
      )
      if (tenantScope === 'local') {
        localStorage.setItem(LS_PRODUCT_FLOW_COMPLETED, prefs.product_flow_completed ? '1' : '0')
      }
    }
    if (typeof prefs.host_pack_acknowledged === 'boolean') {
      writeTenantScopedStorageItem(
        LS_PRODUCT_FLOW_HOST_ACK,
        prefs.host_pack_acknowledged ? '1' : '0',
        tenantScope,
      )
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

export async function hydrateWorkspacePrefsFromServer(scope?: string): Promise<WorkspacePrefs | null> {
  try {
    const resp = await fetchWorkspacePrefs()
    const prefs = resp.data || {}
    if (resp.owner_id) {
      applyWorkspacePrefsToLocalCache(prefs, scope)
    }
    return prefs
  } catch {
    return null
  }
}

/** 防抖写回服务器（离线时静默失败） */
export function queueWorkspacePrefsSync(partial: WorkspacePrefs, delayMs = 400): void {
  pendingPatch = { ...pendingPatch, ...partial }
  if (syncTimer) clearTimeout(syncTimer)
  syncTimer = setTimeout(() => {
    const payload = { ...pendingPatch }
    pendingPatch = {}
    syncTimer = null
    void patchWorkspacePrefs(payload).catch(() => {
      /* 未登录或离线 */
    })
  }, delayMs)
}
