import { defineStore } from 'pinia'
import { ref } from 'vue'
import { shortNameFromPanelTitle } from '@/utils/workflowEmployeeDisplayName'
import { useWorkflowAiEmployeesStore } from '@/stores/workflowAiEmployees'

export const WORKFLOW_EMPLOYEE_SPACE_STORAGE_KEY = 'xcagi_workflow_employee_space_v1'

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

type PersistedV1 = {
  schemaVersion: 1
  snapshots: Record<string, WorkflowEmployeeSpaceSnapshot>
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

function snapshotVisuallyBusy(payload: Record<string, unknown>): boolean {
  const idle = payload.workflowProgressIdle === true
  const started = payload.workflowProgressStarted === true
  const pct = Number(payload.workflowProgressPct ?? 0)
  if (idle) return false
  if (started) return true
  return pct > 0
}

let persistTimer: number | null = null

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

export const useWorkflowEmployeeSpaceStore = defineStore('workflowEmployeeSpace', () => {
  const snapshots = ref<Record<string, WorkflowEmployeeSpaceSnapshot>>({})

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

  hydrateFromSessionStorage()

  function applyFromWorkflowPayload(panelTitle: string, payload: Record<string, unknown> | null | undefined) {
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
    if (
      prev &&
      prev.stage === next.stage &&
      prev.progressPct === next.progressPct &&
      prev.progressLabel === next.progressLabel &&
      prev.hintLine === next.hintLine &&
      prev.idle === next.idle &&
      prev.visuallyBusy === next.visuallyBusy &&
      prev.panelTitle === next.panelTitle
    ) {
      return
    }

    snapshots.value = { ...snapshots.value, [empId]: next }
    schedulePersist(snapshots.value)
  }

  /** 副窗事件桥：仅更新标签打印工作流快照（不操作任务列表） */
  function applyLabelPrintBridge(detail: { at?: number; line?: string }) {
    const wf = useWorkflowAiEmployeesStore()
    if (!wf.enabled.label_print) return
    const line = String(detail?.line || '').trim() || '标签/打印类消息'
    const at = Number(detail?.at) || Date.now()
    applyFromWorkflowPayload('工作流 · 标签打印 AI 员工', {
      employeeId: 'label_print',
      workflowStageLine: '已收微信侧标签/打印信号',
      workflowProgressPct: 55,
      workflowProgressLabel: '进行中',
      workflowCurrentHint: `最近命中标签/打印意图：${line.slice(0, 160)}${line.length > 160 ? '…' : ''}`,
      workflowProgressIdle: false,
      workflowProgressStarted: true,
      lastLabelPrint: { at, line },
    })
  }

  /** 副窗事件桥：收货确认 */
  function applyReceiptBridge(detail: {
    at?: number
    line?: string
    intentLabel?: string
    messageText?: string
    contactName?: string
  }) {
    const wf = useWorkflowAiEmployeesStore()
    if (!wf.enabled.receipt_confirm) return
    const line = String(detail?.line || '').trim() || '客户反馈'
    const at = Number(detail?.at) || Date.now()
    const hint = [
      detail?.contactName ? `联系人：${detail.contactName}` : '',
      detail?.intentLabel ? `意图：${detail.intentLabel}` : '',
      detail?.messageText ? `摘要：${String(detail.messageText).slice(0, 120)}` : '',
    ]
      .filter(Boolean)
      .join(' · ')
    applyFromWorkflowPayload('工作流 · 收货确认 AI 员工', {
      employeeId: 'receipt_confirm',
      workflowStageLine: '已收客户侧业务进程反馈',
      workflowProgressPct: 55,
      workflowProgressLabel: '进行中',
      workflowCurrentHint: hint || line,
      workflowProgressIdle: false,
      workflowProgressStarted: true,
      lastReceiptFeedback: { at, line, detail: hint },
    })
  }

  /** 副窗事件桥：微信消息处理（与 onWechatAiTaskEnqueue 写入的 lastWechat 对齐） */
  function applyWechatMsgBridge(detail: { messageText?: string; contactName?: string }) {
    const wf = useWorkflowAiEmployeesStore()
    if (!wf.enabled.wechat_msg) return
    const name = String(detail?.contactName || '星标联系人').trim()
    const msg = String(detail?.messageText || '').trim()
    const line = `${name}：${msg.replace(/\s+/g, ' ').slice(0, 120)}`
    const at = Date.now()
    applyFromWorkflowPayload('工作流 · 微信消息处理 AI 员工', {
      employeeId: 'wechat_msg',
      workflowStageLine: '监控中 · 最近已处理',
      workflowProgressPct: 100,
      workflowProgressLabel: '处理中',
      workflowCurrentHint: `最近一条客户消息已预处理：${line.slice(0, 120)}${line.length > 120 ? '…' : ''}`,
      workflowProgressIdle: false,
      workflowProgressStarted: true,
      lastWechat: { at, line },
    })
  }

  /**
   * 星标轮询心跳：在无聊天页 upsert 时仍刷新「监控」提示（与任务面板 monitor 行语义接近）。
   */
  function applyWechatStarFeedPolledBridge(detail: { at?: number; intervalMs?: number; contactCount?: number; ok?: boolean }) {
    const wf = useWorkflowAiEmployeesStore()
    if (!wf.enabled.wechat_msg) return
    const prev = snapshots.value.wechat_msg
    const pollOk = detail?.ok !== false
    const t = Number(detail?.at) || Date.now()
    const sec = Math.max(1, Math.round((Number(detail?.intervalMs) || 60000) / 1000))
    const n = detail?.contactCount
    const cnt = typeof n === 'number' ? `星标联系人 ${n} 位` : '星标联系人'
    const clock = new Date(t).toLocaleTimeString('zh-CN', { hour12: false })
    const monitorLine = `${pollOk ? '拉取通道正常' : '上次拉取失败，将重试'} · 上次检查 ${clock} · 每 ${sec}s 轮询 · ${cnt}`
    applyFromWorkflowPayload(prev?.panelTitle || '工作流 · 微信消息处理 AI 员工', {
      employeeId: 'wechat_msg',
      workflowStageLine: prev?.stage && prev.stage.includes('已处理') ? prev.stage : '监控中 · 等待新消息',
      workflowProgressPct: prev?.progressPct ?? 30,
      workflowProgressLabel: prev?.progressLabel || '轮询中',
      workflowCurrentHint: prev?.hintLine ? `${prev.hintLine}\n${monitorLine}` : monitorLine,
      workflowProgressIdle: prev ? prev.idle : true,
      workflowProgressStarted: prev ? prev.visuallyBusy : false,
    })
  }

  function removeEmployee(empId: string) {
    if (!snapshots.value[empId]) return
    const next = { ...snapshots.value }
    delete next[empId]
    snapshots.value = next
    schedulePersist(snapshots.value)
  }

  return {
    snapshots,
    hydrateFromSessionStorage,
    applyFromWorkflowPayload,
    applyLabelPrintBridge,
    applyReceiptBridge,
    applyWechatMsgBridge,
    applyWechatStarFeedPolledBridge,
    removeEmployee,
  }
})
