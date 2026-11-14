import { authApi } from '@/api/auth'
import { ref } from 'vue'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'

let cachedValid: boolean | null = null
let cachedAt = 0
const cacheEpoch = ref(0)
let cachedAccountEpoch = productReadAccountEpoch.value
let validationInFlight: Promise<boolean> | null = null
let desktopBootstrapSessionHint: boolean | null = null

/** Retire work across logout/relogin as well as A -> B -> A workspace changes. */
export function captureAuthSession(): () => boolean {
  const session = cacheEpoch.value
  const account = productReadAccountEpoch.value
  return () => session === cacheEpoch.value && account === productReadAccountEpoch.value
}

export function getAuthSessionEpoch(): number {
  return cacheEpoch.value
}
/** 企业版会话校验缓存：减少侧栏频繁切换时重复打 /api/auth/session/validate */
const SESSION_TTL_MS = 5 * 60_000
/** 空闲超过短 TTL 后，导航仍沿用最近一次成功结果，并在后台复核。 */
const SESSION_NAV_STALE_MS = 30 * 60_000
/**
 * This marker contains no credential and never authorizes an API request.  It
 * only lets the Electron shell render the already-known workspace while the
 * official session validation runs in the background after a cold restart.
 */
export const LS_ENTERPRISE_SESSION_HINT = 'xcagi_enterprise_session_hint_v1'
const SESSION_HINT_TTL_MS = 24 * 60 * 60_000

function writeEnterpriseSessionHint(now = Date.now()): void {
  if (typeof localStorage === 'undefined') return
  try {
    localStorage.setItem(LS_ENTERPRISE_SESSION_HINT, String(now))
  } catch {
    /* private mode / quota: background validation still works */
  }
}

function clearEnterpriseSessionHint(): void {
  if (typeof localStorage === 'undefined') return
  try {
    localStorage.removeItem(LS_ENTERPRISE_SESSION_HINT)
  } catch {
    /* ignore */
  }
}

/** A recent successful official login may show the desktop shell provisionally. */
export function hasRecentEnterpriseSessionHint(now = Date.now()): boolean {
  if (typeof localStorage === 'undefined') return false
  try {
    const at = Number(localStorage.getItem(LS_ENTERPRISE_SESSION_HINT) || 0)
    if (!Number.isFinite(at) || at <= 0 || now < at || now - at > SESSION_HINT_TTL_MS) {
      if (at) clearEnterpriseSessionHint()
      return false
    }
    return true
  } catch {
    return false
  }
}

/**
 * 是否有一个可用的登录会话可用于发起「需要身份」的后台请求。
 * 只读本地标记，不发网络请求；未登录时调用方应静默跳过。
 */
export function hasKnownEnterpriseSession(now = Date.now()): boolean {
  if (cachedValid === true && now - cachedAt <= SESSION_NAV_STALE_MS) return true
  return hasRecentEnterpriseSessionHint(now)
}

/**
 * Electron can see Chromium's persisted HttpOnly session before the renderer
 * starts, while renderer localStorage may still be unavailable immediately
 * after an app replacement. This one-shot value only permits shell rendering;
 * the normal background official validation remains authoritative.
 */
export async function consumeDesktopSessionBootstrapHint(): Promise<boolean> {
  if (typeof window === 'undefined') return false
  if (desktopBootstrapSessionHint !== null) return desktopBootstrapSessionHint
  const consume = window.xcagiDesktop?.consumeBootstrapSessionHint
  if (typeof consume !== 'function') return false
  const isCurrent = captureAuthSession()
  try {
    const hint = Boolean(await consume())
    if (!isCurrent()) return false
    desktopBootstrapSessionHint = hint
    return desktopBootstrapSessionHint
  } catch {
    if (isCurrent()) desktopBootstrapSessionHint = false
    return false
  }
}

/** Decide whether a validated desktop session can enter the shell provisionally. */
export async function canResumeRecentDesktopSession(
  isDesktop: boolean,
  isEnterprise: boolean,
  query: Record<string, unknown>,
): Promise<boolean> {
  if (!isDesktop || !isEnterprise || query.oidc || query.oidc_error) return false
  if (query.reauthenticate === '1') return false
  // A stale ?error= on the login URL is not a new credential failure.
  return hasRecentEnterpriseSessionHint() || (await consumeDesktopSessionBootstrapHint())
}

