import type { WorkflowEmployeeRegistryEntry } from '@/types/workflow-employee'
import {
  isWorkflowCarrierModId,
  modBelongsToEnterpriseStack,
  type EnterpriseModStack,
} from '@/constants/enterpriseModStack'
import { isHostBridgeModId } from '@/constants/genericModPack'
import {
  filterWorkflowRegistrySourceMods,
  isCustomPhaseEmployeeCarrierModId,
  isEmployeePackModEntry,
  type ModWithWorkflowEmployees,
} from '@/utils/modWorkflowEmployees'

/** 副窗 / 员工空间：仅展示当前企业 Mod 栈内的工作流员工 */
export function workflowRegistryEntryBelongsToStack(
  entry: Pick<WorkflowEmployeeRegistryEntry, 'hostModId' | 'carrierModId'>,
  stack: EnterpriseModStack | null,
): boolean {
  const carrier = String(entry.carrierModId || entry.hostModId || '').trim()
  if (!carrier || isCustomPhaseEmployeeCarrierModId(carrier)) return false
  if (stack) {
    return modBelongsToEnterpriseStack(carrier, stack)
  }
  return isWorkflowCarrierModId(carrier) || isHostBridgeModId(carrier)
}

export function filterWorkflowRegistryEntriesForEnterpriseStack(
  entries: WorkflowEmployeeRegistryEntry[],
  stack: EnterpriseModStack | null,
): WorkflowEmployeeRegistryEntry[] {
  return entries.filter((entry) => workflowRegistryEntryBelongsToStack(entry, stack))
}

/** 注册表合并源：仅当前企业 Mod 栈相关 manifest（行业包/定制/基础线/工作流载体） */
export function filterModsForEnterpriseWorkflowRegistry(
  mods: ModWithWorkflowEmployees[] | undefined,
  stack: EnterpriseModStack | null,
): ModWithWorkflowEmployees[] {
  const list = mods || []
  if (!stack) return filterWorkflowRegistrySourceMods(list)

  const stackModIds = new Set([...stack.packageModIds, ...stack.hostLineModIds])
  return list.filter((m) => {
    const id = String(m.id || '').trim()
    if (!id) return false
    const wf = m.workflow_employees || []
    if (!Array.isArray(wf) || !wf.length) return false
    if (isEmployeePackModEntry(m)) return false
    if (stackModIds.has(id)) return true
    return modBelongsToEnterpriseStack(id, stack)
  })
}
