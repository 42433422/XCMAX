/**
 * 图运行（协作图 run）、任务派发与轮询。
 *
 * 由 DutyRosterGraphPanel.vue 原文机械切分而来（行为保持不变）。
 */
import type { DutyRosterState } from './useDutyRosterState'
import type { RunNodeStatus, DutyGraphRun } from './dutyRosterTypes'
import type { DutyData } from './useDutyRosterData'
import type { DutyExec } from './useDutyExec'
import type { DutySelection } from './useDutySelection'
import { publishButlerTask } from '@host/utils/butlerTaskBus'
import api from '@/api/xcmaxMarketProxy'
import { isVirtualEmployee, parseJsonObjectInput } from './dutyRosterConstants'
export function useDutyRun(s: DutyRosterState, data: DutyData, exec: DutyExec, selection: DutySelection) {
  const { employees, missingLocalPackIds, healthMap, depsMap, loading, loadingP2, error, loadWarning, llmStatusMap, llmFernetConfigured, llmStatusFailed, empLlmMap, viewMode, showGapPanel, gapFocusHint, autoRefresh, countdown, capabilityMap, capLoading, runNodeStatusMap, loopRuntimeStatus, showStatsDetail, showMoreActions, detailCollapsed, empCapabilityViewMap, showNoKeyPanel, noKeyLoading, noKeyError, noKeyData, noKeyBusyRow, showAllHandsPanel, allHandsBusy, allHandsError, allHandsReport, allHandsWithResearch, allHandsExpanded, allHandsPlainOpen, allHandsPlainText, allHandsPlainLoading, allHandsPlainReqGen, allHandsMeetingMinutes, allHandsMeetingMinutesEmail, allHandsSessionId, allHandsQuestion, allHandsProgress, showRunPanel, runTargetId, runTaskBrief, runInputJson, runIncludeDependencies, runAllowHighRisk, runMaxConcurrency, runBusy, runError, latestRun, flowNodes, flowEdges, taskBrief, taskInputJson, dispatchConfirmHighRisk, taskRunning, taskResult, taskError, showDispatch, selectedEmp, selectedWorkshop, workshopRouteCopied, execItems, execTotal, execLoading, execLoadingMore, execError, onDutyEmployees, healthLevel, empAreaColor, llmActLevel, anyProviderHasUsableKey, runStatusLevel, capabilityLevel, capabilityColor, capabilityLabel, isDeployedDutyRosterRow } = s
  const { buildRosterEmployeeRows, load, butlerEmployeeRow, seedVirtualEmployees, loadPhase2, loadCapabilities, startAutoRefresh, stopAutoRefresh } = data
  const { fetchExecMetrics } = exec
  const { selectedHealth, selectedDeps, selectedCapabilityView, isSelectedVirtual, selectedLlm, selectedCapability, selectedRunNode } = selection

let   runPollTimer   = 0

function applyRunNodeStatus(run: DutyGraphRun | null) {
  if (!run || !Array.isArray(run.nodes)) {
    runNodeStatusMap.value = {}
    return
  }
  const next: Record<string, RunNodeStatus> = {}
  for (const node of run.nodes) {
    const eid = String(node?.employee_id ?? '').trim()
    if (!eid) continue
    const raw = String(node?.status ?? '').trim() as RunNodeStatus
    next[eid] = (['pending', 'running', 'success', 'failed', 'skipped'] as RunNodeStatus[]).includes(raw)
      ? raw
      : 'idle'
  }
  runNodeStatusMap.value = next
}

function stopRunPolling() {
  if (runPollTimer) {
    clearTimeout(runPollTimer)
    runPollTimer = 0
  }
}

async function pollRunDetail(runId: number) {
  stopRunPolling()
  try {
    const run = (await api.adminDutyGraphRunDetail(runId)) as DutyGraphRun
    latestRun.value = run
    applyRunNodeStatus(run)
    if (run?.status === 'running' || run?.status === 'pending') {
      runPollTimer = window.setTimeout(() => {
        void pollRunDetail(runId)
      }, 2000)
    }
  } catch (err: unknown) {
    runError.value = err instanceof Error ? err.message : String(err)
  }
}

async function startGraphRun() {
  if (runBusy.value) return
  const targetId = String(runTargetId.value || '').trim()
  if (!targetId) {
    runError.value = '请选择目标员工'
    return
  }
  if (!runTaskBrief.value.trim()) {
    runError.value = '请填写任务 brief'
    return
  }
  let inputData: Record<string, unknown> = {}
  try {
    inputData = parseJsonObjectInput(runInputJson.value)
  } catch (err: unknown) {
    runError.value = err instanceof Error ? err.message : String(err)
    return
  }
  runBusy.value = true
  runError.value = ''
  try {
    const run = (await api.adminDutyGraphRunStart({
      target_employee_id: targetId,
      task: runTaskBrief.value.trim(),
      input_data: inputData,
      include_dependencies: runIncludeDependencies.value,
      max_concurrency: Number(runMaxConcurrency.value) || 2,
      allow_high_risk_real_run: runAllowHighRisk.value,
    })) as DutyGraphRun
    latestRun.value = run
    applyRunNodeStatus(run)
    if (run?.id && (run?.status === 'running' || run?.status === 'pending')) {
      void pollRunDetail(Number(run.id))
    }
    // 刷新局部数据，让执行次数/最近执行及时可见
    setTimeout(() => {
      void loadPhase2(employees.value.filter(isDeployedDutyRosterRow))
      void loadCapabilities(employees.value.filter(isDeployedDutyRosterRow))
    }, 1200)
  } catch (err: unknown) {
    runError.value = err instanceof Error ? err.message : String(err)
  } finally {
    runBusy.value = false
  }
}

async function dispatchTask() {
  if (!selectedEmp.value || !taskBrief.value.trim() || taskRunning.value) return
  // 数字管家无后端 execute 接口；点击「派发执行」直接转走事件总线，让浮窗管家接手。
  if (isVirtualEmployee(selectedEmp.value.id)) {
    publishTaskToButler()
    return
  }
  if (selectedCapability.value?.risk?.high_risk && !dispatchConfirmHighRisk.value) {
    taskError.value = '该员工包含高风险动作，请先勾选二次确认后再执行'
    return
  }
  let inputData: Record<string, unknown> = {}
  try {
    inputData = parseJsonObjectInput(taskInputJson.value)
  } catch (err: unknown) {
    taskError.value = err instanceof Error ? err.message : String(err)
    return
  }
  taskRunning.value = true
  taskResult.value  = null
  taskError.value   = null
  try {
    const res = await api.executeEmployeeTask(selectedEmp.value.id, taskBrief.value.trim(), inputData) as Record<string, unknown>
    // Normalise result to a readable string
    if (typeof res === 'string') {
      taskResult.value = res
    } else if (res?.summary) {
      taskResult.value = String(res.summary)
    } else {
      const summary = {
        duration_ms: Number(res?.duration_ms ?? 0) || 0,
        llm_tokens: Number(res?.llm_tokens ?? 0) || 0,
        cognition_error: typeof res?.cognition_error === 'string' ? res.cognition_error : '',
        result: res?.result ?? null,
      }
      taskResult.value = JSON.stringify(summary, null, 2)
    }
    // Refresh health + execution list for this employee after execution
    setTimeout(() => {
      void loadPhase2([selectedEmp.value!])
      void loadCapabilities([selectedEmp.value!])
      void fetchExecMetrics(false)
    }, 1500)
  } catch (e: unknown) {
    taskError.value = e instanceof Error ? e.message : String(e)
  } finally {
    taskRunning.value = false
  }
}

function publishTaskToButler() {
  if (!selectedEmp.value || !taskBrief.value.trim() || taskRunning.value) return
  if (selectedCapability.value?.risk?.high_risk && !dispatchConfirmHighRisk.value) {
    taskError.value = '该员工包含高风险动作，请先勾选二次确认后再发布'
    return
  }
  let inputData: Record<string, unknown> = {}
  try {
    inputData = parseJsonObjectInput(taskInputJson.value)
  } catch (err: unknown) {
    taskError.value = err instanceof Error ? err.message : String(err)
    return
  }
  const emp = selectedEmp.value
  publishButlerTask({
    source: 'admin-duty-graph',
    employeeId: emp.id,
    employeeName: emp.name || emp.id,
    brief: taskBrief.value.trim(),
    inputData,
    includeDependencies: runIncludeDependencies.value,
    allowHighRisk: dispatchConfirmHighRisk.value || runAllowHighRisk.value,
    maxConcurrency: Number(runMaxConcurrency.value) || 2,
  })
  taskError.value = null
  taskResult.value = `已发布到数字管家：${emp.name || emp.id}`
}

// ─────────────────────────────────────────────────────────────────────────────
// Selection

  return {
    applyRunNodeStatus,
    stopRunPolling,
    pollRunDetail,
    startGraphRun,
    dispatchTask,
    publishTaskToButler,
  }
}

export type DutyRun = ReturnType<typeof useDutyRun>
