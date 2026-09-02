/**
 * useChatWorkflowPanel 拆分：工作流员工任务写入与面板任务同步。
 */
import type { Ref } from 'vue'
import { buildModWorkflowPanelMeta, listPhoneAgentEmployeeIds } from '@/utils/modWorkflowEmployees'
import { isCoreWorkflowEmployeeId } from '@/constants/coreWorkflowMod'
import {
  appendCoreWorkflowSummaryParts,
  computeCoreWorkflowProgressState,
  computeWorkflowProgressFromSteps,
  mergeCorePayloadFromExisting,
  type WorkflowMonitorPayload,
} from '@/workflow/coreWorkflowMonitor'
import { formatWorkflowClock } from '@/workflow/coreWorkflowPrefs'
import type { useModsStore } from '@/stores/mods'
import type { TaskItem } from '../useChatPersistence'
import { phoneAgentWorkflowProgressShouldStart, type PhoneAgentStatusPayload } from './phoneAgentStatus'
import type { useWorkflowPanelDisplay } from './useWorkflowPanelDisplay'
import type { usePhoneAgentPolling } from './usePhoneAgentPolling'

export type WorkflowEmployeeTaskUpdate = {
  lastWechat?: { at: number; line: string }
  lastLabelPrint?: { at: number; line: string }
  lastShipmentAudit?: { at: number; line: string; detail?: string }
  lastReceiptFeedback?: { at: number; line: string; detail?: string }
  monitor?: WorkflowMonitorPayload | null
  phoneStatus?: PhoneAgentStatusPayload | null
}

export interface WorkflowPanelTasksDeps {
  taskList: Ref<TaskItem[]>
  activeTaskId: Ref<string>
  upsertTask: (item: Partial<TaskItem> & Pick<TaskItem, 'id' | 'type' | 'source' | 'title' | 'status'>) => void
  sortTaskList: () => void
  getModsForUi: () => ReturnType<typeof useModsStore>['modsForUi']
  readWorkflowEmployeeEnabledMap: () => Record<string, boolean>
  display: ReturnType<typeof useWorkflowPanelDisplay>
  phonePolling: Pick<
    ReturnType<typeof usePhoneAgentPolling>,
    'getEnabledPhoneEmployeeIds' | 'isPollActive' | 'startPhoneAgentStatusPoll' | 'stopPhoneAgentStatusPoll'
  >
}

