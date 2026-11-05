import type { RouteLocationRaw, Router } from 'vue-router'
import { isNavigationFailure, NavigationFailureType } from 'vue-router'

/** Shared user-navigation intent across sidebar / top settings / ecosystem launchers. */
export type AppNavIntent = {
  id: number
  targetKey: string
  source: string
  startedAt: number
}

export type AppNavStatus =
  | 'arrived'
  | 'duplicate'
  | 'superseded'
  | 'cancelled'
  | 'aborted'
  | 'timeout'
  | 'error'
  | 'unresolved'

export type AppNavOutcome = {
  status: AppNavStatus
  intentId: number
  targetKey: string
  /** Human-readable reason for UI / retry copy. */
  message: string
  error?: unknown
}

const DEFAULT_NAV_TIMEOUT_MS = 12_000

let intentSeq = 0
let activeIntent: AppNavIntent | null = null

export function resetAppNavigationForTests(): void {
  intentSeq = 0
  activeIntent = null
}

export function getActiveAppNavIntent(): AppNavIntent | null {
  return activeIntent
}

export function getAppNavIntentId(): number {
  return activeIntent?.id ?? 0
}

export function isAppNavIntentCurrent(intentId: number): boolean {
  return activeIntent != null && activeIntent.id === intentId
}

/**
 * Begin a new user navigation intent. Newer intents supersede older ones so
 * in-flight Mod registration / push waits can bail without clearing the new pending UI.
 */
export function beginAppNavIntent(targetKey: string, source = 'unknown'): AppNavIntent {
  const normalized = String(targetKey || '').trim()
  intentSeq += 1
  activeIntent = {
    id: intentSeq,
    targetKey: normalized,
    source,
    startedAt: Date.now(),
  }
  return activeIntent
}

export function clearAppNavIntentIfCurrent(intentId: number): void {
  if (activeIntent?.id === intentId) activeIntent = null
}

export function classifyNavigationFailure(error: unknown): AppNavStatus | null {
  if (!isNavigationFailure(error)) return null
  // Prefer the typed overload: comparing enum members against ErrorTypes trips TS2367.
  if (isNavigationFailure(error, NavigationFailureType.duplicated)) return 'duplicate'
  if (isNavigationFailure(error, NavigationFailureType.cancelled)) return 'cancelled'
  if (isNavigationFailure(error, NavigationFailureType.aborted)) return 'aborted'
  return 'unresolved'
}

export function routeMatchesTarget(
  router: Router,
  target: { name?: string | null; path?: string | null; key?: string | null },
): boolean {
  const current = router.currentRoute.value
  const name = current.name != null ? String(current.name) : ''
  const path = String(current.path || '')
  const wantName = target.name != null ? String(target.name).replace(/^mod-/, '') : ''
  const wantKey = target.key != null ? String(target.key).replace(/^mod-/, '') : ''
  const wantPath = target.path != null ? String(target.path).split('?')[0]?.split('#')[0] || '' : ''

  if (wantName && (name === wantName || name === `mod-${wantName}` || name.replace(/^mod-/, '') === wantName)) {
    return true
  }
  if (wantKey && (name === wantKey || name === `mod-${wantKey}` || name.replace(/^mod-/, '') === wantKey || path.includes(wantKey))) {
    return true
  }
  if (wantPath && (path === wantPath || path.endsWith(wantPath))) {
    return true
  }
  return false
}

function outcome(
  status: AppNavStatus,
  intent: AppNavIntent,
  message: string,
  error?: unknown,
): AppNavOutcome {
  return { status, intentId: intent.id, targetKey: intent.targetKey, message, error }
}

/**
 * Push a router location under an intent. Distinguishes NavigationFailure kinds,
 * verifies the final route when possible, and times out only this wait.
 */
