/** Read-only offline queries, authorized against the host's live session store. */
import { app } from 'electron'
import fs from 'node:fs'
import path from 'node:path'

export interface OfflineQueryParams {
  kind: string
  keyword?: string
  limit?: number
}

export interface OfflineQueryResult {
  ok: boolean
  data?: unknown[]
  error?: string
  dbPath?: string
}

interface SqliteLike {
  prepare(sql: string): { all(...params: unknown[]): unknown[] }
  exec(sql: string): void
  close(): void
}

const MAX_SAFE_LIMIT = 200
const MAX_KEYWORD_LEN = 200

function clampLimit(raw: number | undefined): number {
  const n = Number.isFinite(raw) ? Math.floor(raw as number) : 20
  return Math.max(1, Math.min(MAX_SAFE_LIMIT, n))
}

/** backendExecutable() supplies this same userData directory as --data-dir. */
export function desktopOfflineDbPath(): string {
  return path.join(app.getPath('userData'), 'data', 'xcagi.db')
}

async function openReadOnlyDb(dbPath: string): Promise<SqliteLike | null> {
  try {
    const mod = (await import('node:sqlite')) as {
      DatabaseSync: new (p: string, opts?: { readOnly?: boolean }) => SqliteLike
    }
    return new mod.DatabaseSync(dbPath, { readOnly: true })
  } catch {
    return null
  }
}

/** userId is resolved by queryOffline, never taken from renderer query parameters. */
export function resolveOfflineQuery(
  kind: string,
  params: OfflineQueryParams,
  userId?: number,
): { sql: string; bind: unknown[] } | null {
  if (!Number.isSafeInteger(userId) || (userId as number) <= 0) return null
  const limit = clampLimit(params.limit)
  const member = `EXISTS (SELECT 1 FROM im_conversation_members cm
                         WHERE cm.conversation_id = m.conversation_id AND cm.user_id = ?)`
  switch (kind) {
    case 'tables':
      return {
        sql: `SELECT name FROM sqlite_master WHERE type='table' ORDER BY name`,
        bind: [],
      }
    case 'chat_recent':
      return {
        sql: `SELECT m.id, m.conversation_id, m.sender_user_id, m.body, m.created_at
              FROM im_messages m WHERE ${member} ORDER BY m.id DESC LIMIT ?`,
        bind: [userId, limit],
      }
    case 'employees':
      return {
        sql: `SELECT id, employee_id, user_id, mod_id, display_name, avatar_url
              FROM ai_employee_profiles WHERE user_id = ? ORDER BY display_name LIMIT ?`,
        bind: [userId, limit],
      }
    case 'search': {
      const kw = String(params.keyword || '').slice(0, MAX_KEYWORD_LEN).trim()
      if (!kw) return null
      const like = `%${kw}%`
      return {
        sql: `SELECT * FROM (
                SELECT 'message' AS kind, m.id AS row_id, m.body AS text, m.created_at AS ts
                FROM im_messages m WHERE ${member} AND m.body LIKE ? ORDER BY m.id DESC LIMIT ?
              ) UNION ALL SELECT * FROM (
                SELECT 'employee' AS kind, p.id AS row_id, p.display_name AS text, p.created_at AS ts
                FROM ai_employee_profiles p WHERE p.user_id = ? AND p.display_name LIKE ?
                ORDER BY p.id DESC LIMIT ?
              )`,
        bind: [userId, like, limit, userId, like, limit],
      }
    }
    default:
      return null
  }
}

/**
 * sessionId must come from the main process's cookie store, not an IPC payload.
 * Revalidate on every call; do not cache an account across logout or account changes.
 */
export async function queryOffline(
  dbPath: string,
  params: OfflineQueryParams,
  sessionId?: string,
): Promise<OfflineQueryResult> {
  if (typeof sessionId !== 'string' || !sessionId.trim() || sessionId.length > 512) {
    return { ok: false, error: 'auth_required' }
  }
  if (!fs.existsSync(dbPath)) return { ok: false, error: 'db_missing', dbPath }
  const db = await openReadOnlyDb(dbPath)
  if (!db) return { ok: false, error: 'unsupported', dbPath }
  try {
    db.exec('PRAGMA busy_timeout=1000; BEGIN')
    // SessionManager stores naive UTC dates; julianday also handles ISO UTC offsets.
    // Offline impersonation is deliberately denied until it has a separate verified identity.
    const rows = db.prepare(
      `SELECT s.user_id FROM sessions s JOIN users u ON u.id = s.user_id
       WHERE s.session_id = ? AND u.is_active = 1
         AND julianday(s.expires_at) > julianday('now')
         AND s.impersonating_market_user_id IS NULL LIMIT 1`,
    ).all(sessionId.trim()) as { user_id?: number }[]
    if (rows.length !== 1 || !Number.isSafeInteger(rows[0].user_id)) {
      return { ok: false, error: 'auth_required' }
    }
    const q = resolveOfflineQuery(params.kind, params, rows[0].user_id)
    if (!q) return { ok: false, error: 'unsupported_kind' }
    const data = db.prepare(q.sql).all(...q.bind)
    db.exec('COMMIT')
    return { ok: true, data, dbPath }
  } catch {
    // A missing/old authorization schema must never fall back to an unscoped read.
    return { ok: false, error: 'query_failed' }
  } finally {
    try { db.close() } catch { /* The query result remains fail-closed on errors. */ }
  }
}
