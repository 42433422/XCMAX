import type { Ref } from 'vue'
import type { ChatMessage } from './useChatMessages'
import type { ShipmentTask } from './useShipmentTask'
import {
  CHAT_MESSAGES_STORAGE_PREFIX,
  CHAT_SESSION_META_PREFIX,
  buildChatMessagesKey,
  buildChatSessionMetaKey,
  extractSessionIdForActiveMod,
} from '@/utils/chatStorageKeys'
import { isIndustryWelcomePlainText } from '@/constants/industryPresets'

/** 刷新后仍能把「分析 Excel」结果随 /api/ai/chat 的 context 带上，避免「加入数据库」落 LLM 空转 */
export const EXCEL_ANALYSIS_STORAGE_PREFIX = 'xcagi_excel_analysis_ctx_'
export const CHAT_TASK_PANEL_STORAGE_PREFIX = 'xcagi_chat_task_panel_'

export type TaskStatus = 'queued' | 'running' | 'success' | 'failed' | 'cancelled'

export interface TaskItem {
  id: string
  type: string
  title: string
  source: 'workflow' | 'excel' | 'print' | 'shipment' | 'manual' | 'system' | 'wechat'
  status: TaskStatus
  progress?: number
  stage?: string
  summary?: string
  error?: string
  startedAt: number
  updatedAt: number
  messageRef?: string
  payload?: Record<string, unknown>
}

export type PersistedTaskPanelState = {
  taskList: TaskItem[]
  activeTaskId: string
  expandedTaskIds: string[]
  taskFilter: 'all' | 'running' | 'success' | 'failed'
  currentTask: ShipmentTask | null
  savedAt: number
}

export type LinkedExcelSheet = { sheet_name: string; sheet_index: number }

export function readPersistedExcelAnalysisContext(sessionKey: string): Record<string, unknown> | null {
  if (typeof sessionStorage === 'undefined') return null
  try {
    const raw = sessionStorage.getItem(EXCEL_ANALYSIS_STORAGE_PREFIX + sessionKey)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    return parsed && typeof parsed === 'object' ? parsed : null
  } catch {
    return null
  }
}

export function persistExcelAnalysisContext(sessionKey: string, ctx: Record<string, unknown> | null) {
  if (typeof sessionStorage === 'undefined') return
  try {
    const key = EXCEL_ANALYSIS_STORAGE_PREFIX + sessionKey
    if (!ctx) sessionStorage.removeItem(key)
    else sessionStorage.setItem(key, JSON.stringify(ctx))
  } catch {
    /* quota / private mode */
  }
}

export function resolveExcelFilePathFromAnalysis(result: unknown): string {
  const r = result as Record<string, unknown> | null | undefined
  const candidates = [
    r?.file_path,
    (r?.preview_data as Record<string, unknown> | undefined)?.file_path,
    (r?.data as Record<string, unknown> | undefined)?.file_path,
    ((r?.data as Record<string, unknown> | undefined)?.preview_data as Record<string, unknown> | undefined)?.file_path,
    (r?.document as Record<string, unknown> | undefined)?.filepath,
    (r?.document as Record<string, unknown> | undefined)?.file_path,
    (r?.meta as Record<string, unknown> | undefined)?.file_path,
    (r?.upload as Record<string, unknown> | undefined)?.file_path,
    (r?.source as Record<string, unknown> | undefined)?.file_path,
  ]
  for (const raw of candidates) {
    const p = String(raw || '').trim()
    if (!p) continue
    return p
  }
  return ''
}

export function resolveExcelSheetOptionsFromContext(ctx: unknown): LinkedExcelSheet[] {
  if (!ctx || typeof ctx !== 'object') return []
  const c = ctx as Record<string, unknown>
  const previewData = c.preview_data as Record<string, unknown> | undefined
  const allSheets = Array.isArray(previewData?.all_sheets) ? previewData.all_sheets : []
  const result: LinkedExcelSheet[] = []
  if (allSheets.length) {
    allSheets.forEach((s: unknown, idx: number) => {
      const sheet = s as Record<string, unknown>
      const name = String(sheet?.sheet_name || '').trim()
      if (!name) return
      result.push({ sheet_name: name, sheet_index: Number(sheet?.sheet_index) || idx + 1 })
    })
    return result
  }
  const names = Array.isArray(previewData?.sheet_names) ? previewData.sheet_names : []
  names.forEach((name: unknown, idx: number) => {
    const n = String(name || '').trim()
    if (!n) return
    result.push({ sheet_name: n, sheet_index: idx + 1 })
  })
  return result
}

