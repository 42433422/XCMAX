import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { useModsStore } from '@/stores/mods'
import { useWorkflowAiEmployeesStore } from '@/stores/workflowAiEmployees'
import { useWorkflowEmployeeSpaceStore, type WorkflowEmployeeSpaceSnapshot } from '@/stores/workflowEmployeeSpace'
import { WORKFLOW_DOC_CORE_EMPLOYEE_IDS } from '@/constants/workflowEmployeeDocIds'
import { buildModWorkflowPanelMeta, type ModWithWorkflowEmployees } from '@/utils/modWorkflowEmployees'
import { shortNameFromPanelTitle } from '@/utils/workflowEmployeeDisplayName'

const BUILTIN_PANEL_TITLE: Record<string, string> = {
  label_print: '工作流 · 标签打印 AI 员工',
  shipment_mgmt: '工作流 · 出货管理 AI 员工',
  receipt_confirm: '工作流 · 收货确认 AI 员工',
  wechat_msg: '工作流 · 微信消息处理 AI 员工',
}

export type WorkflowEmployeeDeskRow = {
  empId: string
  panelTitle: string
  shortName: string
  enabled: boolean
  snapshot?: WorkflowEmployeeSpaceSnapshot
}

function collectEmployeeIds(mods: ModWithWorkflowEmployees[] | undefined): string[] {
  const out: string[] = [...WORKFLOW_DOC_CORE_EMPLOYEE_IDS]
  const seen = new Set(out)
  for (const m of mods || []) {
    for (const e of m.workflow_employees || []) {
      const id = String(e?.id || '').trim()
      if (!id || seen.has(id)) continue
      seen.add(id)
      out.push(id)
    }
  }
  return out
}

/**
 * 员工空间 / 拼接全景页共用的工位行数据（与副窗开关、任务快照同源）。
 */
export function useWorkflowEmployeeDesks() {
  const modsStore = useModsStore()
  const wfEmp = useWorkflowAiEmployeesStore()
  const spaceStore = useWorkflowEmployeeSpaceStore()
  const { enabled: workflowEnabled } = storeToRefs(wfEmp)
  const { snapshots } = storeToRefs(spaceStore)

  const employeeIds = computed(() => collectEmployeeIds(modsStore.modsForUi))

  const modTitleMap = computed(() => buildModWorkflowPanelMeta(modsStore.modsForUi))

  function resolvePanelTitle(empId: string): string {
    const b = BUILTIN_PANEL_TITLE[empId]
    if (b) return b
    const m = modTitleMap.value[empId]
    if (m?.title) return m.title
    return `工作流 · ${empId}`
  }

  const desks = computed<WorkflowEmployeeDeskRow[]>(() => {
    return employeeIds.value.map((empId) => {
      const panelTitle = resolvePanelTitle(empId)
      const en = workflowEnabled.value[empId] === true
      const snap = snapshots.value[empId]
      return {
        empId,
        panelTitle,
        shortName: snap?.shortName || shortNameFromPanelTitle(panelTitle),
        enabled: en,
        snapshot: snap,
      }
    })
  })

  function statusLine(row: WorkflowEmployeeDeskRow): string {
    if (!row.enabled) return '副窗未启用'
    const s = row.snapshot
    if (!s) return '暂无快照'
    return s.stage || s.progressLabel || s.hintLine || '待命'
  }

  function ariaLabel(row: WorkflowEmployeeDeskRow): string {
    const state = !row.enabled ? '副窗未启用' : row.snapshot ? statusLine(row) : '等待活动'
    return `员工 ${row.shortName}。${state}`
  }

  function isBusy(row: WorkflowEmployeeDeskRow): boolean {
    if (!row.enabled) return false
    const s = row.snapshot
    if (!s) return false
    return s.visuallyBusy === true
  }

  return {
    employeeIds,
    desks,
    statusLine,
    ariaLabel,
    isBusy,
  }
}
