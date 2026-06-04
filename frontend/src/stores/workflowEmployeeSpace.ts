import { defineStore } from 'pinia'
import { ref } from 'vue'
import { shortNameFromPanelTitle } from '@/utils/workflowEmployeeDisplayName'
import { useWorkflowAiEmployeesStore } from '@/stores/workflowAiEmployees'
import { aminSignalBridges } from '@/utils/aminRegistry'

export const WORKFLOW_EMPLOYEE_SPACE_STORAGE_KEY = 'xcagi_workflow_employee_space_v1'
export const WORKFLOW_EMPLOYEE_SESSIONS_STORAGE_KEY = 'xcagi_workflow_employee_sessions_v1'

export type WorkflowEmployeeSpaceSnapshot = {
  empId: string
  panelTitle: string
  shortName: string
  stage: string
  progressPct: number
  progressLabel: string
  hintLine: string
  /** 与任务面板 workflowProgressIdle 一致 */
  idle: boolean
  /** 用于像素工位：是否在「干活」视觉态 */
  visuallyBusy: boolean
  lastActivityAt: number
}

/**
 * 员工的「工时与产能」量化数据，用于工位卡片头顶的状态条 / 工位特写。
 *
 * - `enabledAt`: 当前一次「副窗一键托管」打开的时间戳；关闭时清空，再开则刷新。
 * - `firstActivityAt`: 首次实际处理活动的时间戳（跨会话累计，仅记录第一次）。
 * - `lastActivityAt`: 最近一次活动；用于「最近 5 分钟无新活动 → 视觉态淡化」类判断。
 * - `processedCount`: 累计处理任务数（仅 applyFromWorkflowPayload 的非心跳调用，
 *    心跳轮询如 wechat_star_feed_polled 不计数）。
 * - `sessionMs`: 本次启用累计时长；关闭时把 `now - enabledAt` 累加进 `lifetimeMs` 后清零。
 * - `lifetimeMs`: 历史累计工时（已下班的所有 session 之和）。当前 session 的实时时长在外层渲染时按 `now - enabledAt` 计算后叠加。
 */
export type WorkflowEmployeeSession = {
  empId: string
  enabledAt: number | null
  firstActivityAt: number | null
  lastActivityAt: number | null
  processedCount: number
  lifetimeMs: number
}

type PersistedV1 = {
  schemaVersion: 1
  snapshots: Record<string, WorkflowEmployeeSpaceSnapshot>
}

type PersistedSessionsV1 = {
  schemaVersion: 1
  sessions: Record<string, WorkflowEmployeeSession>
}

function safeParsePersisted(raw: string | null): PersistedV1 | null {
  if (!raw) return null
  try {
    const p = JSON.parse(raw) as unknown
    if (!p || typeof p !== 'object') return null
    const o = p as Record<string, unknown>
    if (o.schemaVersion !== 1) return null
    const snaps = o.snapshots
    if (!snaps || typeof snaps !== 'object') return null
    return { schemaVersion: 1, snapshots: snaps as Record<string, WorkflowEmployeeSpaceSnapshot> }
  } catch {
    return null
  }
}

function safeParseSessions(raw: string | null): PersistedSessionsV1 | null {
  if (!raw) return null
  try {
    const p = JSON.parse(raw) as unknown
    if (!p || typeof p !== 'object') return null
    const o = p as Record<string, unknown>
    if (o.schemaVersion !== 1) return null
    const sess = o.sessions
    if (!sess || typeof sess !== 'object') return null
    return { schemaVersion: 1, sessions: sess as Record<string, WorkflowEmployeeSession> }
  } catch {
    return null
  }
}

function emptySession(empId: string): WorkflowEmployeeSession {
  return {
    empId,
    enabledAt: null,
    firstActivityAt: null,
    lastActivityAt: null,
    processedCount: 0,
    lifetimeMs: 0,
  }
}

function snapshotVisuallyBusy(payload: Record<string, unknown>): boolean {
  const idle = payload.workflowProgressIdle === true
  const started = payload.workflowProgressStarted === true
  const pct = Number(payload.workflowProgressPct ?? 0)
  if (idle) return false
  if (started) return true
  return pct > 0
}

let persistTimer: number | null = null
let sessionsPersistTimer: number | null = null

