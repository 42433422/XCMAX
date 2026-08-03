import { session } from 'electron'

/**
 * Chromium loads persisted cookies lazily. On a cold start immediately after
 * an update, the renderer's first enterprise-session validation can otherwise
 * race that load and incorrectly treat an existing signed-in user as logged
 * out. This only warms the existing HttpOnly cookie store; the backend still
 * performs the authoritative local-session and official-market validation.
 */
export async function warmPersistedDesktopSessionCookieStore(defaultPort: number): Promise<boolean> {
  const cookieStore = session.defaultSession.cookies
  if (!cookieStore?.get) return false
  try {
    const cookieName = String(process.env.SESSION_COOKIE_NAME || 'session_id').trim() || 'session_id'
    const cookies = await cookieStore.get({ url: `http://127.0.0.1:${defaultPort}/` })
    return cookies.some(cookie => cookie.name === cookieName && Boolean(cookie.value))
  } catch {
    return false
  }
}
