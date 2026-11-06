import { session } from 'electron'

type CookieReader = {
  get?: (filter: { url: string }) => Promise<Array<{ name?: string; value?: string }>>
}

/**
 * Chromium loads persisted cookies lazily. On a cold start immediately after
 * an update, the renderer's first enterprise-session validation can otherwise
 * race that load and incorrectly treat an existing signed-in user as logged
 * out. This only warms the existing HttpOnly cookie store; the backend still
 * performs the authoritative local-session and official-market validation.
 * 附加窗口传入自己的 cookie 存储，避免主窗口一次性消费后把后来的窗口判成未登录。
 */
export async function warmPersistedDesktopSessionCookieStore(
  defaultPort: number,
  cookieStore: CookieReader | null | undefined = session.defaultSession.cookies,
): Promise<boolean> {
  if (!cookieStore?.get) return false
  try {
    const cookieName = String(process.env.SESSION_COOKIE_NAME || 'session_id').trim() || 'session_id'
    const cookies = await cookieStore.get({ url: `http://127.0.0.1:${defaultPort}/` })
    return cookies.some(cookie => cookie.name === cookieName && Boolean(cookie.value))
  } catch {
    return false
  }
}