export function resolveLinkedSheetGridPreview(
  ctx: unknown,
  linkedSheet: LinkedExcelSheet | null
): Record<string, unknown> | null {
  if (!ctx || typeof ctx !== 'object' || !linkedSheet?.sheet_name) return null
  const c = ctx as Record<string, unknown>
  const previewData = c.preview_data as Record<string, unknown> | undefined
  const allSheets = Array.isArray(previewData?.all_sheets) ? previewData.all_sheets : []
  const target = allSheets.find((s: unknown) => {
    const sheet = s as Record<string, unknown>
    const n = String(sheet?.sheet_name || '').trim()
    const i = Number(sheet?.sheet_index || 0)
    return (linkedSheet.sheet_name && n === linkedSheet.sheet_name)
      || (linkedSheet.sheet_index > 0 && i === linkedSheet.sheet_index)
  }) as Record<string, unknown> | undefined
  if (!target) return null
  const sampleRows = Array.isArray(target?.sample_rows) ? target.sample_rows.slice(0, 8) : []
  const fieldNames = (Array.isArray(target?.fields) ? target.fields : [])
    .map((f: unknown) => String((f as Record<string, unknown>)?.label || (f as Record<string, unknown>)?.name || '').trim())
    .filter(Boolean)
    .slice(0, 40)
  const gridPreview = target?.grid_preview as Record<string, unknown> | undefined
  const rows = Array.isArray(gridPreview?.rows) ? (gridPreview.rows as unknown[]) : []
  const gridRows = rows.slice(0, 60)
  const previewText = [
    `Sheet ${linkedSheet.sheet_index}（${linkedSheet.sheet_name}）`,
    fieldNames.length ? `字段：${fieldNames.join('、')}` : '',
    sampleRows.length ? `样例：${JSON.stringify(sampleRows)}` : '',
    gridRows.length ? `网格前 ${gridRows.length} 行：${JSON.stringify(gridRows)}` : '',
  ].filter(Boolean).join('\n')
  return {
    sheet_name: linkedSheet.sheet_name,
    sheet_index: linkedSheet.sheet_index,
    field_names: fieldNames,
    sample_rows: sampleRows,
    grid_preview_rows: gridRows,
    preview_text: previewText,
  }
}

/** 从常见「查价/查型号」话术里抽关键词，用于在等 AI 完整响应前先打开产品副窗并行查库 */
export function extractLikelyProductQueryKeyword(raw: string): string | null {
  const t = String(raw || '').trim()
  if (t.length < 2 || t.length > 200) return null
  if (/^(什么|怎么|如何|为什么|能否|请|帮)/.test(t)) return null
  if (/(出货单|发货单|订单列表|客户列表|工作流|批量|导入|上传|数据库|打印标签|打印\s|有哪些客户|今天.*单)/.test(t)) {
    return null
  }
  const patterns: RegExp[] = [
    /^查询\s*(.+)$/u,
    /^查一下\s*(.+?)\s*的?(?:价格|价钱|多少钱)?\s*[。！？…]*$/iu,
    /^帮我查(?:询)?\s*(.+?)\s*(?:的)?(?:价格|多少钱)?\s*[。！？…]*$/iu,
  ]
  for (const re of patterns) {
    const m = t.match(re)
    if (m?.[1]) {
      let k = String(m[1]).trim().replace(/[。！？…]+$/g, '').trim()
      if ((k.startsWith('「') && k.endsWith('」')) || (k.startsWith('"') && k.endsWith('"')) || (k.startsWith('『') && k.endsWith('』'))) {
        k = k.slice(1, -1).trim()
      }
      k = k.replace(/^(产品|型号|货号)[是为：:\s]+/i, '').trim()
      if (k.length >= 1 && k.length <= 120) return k
    }
  }
  return null
}

