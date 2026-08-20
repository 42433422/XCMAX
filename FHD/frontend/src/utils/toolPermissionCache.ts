/**
 * 工具权限缓存（GitHub Copilot 三档授权的简化版）。
 *
 * 当用户在审批卡上"批准此工具"时，记忆授权范围：
 * - 'session'      本会话内不再询问（存 sessionStorage）
 * - 'persistent'   永久授权（存 localStorage，跨会话保留）
 *
 * 后端配合（待实现）：当 plan 带 permission_scope 时跳过 step.waiting_user。
 * 前端缓存层先做：让 UI 能展示"已授权"标记 + 自动调用现有确认流程。
 */

const SESSION_KEY = 'xcagi_tool_permissions_session'
const PERSIST_KEY = 'xcagi_tool_permissions_persistent'

export type ToolPermissionScope = 'session' | 'persistent'

interface PermissionStore {
  [toolId: string]: { scope: ToolPermissionScope; grantedAt: number }
}

function readStore(storage: Storage, key: string): PermissionStore {
  try {
    const raw = storage.getItem(key)
    if (!raw) return {}
    const parsed = JSON.parse(raw)
    return parsed && typeof parsed === 'object' ? (parsed as PermissionStore) : {}
  } catch {
    return {}
  }
}

function writeStore(storage: Storage, key: string, store: PermissionStore): void {
  try {
    storage.setItem(key, JSON.stringify(store))
  } catch {
    // ignore quota / privacy mode errors
  }
}

function readSession(): PermissionStore {
  if (typeof sessionStorage === 'undefined') return {}
  return readStore(sessionStorage, SESSION_KEY)
}

function readPersistent(): PermissionStore {
  if (typeof localStorage === 'undefined') return {}
  return readStore(localStorage, PERSIST_KEY)
}

function writeSession(store: PermissionStore): void {
  if (typeof sessionStorage === 'undefined') return
  writeStore(sessionStorage, SESSION_KEY, store)
}

function writePersistent(store: PermissionStore): void {
  if (typeof localStorage === 'undefined') return
  writeStore(localStorage, PERSIST_KEY, store)
}

/** 查询某 tool 的授权范围，session 优先于 persistent */
export function getToolPermission(toolId: string): ToolPermissionScope | null {
  const id = String(toolId || '').trim()
  if (!id) return null
  const session = readSession()[id]
  if (session) return 'session'
  const persistent = readPersistent()[id]
  if (persistent) return 'persistent'
  return null
}

/** 记录授权（同时从另一个 store 清除旧记录，避免同一 tool 在两个 store 残留） */
export function setToolPermission(toolId: string, scope: ToolPermissionScope): void {
  const id = String(toolId || '').trim()
  if (!id) return
  const entry = { scope, grantedAt: Date.now() }
  if (scope === 'session') {
    const store = readSession()
    store[id] = entry
    writeSession(store)
    // 从 persistent store 清除（升级/降级时避免残留）
    const p = readPersistent()
    if (p[id]) {
      delete p[id]
      writePersistent(p)
    }
  } else {
    const store = readPersistent()
    store[id] = entry
    writePersistent(store)
    // 从 session store 清除
    const s = readSession()
    if (s[id]) {
      delete s[id]
      writeSession(s)
    }
  }
}

/** 撤销某 tool 的授权（两个 store 都清） */
export function clearToolPermission(toolId: string): void {
  const id = String(toolId || '').trim()
  if (!id) return
  const s = readSession()
  delete s[id]
  writeSession(s)
  const p = readPersistent()
  delete p[id]
  writePersistent(p)
}

/** 会话切换 / 登出时清空所有会话级授权 */
export function clearSessionPermissions(): void {
  if (typeof sessionStorage !== 'undefined') {
    sessionStorage.removeItem(SESSION_KEY)
  }
}

/** 查询所有已授权的 tool（用于调试 / UI 展示） */
export function listAuthorizedTools(): { tool_id: string; scope: ToolPermissionScope }[] {
  const session = readSession()
  const persistent = readPersistent()
  const out: { tool_id: string; scope: ToolPermissionScope }[] = []
  for (const [id, entry] of Object.entries(persistent)) {
    out.push({ tool_id: id, scope: entry.scope })
  }
  for (const [id, entry] of Object.entries(session)) {
    out.push({ tool_id: id, scope: entry.scope })
  }
  return out
}