function schedulePersist(snapshots: Record<string, WorkflowEmployeeSpaceSnapshot>) {
  if (typeof window === 'undefined') return
  if (persistTimer != null) window.clearTimeout(persistTimer)
  persistTimer = window.setTimeout(() => {
    persistTimer = null
    try {
      const out: PersistedV1 = { schemaVersion: 1, snapshots: { ...snapshots } }
      sessionStorage.setItem(WORKFLOW_EMPLOYEE_SPACE_STORAGE_KEY, JSON.stringify(out))
    } catch {
      /* quota / private mode */
    }
  }, 280)
}

function scheduleSessionsPersist(sessions: Record<string, WorkflowEmployeeSession>) {
  if (typeof window === 'undefined') return
  if (sessionsPersistTimer != null) window.clearTimeout(sessionsPersistTimer)
  sessionsPersistTimer = window.setTimeout(() => {
    sessionsPersistTimer = null
    try {
      const out: PersistedSessionsV1 = { schemaVersion: 1, sessions: { ...sessions } }
      /** 工时累计跨页要存活，用 localStorage（与 xcagi_workflow_ai_employees 持久层一致） */
      localStorage.setItem(WORKFLOW_EMPLOYEE_SESSIONS_STORAGE_KEY, JSON.stringify(out))
    } catch {
      /* quota / private mode */
    }
  }, 280)
}