export function readPersistedTaskPanelState(sessionKey: string): PersistedTaskPanelState | null {
  const sid = String(sessionKey || '').trim()
  if (!sid || typeof sessionStorage === 'undefined') return null
  try {
    const raw = sessionStorage.getItem(CHAT_TASK_PANEL_STORAGE_PREFIX + sid)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object') return null
    const taskList = Array.isArray((parsed as PersistedTaskPanelState).taskList)
      ? (parsed as PersistedTaskPanelState).taskList
      : []
    const activeTaskId = String((parsed as PersistedTaskPanelState).activeTaskId || '').trim()
    const expandedTaskIds = Array.isArray((parsed as PersistedTaskPanelState).expandedTaskIds)
      ? (parsed as PersistedTaskPanelState).expandedTaskIds.map((x) => String(x || '').trim()).filter(Boolean)
      : []
    const filterRaw = String((parsed as PersistedTaskPanelState).taskFilter || '').trim()
    const taskFilter = (['all', 'running', 'success', 'failed'].includes(filterRaw)
      ? filterRaw
      : 'all') as PersistedTaskPanelState['taskFilter']
    const currentTask = ((parsed as PersistedTaskPanelState).currentTask
      && typeof (parsed as PersistedTaskPanelState).currentTask === 'object')
      ? (parsed as PersistedTaskPanelState).currentTask as ShipmentTask
      : null
    return {
      taskList,
      activeTaskId,
      expandedTaskIds,
      taskFilter,
      currentTask,
      savedAt: Number((parsed as PersistedTaskPanelState).savedAt || 0) || 0,
    }
  } catch {
    return null
  }
}

export function persistTaskPanelState(sessionKey: string, state: PersistedTaskPanelState): void {
  const sid = String(sessionKey || '').trim()
  if (!sid || typeof sessionStorage === 'undefined') return
  try {
    sessionStorage.setItem(CHAT_TASK_PANEL_STORAGE_PREFIX + sid, JSON.stringify(state))
  } catch {
    /* ignore quota/private mode */
  }
}

export function clearPersistedTaskPanelState(sessionKey: string): void {
  const sid = String(sessionKey || '').trim()
  if (!sid || typeof sessionStorage === 'undefined') return
  try {
    sessionStorage.removeItem(CHAT_TASK_PANEL_STORAGE_PREFIX + sid)
  } catch {
    /* ignore */
  }
}

export const TASK_HISTORY_LIMIT = 20

export function toPlainText(raw: unknown): string {
  return String(raw || '')
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<[^>]*>/g, '')
    .replace(/&nbsp;/gi, ' ')
    .trim()
}

export function isWelcomeMessage(msg: { role?: unknown; content?: unknown }): boolean {
  return String(msg?.role || '') === 'ai' && isIndustryWelcomePlainText(toPlainText(msg?.content))
}

export function toHistoryTimestamp(raw: unknown): number {
  const ts = Date.parse(String(raw || '').trim())
  return Number.isFinite(ts) ? ts : 0
}

export interface ChatHistoryPersistenceDeps {
  sessionId: Ref<string>
  getActiveModId: () => string
}

