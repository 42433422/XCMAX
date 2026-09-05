import { defaultOnboardingIndustryId, LS_PRODUCT_FLOW_COMPLETED } from '@/constants/productFlow'
import { authApi } from '@/api/auth'
import { fetchIndustryBaseline, fetchOnboardingIndustryCatalog } from '@/utils/platformShellApi'
import { fetchProductSku, isEnterpriseEdition } from '@/utils/productSku'
import { fetchWorkspacePrefs } from '@/utils/workspacePrefsApi'
import { readTenantScopedStorageItem } from '@/utils/tenantStorageScope'

export type HostPackOnboardingStep = 'welcome' | 'industry' | 'host-pack'

/** 本 tab 会话内用户点了「先进入对话，稍后再补」则不再反复拦截（下次登录再提示） */
export const SS_HOST_PACK_SKIPPED_SESSION = 'xcagi_host_pack_skip_session'

export const HOST_PACK_ONBOARDING_EXEMPT_ROUTE_NAMES = new Set([
  'product-onboarding',
  'login',
  'login-help',
  'login-register',
  'login-forgot-account',
  'login-forgot-password',
  'lan-gate',
  'mod-store',
  'employee-workflow',
  'workflow-employee-space',
  'workflow-employee-stitch-full',
])

type HostPackNeedsCache = { needs: boolean; at: number; step: HostPackOnboardingStep | null }
let hostPackNeedsCache: HostPackNeedsCache | null = null
let hostPackCacheEpoch = 0
const HOST_PACK_CACHE_TTL_MS = 60_000
const SS_HOST_PACK_NEEDS_CACHE = 'xcagi_host_pack_needs_cache_v2'

function readPersistedHostPackNeedsCache(): HostPackNeedsCache | null {
  if (typeof sessionStorage === 'undefined') return null
  try {
    const parsed = JSON.parse(sessionStorage.getItem(SS_HOST_PACK_NEEDS_CACHE) || 'null') as {
      needs?: unknown
      at?: unknown
      step?: unknown
    } | null
    if (!parsed || typeof parsed.needs !== 'boolean' || !Number.isFinite(Number(parsed.at))) {
      return null
    }
    const step: HostPackOnboardingStep | null = parsed.step === 'welcome' || parsed.step === 'industry' || parsed.step === 'host-pack' ? parsed.step : null
    if (parsed.needs !== (step !== null)) return null
    const cached = { needs: parsed.needs, at: Number(parsed.at), step }
    if (Date.now() - cached.at >= HOST_PACK_CACHE_TTL_MS) return null
    return cached
  } catch {
    return null
  }
}

function writeHostPackNeedsCache(needs: boolean, at: number, step: HostPackOnboardingStep | null = null): void {
  hostPackNeedsCache = { needs, at, step }
  if (typeof sessionStorage === 'undefined') return
  try {
    sessionStorage.setItem(SS_HOST_PACK_NEEDS_CACHE, JSON.stringify(hostPackNeedsCache))
  } catch {
    /* ignore */
  }
}

export function shouldRouteToHostPackOnboarding(toName: string | symbol | null | undefined): boolean {
  const name = String(toName || '').trim()
  if (!name) return false
  return !HOST_PACK_ONBOARDING_EXEMPT_ROUTE_NAMES.has(name)
}

export function markHostPackSkippedThisSession(): void {
  if (typeof sessionStorage === 'undefined') return
  try {
    sessionStorage.setItem(SS_HOST_PACK_SKIPPED_SESSION, '1')
  } catch {
    /* ignore */
  }
  invalidateHostPackCompletionCache()
}

export function clearHostPackSkippedSession(): void {
  if (typeof sessionStorage === 'undefined') return
  try {
    sessionStorage.removeItem(SS_HOST_PACK_SKIPPED_SESSION)
  } catch {
    /* ignore */
  }
  invalidateHostPackCompletionCache()
}

export function isHostPackSkippedThisSession(): boolean {
  if (typeof sessionStorage === 'undefined') return false
  try {
    return sessionStorage.getItem(SS_HOST_PACK_SKIPPED_SESSION) === '1'
  } catch {
    return false
  }
}

