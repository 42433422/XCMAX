/**
 * 最近执行指标（分页拉取 + 选中员工联动重置）。
 *
 * 由 AdminDutyEmployeeGraph.vue 原文机械迁出。
 */
import { watch } from 'vue'
import { api } from '../../../api'
import { EXEC_METRICS_PAGE, isVirtualEmployee } from './adminDutyConstants'
import type { AdminDutyState } from './useAdminDutyState'
import type { ExecRow } from './adminDutyTypes'

export function useAdminDutyExec(s: AdminDutyState) {
  const {
    selectedEmp, runTargetId, dispatchConfirmHighRisk,
    execItems, execTotal, execLoading, execLoadingMore, execError,
  } = s

async function fetchExecMetrics(append: boolean) {
  const emp = selectedEmp.value
  if (!emp) return
  if (isVirtualEmployee(emp.id)) {
    execItems.value = []
    execTotal.value = 0
    execLoading.value = false
    execLoadingMore.value = false
    return
  }
  if (append) execLoadingMore.value = true
  else {
    execLoading.value = true
    execError.value = ''
  }
  try {
    const offset = append ? execItems.value.length : 0
    const res = (await api.adminEmployeeExecutionMetrics(emp.id, {
      limit: EXEC_METRICS_PAGE,
      offset,
    })) as { items?: ExecRow[]; total?: number }
    const raw = Array.isArray(res?.items) ? res.items : []
    const items: ExecRow[] = raw.map((r) => ({
      id: Number(r.id),
      user_id: Number(r.user_id),
      task: typeof r.task === 'string' ? r.task : '',
      status: typeof r.status === 'string' ? r.status : '',
      duration_ms: Number(r.duration_ms) || 0,
      llm_tokens: Number(r.llm_tokens) || 0,
      error: typeof r.error === 'string' ? r.error : '',
      created_at: typeof r.created_at === 'string' ? r.created_at : null,
    }))
    if (append) execItems.value = [...execItems.value, ...items]
    else execItems.value = items
    execTotal.value = Number(res?.total ?? 0)
  } catch (e: unknown) {
    execError.value = e instanceof Error ? e.message : String(e)
    if (!append) execItems.value = []
  } finally {
    execLoading.value = false
    execLoadingMore.value = false
  }
}


watch(
  () => selectedEmp.value?.id,
  (id) => {
    execItems.value = []
    execTotal.value = 0
    execError.value = ''
    if (id) runTargetId.value = id
    dispatchConfirmHighRisk.value = false
    if (id) void fetchExecMetrics(false)
  },
)


  return { fetchExecMetrics }
}

export type AdminDutyExec = ReturnType<typeof useAdminDutyExec>
