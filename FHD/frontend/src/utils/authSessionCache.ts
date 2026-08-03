import { authApi } from '@/api/auth';

let cachedValid: boolean | null = null;
let cachedAt = 0;
let cacheEpoch = 0;
let desktopBootstrapSessionHint: boolean | null = null;
/** 企业版会话校验缓存：减少侧栏频繁切换时重复打 /api/auth/session/validate */
const SESSION_TTL_MS = 5 * 60_000;
/**
 * This marker contains no credential and never authorizes an API request.  It
 * only lets the Electron shell render the already-known workspace while the
 * official session validation runs in the background after a cold restart.
 */
export const LS_ENTERPRISE_SESSION_HINT = 'xcagi_enterprise_session_hint_v1';
const SESSION_HINT_TTL_MS = 24 * 60 * 60_000;

function writeEnterpriseSessionHint(now = Date.now()): void {
  if (typeof localStorage === 'undefined') return;
  try {
    localStorage.setItem(LS_ENTERPRISE_SESSION_HINT, String(now));
  } catch {
    /* private mode / quota: background validation still works */
  }
}

function clearEnterpriseSessionHint(): void {
  if (typeof localStorage === 'undefined') return;
  try {
    localStorage.removeItem(LS_ENTERPRISE_SESSION_HINT);
  } catch {
    /* ignore */
  }
}

/** A recent successful official login may show the desktop shell provisionally. */
export function hasRecentEnterpriseSessionHint(now = Date.now()): boolean {
  if (typeof localStorage === 'undefined') return false;
  try {
    const at = Number(localStorage.getItem(LS_ENTERPRISE_SESSION_HINT) || 0);
    if (!Number.isFinite(at) || at <= 0 || now < at || now - at > SESSION_HINT_TTL_MS) {
      if (at) clearEnterpriseSessionHint();
      return false;
    }
    return true;
  } catch {
    return false;
  }
}

/**
 * Electron can see Chromium's persisted HttpOnly session before the renderer
 * starts, while renderer localStorage may still be unavailable immediately
 * after an app replacement. This one-shot value only permits shell rendering;
 * the normal background official validation remains authoritative.
 */
export async function consumeDesktopSessionBootstrapHint(): Promise<boolean> {
  if (typeof window === 'undefined') return false;
  if (desktopBootstrapSessionHint !== null) return desktopBootstrapSessionHint;
  const consume = window.xcagiDesktop?.consumeBootstrapSessionHint;
  if (typeof consume !== 'function') return false;
  try {
    desktopBootstrapSessionHint = Boolean(await consume());
    return desktopBootstrapSessionHint;
  } catch {
    desktopBootstrapSessionHint = false;
    return false;
  }
}

function clearDesktopSessionBootstrapHint(): void {
  desktopBootstrapSessionHint = false;
}

function resetDesktopSessionBootstrapHint(): void {
  desktopBootstrapSessionHint = null;
}

function readValid(res: unknown): boolean {
  const r = res as { success?: boolean; valid?: boolean; data?: { valid?: boolean } };
  return r?.success === true || r?.valid === true || r?.data?.valid === true;
}

export async function validateEnterpriseSessionCached(force = false): Promise<boolean> {
  const now = Date.now();
  if (!force && cachedValid !== null && now - cachedAt < SESSION_TTL_MS) {
    return cachedValid;
  }
  const requestEpoch = cacheEpoch;
  const res = await authApi.validateSession();
  const valid = readValid(res);
  if (requestEpoch !== cacheEpoch) {
    return cachedValid === true;
  }
  cachedValid = valid;
  cachedAt = Date.now();
  if (valid) writeEnterpriseSessionHint(cachedAt);
  else {
    clearEnterpriseSessionHint();
    clearDesktopSessionBootstrapHint();
  }
  return valid;
}

export function invalidateEnterpriseSessionCache(): void {
  cacheEpoch += 1;
  cachedValid = null;
  cachedAt = 0;
  clearEnterpriseSessionHint();
  resetDesktopSessionBootstrapHint();
}

/** Login just established the cookie; avoid an immediate blocking validate round-trip. */
export function markEnterpriseSessionValid(): void {
  cacheEpoch += 1;
  cachedValid = true;
  cachedAt = Date.now();
  writeEnterpriseSessionHint(cachedAt);
}
