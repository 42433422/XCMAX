import {
  employeePackIconKind,
  employeePackRole,
  OFFICE_EMPLOYEE_PKG_IDS,
  OFFICE_GROUP_LABELS,
} from '@/constants/officeEmployeePack'
import { OFFICE_EMPLOYEE_PACK_BRIDGE_MOD_ID } from '@/constants/officeEmployeePackMod'
import type { WorkflowEmployeeDeskRow } from '@/composables/useWorkflowEmployeeDesks'
import type { EmployeePlannerStatus } from '@/constants/platformShell'

export function resolveOfficeInstalledPackIds(status: EmployeePlannerStatus): string[] {
  const fromApi = status.office_installed_ids
  if (fromApi?.length) return [...fromApi]
  const missing = new Set(status.missing_office_pack_ids || [])
  if (status.office_ready) return [...OFFICE_EMPLOYEE_PKG_IDS]
  return OFFICE_EMPLOYEE_PKG_IDS.filter((id) => !missing.has(id))
}

export function officePackIdToShortLabel(packId: string): string {
  const kind = employeePackIconKind(packId)
  const base = OFFICE_GROUP_LABELS[kind] || packId
  const role = employeePackRole(packId)
  if (role === 'read') return `${base}·读`
  if (role === 'generate') return `${base}·写`
  if (role === 'report') return `${base}·报告`
  return base
}

/** 已安装的办公 employee_pack → 四部门图 L1 工具层展示行（非工作流工位） */
export function buildOfficeToolDeskRows(installedIds: string[]): WorkflowEmployeeDeskRow[] {
  return installedIds
    .map((id) => String(id || '').trim())
    .filter(Boolean)
    .map((empId) => {
      const shortName = officePackIdToShortLabel(empId)
      return {
        empId,
        panelTitle: `办公工具 · ${shortName}`,
        shortName,
        enabled: true,
        hostModId: OFFICE_EMPLOYEE_PACK_BRIDGE_MOD_ID,
      }
    })
}