export function invalidateHostPackCompletionCache(): void {
  hostPackCacheEpoch += 1
  hostPackNeedsCache = null
  if (typeof sessionStorage === 'undefined') return
  try {
    sessionStorage.removeItem(SS_HOST_PACK_NEEDS_CACHE)
  } catch {
    /* ignore */
  }
}

function readSessionAdminFlag(payload: unknown): boolean {
  const root = (payload && typeof payload === 'object' ? payload : {}) as Record<string, unknown>
  const data = root.data && typeof root.data === 'object' && !Array.isArray(root.data) ? (root.data as Record<string, unknown>) : root
  const kind = String(data.account_kind || '').trim()
  return kind === 'admin' && Boolean(data.market_is_admin)
}

/** 与后端 is_admin_account_session 对齐：管理员跳过补基础线登录拦截。 */
export async function isAdminAccountSessionForGate(): Promise<boolean> {
  try {
    const res = await authApi.validateSession()
    return readSessionAdminFlag(res)
  } catch {
    return false
  }
}

/**
 * 企业版未完成引导时应进入的步骤：未选行业 → welcome；否则 host-pack。
 * 返回 null 表示无需拦截。
 */
export async function resolveHostPackOnboardingStep(force = false): Promise<HostPackOnboardingStep | null> {
  const needs = await needsHostPackCompletion(force)
  return needs ? hostPackNeedsCache?.step ?? 'host-pack' : null
}

/**
 * 企业版：新工作区未选行业时先选择；必需基础 Mod 未齐时进「补基础线」。
 * 登录后首次进入受保护路由时 force 刷新；同会话内跳过则不再弹，直至下次登录。
 */
export async function needsHostPackCompletion(force = false): Promise<boolean> {
  if (isHostPackSkippedThisSession()) return false

  const now = Date.now()
  if (!force) {
    const cached =
      hostPackNeedsCache && now - hostPackNeedsCache.at < HOST_PACK_CACHE_TTL_MS ? hostPackNeedsCache : readPersistedHostPackNeedsCache()
    if (cached) {
      hostPackNeedsCache = cached
      return cached.needs
    }
  }

  const requestEpoch = hostPackCacheEpoch
  function saveResult(needs: boolean, step: HostPackOnboardingStep | null = null): boolean {
    // A login, tenant change or explicit skip can invalidate an in-flight read.
    if (requestEpoch !== hostPackCacheEpoch) return false
    writeHostPackNeedsCache(needs, now, step)
    return needs
  }

  let sku = 'generic'
  try {
    sku = await fetchProductSku()
  } catch {
    return false
  }
  if (!isEnterpriseEdition(sku)) {
    return saveResult(false)
  }

  if (await isAdminAccountSessionForGate()) {
    return saveResult(false)
  }

  try {
    const catalog = await fetchOnboardingIndustryCatalog(force)
    let industryId = String(catalog?.selected_industry_id || '').trim()
    if (!industryId) {
      const selectable = (catalog?.open_packages || []).some((item) => item.selectable !== false && String(item.industry_id || '').trim())
      if (!selectable) return saveResult(false)
      const ownerId = String(catalog?.owner_id || '').trim()
      if (!ownerId) return false
      // Profile.loaded can become true before preference hydration finishes.
      // Read the same server workspace before classifying it as first use.
      const response = await fetchWorkspacePrefs()
      if (response.success !== true || response.owner_id !== ownerId) return false
      const prefs = response.data || {}
      industryId = String(prefs.selected_industry_id || '').trim()
      const completed = prefs.product_flow_completed === true || (
        prefs.product_flow_completed !== false && readTenantScopedStorageItem(LS_PRODUCT_FLOW_COMPLETED, ownerId) === '1'
      )
      if (!industryId && !completed) return saveResult(true, 'welcome')
    }
    const plan = await fetchIndustryBaseline(industryId || defaultOnboardingIndustryId(), force)
    const needs = plan?.baseline_ready !== true
    return saveResult(needs, needs ? 'host-pack' : null)
  } catch {
    return false
  }
}