export function useWorkflowPanelTasks(deps: WorkflowPanelTasksDeps) {
  const { taskList, activeTaskId, upsertTask, sortTaskList, getModsForUi, readWorkflowEmployeeEnabledMap } = deps
  const { resolvePhoneChannelByEmployee, buildWorkflowMonitorLine, buildWorkflowStepsForEmployee, computeWorkflowCurrentHint, computeWorkflowStageLine } =
    deps.display
  const { getEnabledPhoneEmployeeIds, isPollActive, startPhoneAgentStatusPoll, stopPhoneAgentStatusPoll } = deps.phonePolling

  function resolveWorkflowEmployeePanelMeta(empId: string): { title: string; summary: string } | null {
    const modMap = buildModWorkflowPanelMeta(getModsForUi())
    return modMap[empId] || null
  }

  /** 关闭 Mod 界面或 manifest 无该员工时，去掉任务面板中已无 meta 的工作流项 */
  function pruneStaleWorkflowEmployeeTasks() {
    for (let i = taskList.value.length - 1; i >= 0; i--) {
      const t = taskList.value[i]
      if (t?.type !== 'workflow_employee') continue
      const id = t.id
      if (typeof id !== 'string' || !id.startsWith('workflow_emp_')) continue
      const empId = id.slice('workflow_emp_'.length)
      if (resolveWorkflowEmployeePanelMeta(empId)) continue
      taskList.value.splice(i, 1)
      if (activeTaskId.value === id) {
        activeTaskId.value = taskList.value[0]?.id || ''
      }
    }
  }

  function upsertWorkflowEmployeeTask(empId: string, opts?: WorkflowEmployeeTaskUpdate) {
    const taskId = `workflow_emp_${empId}`
    const existing = taskList.value.find((t) => t.id === taskId)
    const coreCtx = mergeCorePayloadFromExisting(empId, opts, existing?.payload as Record<string, unknown> | undefined)
    const lastWechat = coreCtx.lastWechat
    const lastLabelPrint = coreCtx.lastLabelPrint
    const lastShipmentAudit = coreCtx.lastShipmentAudit
    const lastReceiptFeedback = coreCtx.lastReceiptFeedback

    let monitor: WorkflowMonitorPayload | undefined
    if (opts && 'monitor' in opts && opts.monitor !== undefined) {
      monitor = opts.monitor === null ? undefined : opts.monitor
    } else if (empId === 'wechat_msg' && existing?.payload?.monitor) {
      monitor = existing.payload.monitor as WorkflowMonitorPayload
    }

    let phoneStatus: PhoneAgentStatusPayload | undefined
    if (opts && 'phoneStatus' in opts && opts.phoneStatus !== undefined) {
      phoneStatus = opts.phoneStatus === null ? undefined : opts.phoneStatus
    } else if (listPhoneAgentEmployeeIds(getModsForUi()).includes(empId) && existing?.payload?.phoneStatus) {
      phoneStatus = existing.payload.phoneStatus as PhoneAgentStatusPayload
    }

    const steps = buildWorkflowStepsForEmployee(empId, {
      ...(lastWechat ? { lastWechat } : {}),
      ...(lastLabelPrint ? { lastLabelPrint } : {}),
      ...(lastShipmentAudit ? { lastShipmentAudit } : {}),
      ...(lastReceiptFeedback ? { lastReceiptFeedback } : {}),
      ...(phoneStatus ? { phoneStatus } : {}),
    })

    /** 微信员工：仅在实际「接收到新消息并完成一轮意图预处理」后才显示步骤进度，避免监控阶段出现 50% 等误导 */
    let progressPct = 0
    let progressLabel = ''
    let workflowProgressStarted = true
    if (isCoreWorkflowEmployeeId(empId)) {
      const prog = computeCoreWorkflowProgressState(empId, steps, coreCtx)
      progressPct = prog.progressPct
      progressLabel = prog.progressLabel
      workflowProgressStarted = prog.workflowProgressStarted
    } else if (resolvePhoneChannelByEmployee(empId) === 'wechat') {
      const ps = phoneStatus
      const psBad =
        !ps ||
        !!(ps.fetchError && String(ps.fetchError).trim()) ||
        ps.phone_agent_get_status_failed ||
        ps.phone_agent_status_route_failed ||
        ps.phone_agent_manager_load_failed
      const started = !psBad && phoneAgentWorkflowProgressShouldStart(ps)
      if (!started) {
        progressPct = 0
        progressLabel = !ps
          ? '正在同步后端 phone-agent 状态…'
          : psBad
            ? '无法计算进度：请先排除状态接口或管理器异常'
            : !ps.running
              ? (() => {
                  const err = String(ps.phone_agent_last_start_error || '').trim()
                  return err
                    ? `待命：未运行 — ${err.length > 60 ? `${err.slice(0, 60)}…` : err}`
                    : '待命：phone-agent 未运行（多为音频采集未启动，见后端日志）'
                })()
              : '待命：链路就绪，等待来电或通话界面（下次轮询会检测微信通话窗）'
        workflowProgressStarted = false
      } else {
        const p = computeWorkflowProgressFromSteps(steps)
        progressPct = p.pct
        progressLabel = p.label
        workflowProgressStarted = true
      }
    } else if (resolvePhoneChannelByEmployee(empId) === 'adb') {
      const ps = phoneStatus
      const started = !!(ps && ps.running && ps.adb_device_connected)
      if (!started) {
        progressPct = 0
        progressLabel = !ps
          ? '正在同步 ADB 电话状态…'
          : !ps.running
            ? '待命：ADB 链路未运行'
            : !ps.adb_available
              ? '待命：未检测到 adb'
              : '待命：等待设备在线'
        workflowProgressStarted = false
      } else {
        const p = computeWorkflowProgressFromSteps(steps)
        progressPct = p.pct
        progressLabel = p.label
        workflowProgressStarted = true
      }
    } else {
      const p = computeWorkflowProgressFromSteps(steps)
      progressPct = p.pct
      progressLabel = p.label
    }

    const workflowProgressIdle = !workflowProgressStarted

    const monitorLine = buildWorkflowMonitorLine(
      empId,
      steps,
      monitor,
      lastWechat,
      lastLabelPrint,
      lastShipmentAudit,
      lastReceiptFeedback,
      phoneStatus,
    )
    const hint = computeWorkflowCurrentHint(
      empId,
      steps,
      lastWechat,
      monitor,
      lastLabelPrint,
      lastShipmentAudit,
      lastReceiptFeedback,
      phoneStatus,
    )
    const meta = resolveWorkflowEmployeePanelMeta(empId)
    if (!meta) return
    const summaryParts = [meta.summary]
    appendCoreWorkflowSummaryParts(empId, summaryParts, coreCtx)
    if (resolvePhoneChannelByEmployee(empId) === 'wechat' && phoneStatus) {
      const ps = phoneStatus
      const bits = [
        ps.running ? '运行中' : '未运行',
        ps.window_monitor_available ? '窗口监控 OK' : '窗口监控不可用',
        ps.lastPolledAt ? `上次同步 ${formatWorkflowClock(ps.lastPolledAt)}` : '',
      ]
        .filter(Boolean)
        .join(' · ')
      summaryParts.push(`电话业务员状态：${bits}`)
      if (ps.last_popup_detected_at_ms) {
        summaryParts.push(
          `识别弹窗：${formatWorkflowClock(ps.last_popup_detected_at_ms)} · ${ps.last_popup_source || '—'} · ${String(ps.last_popup_title || '').slice(0, 60)}`,
        )
      }
      if (ps.last_click_at_ms != null && ps.last_click_at_ms !== undefined) {
        summaryParts.push(
          `接听点击：${ps.last_click_ok ? '成功' : '失败'} · ${formatWorkflowClock(ps.last_click_at_ms)} · ${ps.last_click_method || '—'}`,
        )
      }
      if (ps.last_asr_at_ms != null && ps.last_asr_at_ms !== undefined && (ps.last_asr_text || '').trim()) {
        summaryParts.push(
          `对方语音(ASR) ${formatWorkflowClock(ps.last_asr_at_ms)}：${String(ps.last_asr_text).slice(0, 160)}${
            String(ps.last_asr_text).length > 160 ? '…' : ''
          }`,
        )
      }
      if (ps.last_reply_at_ms != null && ps.last_reply_at_ms !== undefined && (ps.last_reply_text || '').trim()) {
        summaryParts.push(
          `回复送 VB ${formatWorkflowClock(ps.last_reply_at_ms)}：${String(ps.last_reply_text).slice(0, 160)}${
            String(ps.last_reply_text).length > 160 ? '…' : ''
          }`,
        )
      }
    }
    if (resolvePhoneChannelByEmployee(empId) === 'adb' && phoneStatus) {
      const ps = phoneStatus
      const bits = [
        ps.running ? '运行中' : '未运行',
        ps.adb_available ? 'ADB OK' : 'ADB 不可用',
        ps.adb_device_connected ? `设备 ${ps.adb_device_serial || 'online'}` : '无在线设备',
        ps.adb_call_state ? `状态 ${String(ps.adb_call_state).toUpperCase()}` : '',
      ]
        .filter(Boolean)
        .join(' · ')
      summaryParts.push(`真实电话状态：${bits}`)
      if (ps.adb_last_error) {
        summaryParts.push(`最近错误：${String(ps.adb_last_error).slice(0, 120)}`)
      }
    }

    upsertTask({
      id: taskId,
      type: 'workflow_employee',
      source: 'system',
      title: meta.title,
      status: 'running',
      progress: progressPct,
      stage: computeWorkflowStageLine(empId, lastWechat, lastLabelPrint, lastShipmentAudit, lastReceiptFeedback, phoneStatus),
      summary: summaryParts.join('\n\n'),
      payload: {
        employeeId: empId,
        workflowSteps: steps,
        workflowCurrentHint: hint,
        workflowProgressPct: progressPct,
        workflowProgressLabel: progressLabel,
        workflowProgressIdle,
        workflowProgressStarted,
        workflowMonitorLine: monitorLine,
        ...(lastWechat ? { lastWechat } : {}),
        ...(lastLabelPrint ? { lastLabelPrint } : {}),
        ...(lastShipmentAudit ? { lastShipmentAudit } : {}),
        ...(lastReceiptFeedback ? { lastReceiptFeedback } : {}),
        ...(monitor ? { monitor } : {}),
        ...(phoneStatus ? { phoneStatus } : {}),
      },
    })
  }

  function syncWorkflowEmployeePanelTasks(enabled: Record<string, boolean>) {
    const merged = { ...readWorkflowEmployeeEnabledMap(), ...enabled }
    const modMeta = buildModWorkflowPanelMeta(getModsForUi())
    const allEmpIds = new Set([...Object.keys(modMeta)])
    for (const empId of allEmpIds) {
      const taskId = `workflow_emp_${empId}`
      if (merged[empId]) {
        if (resolveWorkflowEmployeePanelMeta(empId)) {
          upsertWorkflowEmployeeTask(empId)
        }
      } else {
        const idx = taskList.value.findIndex((t) => t.id === taskId)
        if (idx !== -1) {
          taskList.value.splice(idx, 1)
          if (activeTaskId.value === taskId) {
            activeTaskId.value = taskList.value[0]?.id || ''
          }
        }
      }
    }
    pruneStaleWorkflowEmployeeTasks()
    sortTaskList()
    if (getEnabledPhoneEmployeeIds().length > 0) {
      if (!isPollActive()) startPhoneAgentStatusPoll()
    } else {
      stopPhoneAgentStatusPoll()
    }
  }

  function resyncEnabledWorkflowEmployeeTasks() {
    const enabled = readWorkflowEmployeeEnabledMap()
    const modMeta = buildModWorkflowPanelMeta(getModsForUi())
    const allEmpIds = new Set([...Object.keys(modMeta)])
    for (const empId of allEmpIds) {
      if (enabled[empId] && resolveWorkflowEmployeePanelMeta(empId)) {
        upsertWorkflowEmployeeTask(empId)
      }
    }
    pruneStaleWorkflowEmployeeTasks()
    sortTaskList()
  }

  return {
    resolveWorkflowEmployeePanelMeta,
    upsertWorkflowEmployeeTask,
    syncWorkflowEmployeePanelTasks,
    resyncEnabledWorkflowEmployeeTasks,
  }
}
