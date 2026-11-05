/** Bind offline reads to the Electron cookie jar belonging to the trusted sender. */
import type { Cookie, Session } from 'electron'
import { queryOffline } from './data-bridge'
import type { OfflineQueryParams, OfflineQueryResult } from './data-bridge'

export async function queryOfflineForSession(
  session: Pick<Session, 'cookies'>,
  dbPath: string,
  params: OfflineQueryParams,
  origin: string,
  cookieName = 'session_id',
): Promise<OfflineQueryResult> {
  try {
    const url = new URL(origin)
    if (url.protocol !== 'http:' || url.hostname !== '127.0.0.1' || url.username || url.password) {
      return { ok: false, error: 'auth_required' }
    }
  } catch {
    return { ok: false, error: 'auth_required' }
  }
  if (!cookieName.trim()) return { ok: false, error: 'auth_required' }
  const cookies = session.cookies
  let changed = false
  const onChanged = (_event: unknown, cookie: Pick<Cookie, 'name'>) => {
    if (cookie.name === cookieName) changed = true
  }
  const readSession = async (): Promise<string | null> => {
    const found = await cookies.get({ url: origin, name: cookieName })
    if (found.length !== 1) return null
    const cookie = found[0]
    if (cookie.expirationDate !== undefined && cookie.expirationDate <= Date.now() / 1000) {
      return null
    }
    return cookie.value || null
  }
  cookies.on('changed', onChanged)
  try {
    const sessionId = await readSession()
    if (!sessionId) return { ok: false, error: 'auth_required' }
    const result = await queryOffline(dbPath, params, sessionId)
    const current = await readSession()
    if (changed || current !== sessionId) return { ok: false, error: 'auth_changed' }
    return result
  } catch {
    return { ok: false, error: 'auth_unavailable' }
  } finally {
    cookies.removeListener('changed', onChanged)
  }
}