export function useChatHistoryPersistence(deps: ChatHistoryPersistenceDeps) {
  const { sessionId, getActiveModId } = deps

  function normalizeHistorySessions(rawSessions: unknown[]): Array<Record<string, unknown>> {
    return (Array.isArray(rawSessions) ? rawSessions : [])
      .map((session: unknown, idx: number) => {
        const s = session as Record<string, unknown>
        const sid = String(s?.session_id || s?.id || '').trim()
        if (!sid) return null
        const title = String(s?.title || s?.summary || '').trim() || `会话 ${idx + 1}`
        const count = Number(
          s?.message_count
          ?? (Array.isArray(s?.messages) ? s.messages.length : 0),
        )
        return {
          ...s,
          session_id: sid,
          title,
          message_count: Number.isFinite(count) && count >= 0 ? count : 0,
          last_message_at: String(s?.last_message_at || s?.updated_at || s?.created_at || '').trim(),
          is_local_only: false,
        }
      })
      .filter(Boolean) as Array<Record<string, unknown>>
  }

  function readLocalMessagesBySession(targetSessionId: string): ChatMessage[] {
    const sid = String(targetSessionId || '').trim()
    if (!sid || typeof localStorage === 'undefined') return []
    try {
      const raw = localStorage.getItem(buildChatMessagesKey(sid, getActiveModId()))
      if (!raw) return []
      const parsed = JSON.parse(raw)
      if (!Array.isArray(parsed)) return []
      return parsed
        .map((msg: unknown) => {
          const m = msg as Record<string, unknown>
          return {
            role: m?.role === 'user' || m?.role === 'task' ? m.role : 'ai',
            content: String(m?.content || ''),
            time: String(m?.time || '').trim() || new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
          } as ChatMessage
        })
        .filter((msg: ChatMessage) => !!toPlainText(msg.content))
    } catch {
      return []
    }
  }

  function readLocalSessionMeta(targetSessionId: string): Record<string, unknown> | null {
    const sid = String(targetSessionId || '').trim()
    if (!sid || typeof localStorage === 'undefined') return null
    try {
      const raw = localStorage.getItem(buildChatSessionMetaKey(sid, getActiveModId()))
      if (!raw) return null
      const parsed = JSON.parse(raw)
      return parsed && typeof parsed === 'object' ? parsed : null
    } catch {
      return null
    }
  }

  function deriveLocalSessionTitle(
    messagesList: Array<{ role?: unknown; content?: unknown }>,
    fallbackTitle = '',
  ): string {
    const fallback = String(fallbackTitle || '').trim()
    if (fallback) return fallback
    const meaningful = messagesList.filter((msg) => {
      const plain = toPlainText(msg?.content)
      if (!plain) return false
      return !isWelcomeMessage(msg)
    })
    const preferred = meaningful.find((msg) => String(msg?.role || '') === 'user') || meaningful[0]
    const plain = toPlainText(preferred?.content || '').replace(/\s+/g, ' ').trim()
    if (!plain) return '新会话'
    return plain.length > 32 ? `${plain.slice(0, 32)}...` : plain
  }

  function buildLocalHistorySession(targetSessionId: string): Record<string, unknown> | null {
    const sid = String(targetSessionId || '').trim()
    if (!sid) return null
    const cachedMessages = readLocalMessagesBySession(sid)
    const meaningful = cachedMessages.filter((msg) => {
      const plain = toPlainText(msg.content)
      if (!plain) return false
      return !isWelcomeMessage(msg)
    })
    if (!meaningful.length) return null
    const meta = readLocalSessionMeta(sid)
    const title = deriveLocalSessionTitle(cachedMessages, String(meta?.title || ''))
    const count = Number(meta?.message_count ?? meaningful.length)
    const updatedAt = String(meta?.updated_at || '').trim() || new Date().toISOString()
    return {
      session_id: sid,
      title,
      message_count: Number.isFinite(count) && count >= 0 ? count : meaningful.length,
      last_message_at: updatedAt,
      is_local_only: true,
    }
  }

  function listLocalHistorySessions(limit = 50): Array<Record<string, unknown>> {
    if (typeof localStorage === 'undefined') return []
    const currentMod = getActiveModId()
    const ids = new Set<string>()
    for (let i = 0; i < localStorage.length; i += 1) {
      const key = String(localStorage.key(i) || '')
      const metaSid = extractSessionIdForActiveMod(CHAT_SESSION_META_PREFIX, key, currentMod)
      if (metaSid) {
        ids.add(metaSid)
        continue
      }
      const msgSid = extractSessionIdForActiveMod(CHAT_MESSAGES_STORAGE_PREFIX, key, currentMod)
      if (msgSid) {
        ids.add(msgSid)
      }
    }
    const sessions = Array.from(ids)
      .map((sid) => buildLocalHistorySession(sid))
      .filter(Boolean) as Array<Record<string, unknown>>
    sessions.sort((a, b) => toHistoryTimestamp(b.last_message_at) - toHistoryTimestamp(a.last_message_at))
    return sessions.slice(0, Math.max(1, limit))
  }

  function mergeHistorySessions(serverRawSessions: unknown[]): Array<Record<string, unknown>> {
    const serverSessions = normalizeHistorySessions(serverRawSessions)
    const localSessions = listLocalHistorySessions(80)
    const byId = new Map<string, Record<string, unknown>>()

    localSessions.forEach((session) => {
      byId.set(String(session.session_id), session)
    })

    serverSessions.forEach((session) => {
      const sid = String(session.session_id)
      const prev = byId.get(sid)
      byId.set(sid, {
        ...(prev || {}),
        ...session,
        is_local_only: false,
      })
    })

    const activeSessionId = String(sessionId.value || '').trim()
    if (activeSessionId && !byId.has(activeSessionId)) {
      const activeFallback = buildLocalHistorySession(activeSessionId)
      if (activeFallback) {
        byId.set(activeSessionId, activeFallback)
      }
    }

    const merged = Array.from(byId.values())
    merged.sort((a, b) => toHistoryTimestamp(b.last_message_at) - toHistoryTimestamp(a.last_message_at))
    return merged
  }

  function clearLocalHistoryCache(): void {
    if (typeof localStorage === 'undefined') return
    const currentMod = getActiveModId()
    const removeKeys: string[] = []
    for (let i = 0; i < localStorage.length; i += 1) {
      const key = String(localStorage.key(i) || '')
      if (
        extractSessionIdForActiveMod(CHAT_MESSAGES_STORAGE_PREFIX, key, currentMod)
        || extractSessionIdForActiveMod(CHAT_SESSION_META_PREFIX, key, currentMod)
      ) {
        removeKeys.push(key)
      }
    }
    removeKeys.forEach((key) => {
      localStorage.removeItem(key)
    })
  }

  return {
    normalizeHistorySessions,
    readLocalMessagesBySession,
    readLocalSessionMeta,
    deriveLocalSessionTitle,
    buildLocalHistorySession,
    listLocalHistorySessions,
    mergeHistorySessions,
    clearLocalHistoryCache,
    toPlainText,
    isWelcomeMessage,
    toHistoryTimestamp,
  }
}