export type EnterpriseSessionProbe = 'valid' | 'invalid' | 'unknown'

/** Force a server check. Network loss stays unknown and does not look like logout. */
export async function probeEnterpriseSession(): Promise<EnterpriseSessionProbe> {
  const isCurrent = captureAuthSession()
  try {
    const valid = await validateEnterpriseSessionCached(true)
    if (!isCurrent()) return 'unknown'
    if (valid) return 'valid'
  } catch {
    return 'unknown'
  }
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('xcagi:enterprise-session-invalid'))
  }
  return 'invalid'
}

function clearDesktopSessionBootstrapHint(): void {
  desktopBootstrapSessionHint = false
}

function resetDesktopSessionBootstrapHint(): void {
  desktopBootstrapSessionHint = null
}

export function readValid(res: unknown): boolean {
  const r = res as { success?: boolean; valid?: boolean; data?: { valid?: boolean } }
  if (typeof r?.valid === 'boolean') return r.valid
  if (typeof r?.data?.valid === 'boolean') return r.data.valid
  if (r?.success === true) return true
  throw new Error('会话校验暂不可用，请稍后重试')
}

/** Login just returned a session cookie. The next navigation may trust it until the TTL. */
export function rememberEnterpriseSessionValid(): void {
  cachedAccountEpoch = productReadAccountEpoch.value
  cachedValid = true
  cachedAt = Date.now()
  writeEnterpriseSessionHint(cachedAt)
}

export async function validateEnterpriseSessionCached(force = false): Promise<boolean> {
  if (cachedAccountEpoch !== productReadAccountEpoch.value) {
    cachedAccountEpoch = productReadAccountEpoch.value
    cachedValid = null
    cachedAt = 0
    validationInFlight = null
  }
  const now = Date.now()
  if (!force && cachedValid === true && now - cachedAt < SESSION_TTL_MS) return true
  if (!force && cachedValid !== null && cachedValid !== true && now - cachedAt < SESSION_TTL_MS) return cachedValid
  if (!force && cachedValid === true && now - cachedAt < SESSION_NAV_STALE_MS) {
    if (!validationInFlight) {
      const isCurrent = captureAuthSession()
      void validateEnterpriseSessionCached(true).then((valid) => {
        if (!isCurrent() || valid || typeof window === 'undefined') return
        window.dispatchEvent(new CustomEvent('xcagi:enterprise-session-invalid'))
      }).catch(() => undefined)
    }
    return true
  }
  if (validationInFlight) return validationInFlight
  const isCurrent = captureAuthSession()
  const pending = (async () => {
    let valid: boolean
    // 桌面每 5 秒探一次。入库预演会占住后端约 12s，8s 会先报失败，后端随后仍返回成功。
    try { valid = readValid(await authApi.validateSession({ timeoutMs: 30_000 })) }
    catch (error) {
      const status = (error as { status?: number })?.status
      if (status !== 401 && status !== 403) throw error
      valid = false
    }
    if (!isCurrent()) {
      return cachedAccountEpoch === productReadAccountEpoch.value && cachedValid === true
    }
    cachedValid = valid
    cachedAt = Date.now()
    if (valid) writeEnterpriseSessionHint(cachedAt)
    else {
      clearEnterpriseSessionHint()
      clearDesktopSessionBootstrapHint()
    }
    return valid
  })()
  validationInFlight = pending
  try { return await pending }
  finally { if (validationInFlight === pending) validationInFlight = null }
}

export function invalidateEnterpriseSessionCache(): void {
  cacheEpoch.value += 1
  cachedAccountEpoch = productReadAccountEpoch.value
  validationInFlight = null
  cachedValid = null
  cachedAt = 0
  clearEnterpriseSessionHint()
  resetDesktopSessionBootstrapHint()
}

/** Login just established the cookie; avoid an immediate blocking validate round-trip. */
export function markEnterpriseSessionValid(): void {
  cacheEpoch.value += 1
  cachedAccountEpoch = productReadAccountEpoch.value
  validationInFlight = null
  cachedValid = true
  cachedAt = Date.now()
  writeEnterpriseSessionHint(cachedAt)
}
