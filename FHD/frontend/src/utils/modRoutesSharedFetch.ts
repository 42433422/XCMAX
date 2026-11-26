import { apiFetch } from '@/utils/apiBase'
import { captureAuthSession } from '@/utils/authSessionCache'
import type { ModRouteApiEntry } from '@/router/registerModRoutes'

const MOD_ROUTES_TIMEOUT_MS = 25_000

// Share a request only within its original authenticated account/session.
type Pending = { current: () => boolean; promise: Promise<ModRouteApiEntry[] | null> }
let inflight: Pending | null = null

export function fetchModRoutesPayloadShared(): Promise<ModRouteApiEntry[] | null> {
  if (inflight?.current()) return inflight.promise
  const current = captureAuthSession()
  const pending: Pending = { current, promise: Promise.resolve(null) }
  pending.promise = (async () => {
    try {
      const response = await apiFetch('/api/mods/routes', {
        timeoutMs: MOD_ROUTES_TIMEOUT_MS,
      })
      if (!current() || !response.ok) return null
      const data = await response.json()
      if (current() && data.success && Array.isArray(data.data)) {
        return data.data as ModRouteApiEntry[]
      }
      return null
    } catch (e) {
      if (import.meta.env.DEV && current()) {
        console.warn('[modRoutesShared] /api/mods/routes:', e)
      }
      return null
    }
  })().finally(() => {
    if (inflight === pending) inflight = null
  })
  inflight = pending
  return pending.promise
}
