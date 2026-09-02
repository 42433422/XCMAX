/**
 * Graph Run 批量执行与单任务派发。
 *
 * 由 AdminDutyEmployeeGraph.vue 原文机械迁出。
 */
import { api } from '../../../api'
import { publishButlerTask } from '../../../utils/agent/butlerTaskBus'
import { isDeployedDutyRosterRow, isVirtualEmployee } from './adminDutyConstants'
import type { AdminDutyState } from './useAdminDutyState'
import type { AdminDutyData } from './useAdminDutyData'
import type { AdminDutySelection } from './useAdminDutySelection'
import type { AdminDutyExec } from './useAdminDutyExec'
import type { DutyGraphRun, RunNodeStatus } from './adminDutyTypes'

export function useAdminDutyRun(
  s: AdminDutyState,
  data: AdminDutyData,
  selection: AdminDutySelection,
  exec: AdminDutyExec,
) {
  const { employees, runTargetId, runTaskBrief, runInputJson, runIncludeDependencies,
          runAllowHighRisk, runMaxConcurrency, runBusy, runError, latestRun,
          runNodeStatusMap, selectedEmp, taskBrief, taskInputJson, dispatchConfirmHighRisk,
          taskRunning, taskResult, taskError } = s
  const { selectedCapability } = selection
  const { loadPhase2, loadCapabilities } = data
  const { fetchExecMetrics } = exec
  let runPollTimer = 0

function parseJsonObjectInput(raw: string): Record<string, unknown> {
  const text = String(raw || '').trim()
  if (!text) return {}
  let parsed: unknown
  try {
    parsed = JSON.parse(text)
  } catch (err: unknown) {
    throw new Error(err instanceof Error ? err.message : 'input_data JSON 解析失败')
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('input_data 必须是 JSON 对象')
  }
  return parsed as Record<string, unknown>
}


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


  return { startGraphRun, stopRunPolling, pollRunDetail, dispatchTask, publishTaskToButler, applyRunNodeStatus }
}

export type AdminDutyRun = ReturnType<typeof useAdminDutyRun>
