import {
  defaultOnboardingIndustryId,
} from '@/constants/productFlow'
import { authApi } from '@/api/auth'
import { fetchIndustryBaseline, fetchOnboardingIndustryCatalog } from '@/utils/platformShellApi'
import { fetchProductSku, isEnterpriseEdition } from '@/utils/productSku'

export type HostPackOnboardingStep = 'industry' | 'host-pack'

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

let hostPackNeedsCache: { needs: boolean; at: number } | null = null
const HOST_PACK_CACHE_TTL_MS = 60_000

export function shouldRouteToHostPackOnboarding(
  toName: string | symbol | null | undefined,
): boolean {
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
  hostPackNeedsCache = null
}

function readSessionAdminFlag(payload: unknown): boolean {
  const root = (payload && typeof payload === 'object' ? payload : {}) as Record<string, unknown>
  const data =
    root.data && typeof root.data === 'object' && !Array.isArray(root.data)
      ? (root.data as Record<string, unknown>)
      : root
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
 * 企业版未完成引导时应进入的步骤：未选行业 → industry；否则 host-pack。
 * 返回 null 表示无需拦截。
 */
export async function resolveHostPackOnboardingStep(force = false): Promise<HostPackOnboardingStep | null> {
  const needs = await needsHostPackCompletion(force)
  if (!needs) return null

  try {
    const catalog = await fetchOnboardingIndustryCatalog(force)
    const industryId = String(catalog?.selected_industry_id || '').trim()
    if (!industryId) return 'industry'
  } catch {
    return 'host-pack'
  }
  return 'host-pack'
}

/**
 * 企业版：所选行业必需基础 Mod 未齐（baseline_ready !== true）时需进「补基础线」。
 * 登录后首次进入受保护路由时 force 刷新；同会话内跳过则不再弹，直至下次登录。
 */
export async function needsHostPackCompletion(force = false): Promise<boolean> {
  if (isHostPackSkippedThisSession()) return false

  const now = Date.now()
  if (!force && hostPackNeedsCache && now - hostPackNeedsCache.at < HOST_PACK_CACHE_TTL_MS) {
    return hostPackNeedsCache.needs
  }

  let sku = 'generic'
  try {
    sku = await fetchProductSku()
  } catch {
    return false
  }
  if (!isEnterpriseEdition(sku)) {
    hostPackNeedsCache = { needs: false, at: now }
    return false
  }

  if (await isAdminAccountSessionForGate()) {
    hostPackNeedsCache = { needs: false, at: now }
    return false
  }

  try {
    const catalog = await fetchOnboardingIndustryCatalog(force)
    const industryId =
      String(catalog?.selected_industry_id || '').trim() || defaultOnboardingIndustryId()
    const plan = await fetchIndustryBaseline(industryId, force)
    const needs = plan?.baseline_ready !== true
    hostPackNeedsCache = { needs, at: now }
    return needs
  } catch {
    return false
  }
}
