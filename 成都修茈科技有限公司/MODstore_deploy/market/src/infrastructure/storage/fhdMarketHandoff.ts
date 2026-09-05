import type { RouteLocationNormalized } from 'vue-router'
import { clearAuthTokens, setAuthTokens } from './tokenStore'

const CODE_KEY = 'xcagi_code'
const SECRET_KEYS = ['xcagi_mt', CODE_KEY, 'access_token', 'refresh_token']
type Handoff = { code: string; target: string }
let pending: Handoff | null = null

function inspectUrl(url: URL): Handoff | null {
  const hash = new URLSearchParams(url.hash.replace(/^#/, ''))
  const hasSecretHash = SECRET_KEYS.some((key) => hash.has(key))
  const hasSecretQuery = SECRET_KEYS.some((key) => url.searchParams.has(key))
  if (!hasSecretHash && !hasSecretQuery) return null
  const raw = hash.get(CODE_KEY) || ''
  const code = hash.size === 1 && /^[A-Za-z0-9_-]{43}$/.test(raw) ? raw : ''
  for (const key of SECRET_KEYS) url.searchParams.delete(key)
  if (hasSecretHash) url.hash = ''
  const path = url.pathname.replace(/^\/market(?=\/)/, '')
  return { code, target: path + url.search }
}

/** Run before bootstrap HTTP requests: remove credentials even when auth fails. */
export function captureBrowserHandoff(): void {
  const url = new URL(window.location.href)
  const incoming = inspectUrl(url)
  if (!incoming) return
  pending = incoming
  window.history.replaceState(window.history.state, '', url.pathname + url.search + url.hash)
}

export function takeBrowserHandoff(to: RouteLocationNormalized): Handoff | null {
  if (pending) {
    const incoming = pending
    pending = null
    return incoming
  }
  const url = new URL(to.fullPath || to.path || '/', window.location.origin)
  const incoming = inspectUrl(url)
  if (incoming) {
    // Also covers navigation inside an already-running SPA and failed exchanges.
    const visible = new URL(window.location.href)
    if (inspectUrl(visible)) {
      window.history.replaceState(window.history.state, '', visible.pathname + visible.search + visible.hash)
    }
  }
  return incoming
}

export async function consumeBrowserHandoff(handoff: Handoff): Promise<void> {
  const target = new URL(handoff.target, window.location.origin)
  if (!handoff.code || target.origin !== window.location.origin || !['/wallet', '/plans'].includes(target.pathname)) {
    throw new Error('登录连接已失效')
  }
  const base = String(import.meta.env.VITE_API_BASE || '')
    .trim()
    .replace(/\/$/, '')
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), 8_000)
  try {
    // The one-use code authenticates this POST; never forward a previous user's bearer.
    const response = await fetch(`${base}/api/auth/browser-handoff/consume`, {
      method: 'POST',
      credentials: 'omit',
      cache: 'no-store',
      referrerPolicy: 'no-referrer',
      headers: { 'Content-Type': 'application/json' },
      signal: controller.signal,
      body: JSON.stringify({ code: handoff.code, target: handoff.target, purpose: target.pathname.slice(1) }),
    })
    if (!response.ok) throw new Error('登录连接已失效')
    const result = await response.json()
    if (
      !result.ok ||
      typeof result.access_token !== 'string' ||
      !result.access_token ||
      typeof result.refresh_token !== 'string' ||
      !result.refresh_token
    )
      throw new Error('登录连接已失效')
    // Never keep the previous identity's refresh token after switching accounts.
    clearAuthTokens()
    setAuthTokens({ access_token: result.access_token, refresh_token: result.refresh_token })
  } finally {
    clearTimeout(timer)
  }
}