export interface ChatTaskPanelPersistenceDeps {
  sessionId: Ref<string>
  taskList: Ref<TaskItem[]>
  activeTaskId: Ref<string>
  expandedTaskIds: Ref<string[]>
  taskFilter: Ref<'all' | 'running' | 'success' | 'failed'>
  currentTask: Ref<ShipmentTask | null>
  sortTaskList: () => void
}

export function useChatTaskPanelPersistence(deps: ChatTaskPanelPersistenceDeps) {
  const {
    sessionId,
    taskList,
    activeTaskId,
    expandedTaskIds,
    taskFilter,
    currentTask,
    sortTaskList,
  } = deps

  function persistTaskPanelStateForSession(targetSessionId?: string): void {
    const sid = String(targetSessionId || sessionId.value || '').trim() || 'default'
    persistTaskPanelState(sid, {
      taskList: taskList.value.slice(0, TASK_HISTORY_LIMIT),
      activeTaskId: String(activeTaskId.value || '').trim(),
      expandedTaskIds: expandedTaskIds.value.slice(0, 80),
      taskFilter: taskFilter.value,
      currentTask: (currentTask.value ? { ...(currentTask.value as ShipmentTask) } : null),
      savedAt: Date.now(),
    })
  }

  function applyPersistedTaskPanelStateForSession(targetSessionId?: string): void {
    const sid = String(targetSessionId || sessionId.value || '').trim() || 'default'
    const persisted = readPersistedTaskPanelState(sid)
    if (!persisted) {
      taskList.value = []
      activeTaskId.value = ''
      expandedTaskIds.value = []
      taskFilter.value = 'all'
      currentTask.value = null
      return
    }
    taskList.value = Array.isArray(persisted.taskList) ? persisted.taskList.slice(0, TASK_HISTORY_LIMIT) : []
    taskFilter.value = persisted.taskFilter
    currentTask.value = (persisted.currentTask || null) as ShipmentTask | null
    const idSet = new Set(taskList.value.map((t) => t.id))
    expandedTaskIds.value = (persisted.expandedTaskIds || []).filter((id) => idSet.has(id)).slice(0, 80)
    activeTaskId.value = persisted.activeTaskId && idSet.has(persisted.activeTaskId)
      ? persisted.activeTaskId
      : (taskList.value[0]?.id || '')
    sortTaskList()
  }

  return {
    persistTaskPanelStateForSession,
    applyPersistedTaskPanelStateForSession,
  }
}