export const useWorkflowEmployeeSpaceStore = defineStore('workflowEmployeeSpace', () => {
  const snapshots = ref<Record<string, WorkflowEmployeeSpaceSnapshot>>({})
  const sessions = ref<Record<string, WorkflowEmployeeSession>>({})

  function hydrateFromSessionStorage() {
    if (typeof sessionStorage === 'undefined') return
    try {
      const parsed = safeParsePersisted(sessionStorage.getItem(WORKFLOW_EMPLOYEE_SPACE_STORAGE_KEY))
      if (parsed?.snapshots) {
        snapshots.value = { ...parsed.snapshots }
      }
    } catch {
      /* ignore */
    }
  }

  function hydrateSessionsFromLocalStorage() {
    if (typeof localStorage === 'undefined') return
    try {
      const parsed = safeParseSessions(localStorage.getItem(WORKFLOW_EMPLOYEE_SESSIONS_STORAGE_KEY))
      if (parsed?.sessions) {
        sessions.value = { ...parsed.sessions }
      }
    } catch {
      /* ignore */
    }
  }

  hydrateFromSessionStorage()
  hydrateSessionsFromLocalStorage()

  function ensureSession(empId: string): WorkflowEmployeeSession {
    const cur = sessions.value[empId]
    if (cur) return cur
    const fresh = emptySession(empId)
    sessions.value = { ...sessions.value, [empId]: fresh }
    return fresh
  }

  /** 副窗一键托管开 → 记录上工时间 */
  function markEnabled(empId: string) {
    if (!empId) return
    const cur = ensureSession(empId)
    if (cur.enabledAt) return
    sessions.value = {
      ...sessions.value,
      [empId]: { ...cur, enabledAt: Date.now() },
    }
    scheduleSessionsPersist(sessions.value)
  }

  /** 副窗一键托管关 → 把当前 session 时长累加进 lifetime */
  function markDisabled(empId: string) {
    if (!empId) return
    const cur = sessions.value[empId]
    if (!cur || !cur.enabledAt) return
    const elapsed = Math.max(0, Date.now() - cur.enabledAt)
    sessions.value = {
      ...sessions.value,
      [empId]: {
        ...cur,
        enabledAt: null,
        lifetimeMs: cur.lifetimeMs + elapsed,
      },
    }
    scheduleSessionsPersist(sessions.value)
  }

  function bumpProcessed(empId: string) {
    if (!empId) return
    const cur = ensureSession(empId)
    const now = Date.now()
    sessions.value = {
      ...sessions.value,
      [empId]: {
        ...cur,
        processedCount: cur.processedCount + 1,
        firstActivityAt: cur.firstActivityAt ?? now,
        lastActivityAt: now,
      },
    }
    scheduleSessionsPersist(sessions.value)
  }

  function applyFromWorkflowPayload(
    panelTitle: string,
    payload: Record<string, unknown> | null | undefined,
    options: { isHeartbeat?: boolean } = {}
  ) {
    const empId = String(payload?.employeeId ?? '').trim()
    if (!empId) return
    const stage = String(payload?.workflowStageLine ?? '').trim()
    const progressPct = Math.max(0, Math.min(100, Number(payload?.workflowProgressPct ?? 0) || 0))
    const progressLabel = String(payload?.workflowProgressLabel ?? '').trim()
    const hintLine = String(payload?.workflowCurrentHint ?? '').trim()
    const idle = payload?.workflowProgressIdle === true
    const visuallyBusy = snapshotVisuallyBusy(payload || {})

    const next: WorkflowEmployeeSpaceSnapshot = {
      empId,
      panelTitle: String(panelTitle || '').trim() || `工作流 · ${empId}`,
      shortName: shortNameFromPanelTitle(panelTitle),
      stage: stage || '—',
      progressPct,
      progressLabel,
      hintLine,
      idle,
      visuallyBusy,
      lastActivityAt: Date.now(),
    }

    const prev = snapshots.value[empId]
    const sameSnapshot =
      prev &&
      prev.stage === next.stage &&
      prev.progressPct === next.progressPct &&
      prev.progressLabel === next.progressLabel &&
      prev.hintLine === next.hintLine &&
      prev.idle === next.idle &&
      prev.visuallyBusy === next.visuallyBusy &&
      prev.panelTitle === next.panelTitle

    /**
     * 心跳（如星标轮询）即便相同也写一次 lastActivityAt 以保留「在线」感，
     * 但不计入「已处理任务数」；真实活动且状态变化时才递增 processedCount。
     */
    if (!options.isHeartbeat && !sameSnapshot) {
      bumpProcessed(empId)
    }

    if (sameSnapshot) return

    snapshots.value = { ...snapshots.value, [empId]: next }
    schedulePersist(snapshots.value)
  }

  function applyLabelPrintBridge(detail: { at?: number; line?: string }) {
    const bridge = aminSignalBridges().find((b) => b.empId === 'label_print')
    if (bridge) bridge.handler(detail as Record<string, unknown>)
  }

  function applyReceiptBridge(detail: {
    at?: number
    line?: string
    intentLabel?: string
    messageText?: string
    contactName?: string
  }) {
    const bridge = aminSignalBridges().find((b) => b.empId === 'receipt_confirm')
    if (bridge) bridge.handler(detail as Record<string, unknown>)
  }

  function applyWechatMsgBridge(detail: { messageText?: string; contactName?: string }) {
    const bridges = aminSignalBridges().filter((b) => b.empId === 'wechat_msg' && b.eventNames.includes('xcagi:wechat-ai-task-enqueue'))
    for (const bridge of bridges) bridge.handler(detail as Record<string, unknown>)
  }

  function applyWechatStarFeedPolledBridge(detail: { at?: number; intervalMs?: number; contactCount?: number; ok?: boolean }) {
    const bridges = aminSignalBridges().filter((b) => b.empId === 'wechat_msg' && b.eventNames.includes('xcagi:wechat-star-feed-polled'))
    for (const bridge of bridges) bridge.handler(detail as Record<string, unknown>)
  }

  function removeEmployee(empId: string) {
    if (!snapshots.value[empId]) return
    const next = { ...snapshots.value }
    delete next[empId]
    snapshots.value = next
    schedulePersist(snapshots.value)
  }

  /**
   * 跟踪副窗一键托管开关：开 → markEnabled，关 → markDisabled。
   * 通过 pinia $subscribe 与开关 store 解耦——卡片 UI 只调 wfEmp.toggle，
   * 工时累计在这里集中处理，避免分散到每个调用点。
   */
  const wfEmp = useWorkflowAiEmployeesStore()
  let lastEnabled: Record<string, boolean> = { ...wfEmp.enabled }
  /** 初始化阶段：已经处于开启的员工，把 enabledAt 设为「现在」（从启动那一刻算起） */
  for (const id of Object.keys(lastEnabled)) {
    if (lastEnabled[id]) markEnabled(id)
  }
  wfEmp.$subscribe((_mutation, state) => {
    const cur = state.enabled as Record<string, boolean>
    const allIds = new Set([...Object.keys(lastEnabled), ...Object.keys(cur)])
    for (const id of allIds) {
      const wasOn = lastEnabled[id] === true
      const isOn = cur[id] === true
      if (!wasOn && isOn) markEnabled(id)
      else if (wasOn && !isOn) markDisabled(id)
    }
    lastEnabled = { ...cur }
  })

  return {
    snapshots,
    sessions,
    hydrateFromSessionStorage,
    hydrateSessionsFromLocalStorage,
    applyFromWorkflowPayload,
    applyLabelPrintBridge,
    applyReceiptBridge,
    applyWechatMsgBridge,
    applyWechatStarFeedPolledBridge,
    removeEmployee,
    markEnabled,
    markDisabled,
  }
})