export async function pushWithAppNavIntent(
  router: Router,
  location: RouteLocationRaw,
  intent: AppNavIntent,
  options: {
    timeoutMs?: number
    match?: { name?: string | null; path?: string | null; key?: string | null }
    isStale?: () => boolean
  } = {},
): Promise<AppNavOutcome> {
  const timeoutMs = options.timeoutMs ?? DEFAULT_NAV_TIMEOUT_MS
  const isStale = options.isStale ?? (() => !isAppNavIntentCurrent(intent.id))
  const match = options.match ?? {
    name: typeof location === 'object' && location && 'name' in location ? String((location as { name?: unknown }).name ?? '') : null,
    path: typeof location === 'string' ? location : typeof location === 'object' && location && 'path' in location ? String((location as { path?: unknown }).path ?? '') : null,
    key: intent.targetKey,
  }

  if (isStale()) {
    return outcome('superseded', intent, '已有更新的导航意图')
  }

  // Already on the target: treat as successful duplicate, not an error.
  if (routeMatchesTarget(router, match)) {
    return outcome('duplicate', intent, '已在目标页面')
  }

  let timer: ReturnType<typeof setTimeout> | undefined
  let staleTimer: ReturnType<typeof setInterval> | undefined
  // Vue Router 4 resolves NavigationFailure instead of rejecting in most cases.
  const pushPromise = Promise.resolve(router.push(location)).then(
    (value) => {
      if (isNavigationFailure(value)) return { kind: 'err' as const, error: value }
      return { kind: 'ok' as const }
    },
    (error: unknown) => ({ kind: 'err' as const, error }),
  )

  const raced = await new Promise<{ kind: 'ok' } | { kind: 'err'; error: unknown } | { kind: 'timeout' } | { kind: 'stale' }>((resolve) => {
    let settled = false
    const finish = (value: { kind: 'ok' } | { kind: 'err'; error: unknown } | { kind: 'timeout' } | { kind: 'stale' }) => {
      if (settled) return
      settled = true
      if (timer) clearTimeout(timer)
      if (staleTimer) clearInterval(staleTimer)
      resolve(value)
    }
    timer = setTimeout(() => finish({ kind: 'timeout' }), timeoutMs)
    staleTimer = setInterval(() => {
      if (isStale()) finish({ kind: 'stale' })
    }, 16)
    void pushPromise.then((result) => finish(result))
  })

  if (raced.kind === 'stale' || isStale()) {
    return outcome('superseded', intent, '已有更新的导航意图')
  }
  if (raced.kind === 'timeout') {
    return outcome('timeout', intent, '打开页面超时，可重试')
  }
  if (raced.kind === 'err') {
    const classified = classifyNavigationFailure(raced.error)
    if (classified === 'duplicate') {
      // Vue Router rejects duplicated navigations; if we are on target, OK.
      if (routeMatchesTarget(router, match)) {
        return outcome('duplicate', intent, '已在目标页面')
      }
      return outcome('duplicate', intent, '重复导航已忽略')
    }
    if (classified === 'cancelled') {
      // Internal redirect / newer navigation cancelled this push.
      if (!isStale() && routeMatchesTarget(router, match)) {
        return outcome('arrived', intent, '已到达目标页面')
      }
      if (isStale()) return outcome('superseded', intent, '已有更新的导航意图')
      return outcome('cancelled', intent, '导航已取消，可重试')
    }
    if (classified === 'aborted') {
      // Guard redirected: if final route still matches intent, keep as arrived.
      if (routeMatchesTarget(router, match)) {
        return outcome('arrived', intent, '已到达目标页面')
      }
      if (isStale()) return outcome('superseded', intent, '已有更新的导航意图')
      return outcome('aborted', intent, '导航被拦截，可重试', raced.error)
    }
    return outcome('error', intent, '页面打开失败，可重试', raced.error)
  }

  // Push resolved: confirm we landed where the user asked (guards may redirect).
  if (routeMatchesTarget(router, match)) {
    return outcome('arrived', intent, '已到达目标页面')
  }
  // Guard may have redirected to login etc.; if intent still current, report unresolved.
  if (isStale()) return outcome('superseded', intent, '已有更新的导航意图')
  return outcome('unresolved', intent, '未能确认到达目标页面，可重试')
}

export function isSuccessfulNav(status: AppNavStatus): boolean {
  return status === 'arrived' || status === 'duplicate' || status === 'superseded'
}

export function shouldShowNavFailure(status: AppNavStatus): boolean {
  return status === 'aborted' || status === 'cancelled' || status === 'timeout' || status === 'error' || status === 'unresolved'
}
