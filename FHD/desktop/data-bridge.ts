/**
 * 原生本地数据桥（离线只读）
 *
 * 用途：当本地后端 HTTP 不可用时（后端未就绪 / 崩溃 / 维护中），前端仍可
 * 通过 Electron IPC 直读本机 `userData/data/xcagi.db`（SQLite，WAL 多读安全），
 * 实现对聊天历史 / AI 员工配置的离线检索，把"本地优先"变成可感知的可靠性。
 *
 * 设计约束：
 * - 只读打开（readOnly），绝不写库；后端仍是数据权威，本桥只做离线兜底。
 * - 所有 SQL 均为固定白名单查询 + 参数绑定，杜绝注入。
 * - `node:sqlite`（Electron 41 内置 Node 22）不可用时优雅降级，不阻塞主流程。
 */

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

const MAX_SAFE_LIMIT = 200
const MAX_KEYWORD_LEN = 200

/** 仅依赖最小方法面的 SQLite 抽象，避免与 node:sqlite 具体类型强耦合。 */
interface SqliteLike {
  prepare(sql: string): { all(...params: unknown[]): unknown[] }
  close(): void
}

function clampLimit(raw: number | undefined): number {
  const n = Number.isFinite(raw) ? Math.floor(raw as number) : 20
  return Math.max(1, Math.min(MAX_SAFE_LIMIT, n))
}

/** 桌面后端 SQLite 主库路径（与 run_fastapi.py / paths.py 一致）。 */
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

/** 白名单查询解析：每种 kind 对应固定 SQL + 参数；未知 kind 返回 null。 */
export function resolveOfflineQuery(
  kind: string,
  params: OfflineQueryParams,
): { sql: string; bind: unknown[] } | null {
  const limit = clampLimit(params.limit)
  switch (kind) {
    case 'tables':
      return {
        sql: `SELECT name FROM sqlite_master WHERE type='table' ORDER BY name`,
        bind: [],
      }
    case 'chat_recent':
      return {
        sql: `SELECT id, conversation_id, sender_user_id, body, created_at
              FROM im_messages
              ORDER BY id DESC
              LIMIT ?`,
        bind: [limit],
      }
    case 'employees':
      return {
        sql: `SELECT id, employee_id, user_id, mod_id, display_name, avatar_url
              FROM ai_employee_profiles
              ORDER BY display_name
              LIMIT ?`,
        bind: [limit],
      }
    case 'search': {
      const kw = String(params.keyword || '').slice(0, MAX_KEYWORD_LEN).trim()
      if (!kw) return null
      const like = `%${kw}%`
      return {
        sql: `SELECT * FROM (
                SELECT 'message' AS kind, m.id AS row_id, m.body AS text, m.created_at AS ts
                FROM im_messages m WHERE m.body LIKE ? LIMIT ?
              )
              UNION ALL
              SELECT * FROM (
                SELECT 'employee' AS kind, p.id AS row_id, p.display_name AS text, p.created_at AS ts
                FROM ai_employee_profiles p WHERE p.display_name LIKE ? LIMIT ?
              )`,
        bind: [like, limit, like, limit],
      }
    }
    default:
      return null
  }
}

/** 执行一次离线只读查询。任何不可用/异常都返回 ok:false，不抛错。 */
export async function queryOffline(
  dbPath: string,
  params: OfflineQueryParams,
): Promise<OfflineQueryResult> {
  if (!fs.existsSync(dbPath)) {
    return { ok: false, error: 'db_missing', dbPath }
  }
  const db = await openReadOnlyDb(dbPath)
  if (!db) {
    return { ok: false, error: 'unsupported', dbPath }
  }
  try {
    const q = resolveOfflineQuery(params.kind, params)
    if (!q) {
      return { ok: false, error: 'unsupported_kind', dbPath }
    }
    const stmt = db.prepare(q.sql)
    const rows = stmt.all(...q.bind)
    return { ok: true, data: rows as unknown[], dbPath }
  } catch (e) {
    return {
      ok: false,
      error: `query_failed:${e instanceof Error ? e.message : String(e)}`,
      dbPath,
    }
  } finally {
    db.close()
  }
}
