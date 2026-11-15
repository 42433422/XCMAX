import type { WorkflowEmployeeRegistryEntry } from '@/types/workflow-employee'
import { defaultHostModIdForMarketEmployee, isWorkflowCarrierModId, modBelongsToEnterpriseStack, type EnterpriseModStack } from '@/constants/enterpriseModStack'
import { isHostBridgeModId } from '@/constants/genericModPack'
import { entitlementMatchesMod } from '@/stores/mods/entitlements'
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
  const host = String(entry.hostModId || '').trim()
  const carrier = String(entry.carrierModId || entry.hostModId || '').trim()
  if (host && stack && isCustomPhaseEmployeeCarrierModId(carrier) && modBelongsToEnterpriseStack(host, stack)) return true
  if (!carrier || isCustomPhaseEmployeeCarrierModId(carrier)) return false
  if (stack) {
    return modBelongsToEnterpriseStack(carrier, stack)
  }
  return isWorkflowCarrierModId(carrier) || isHostBridgeModId(carrier)
}

export function harvestOfficialCarrierEmployeesForStack(
  mods: ModWithWorkflowEmployees[] | undefined,
  stack: EnterpriseModStack | null,
  entitledModIds?: Iterable<string>,
): WorkflowEmployeeRegistryEntry[] {
  const host = stack ? defaultHostModIdForMarketEmployee(stack) : ''
  if (!stack || !host) return []
  const entitled = new Set(Array.from(entitledModIds || []).map((id) => String(id || '').trim()).filter(Boolean))
  const harvested: WorkflowEmployeeRegistryEntry[] = []
  for (const mod of mods || []) {
    const packId = String(mod.id || '').trim()
    if (!isCustomPhaseEmployeeCarrierModId(packId)) continue
    if (entitled.size && !entitlementMatchesMod(packId, entitled) && !modBelongsToEnterpriseStack(packId, stack)) continue
    for (const item of Array.isArray(mod.workflow_employees) ? mod.workflow_employees : []) {
      const record = item && typeof item === 'object' ? item as { id?: string; label?: string; host_mod_id?: string; enterprise_mod_id?: string } : {}
      const id = String(record.id || '').trim()
      if (!id || harvested.some((entry) => entry.id === id)) continue
      const explicit = String(record.host_mod_id || record.enterprise_mod_id || '').trim()
      harvested.push({ id, label: String(record.label || '').trim() || id, kind: 'mod_extension', order: 100 + harvested.length, source: 'mod_manifest', carrierModId: packId, hostModId: explicit && modBelongsToEnterpriseStack(explicit, stack) ? explicit : host })
    }
  }
  return harvested
}

export function filterWorkflowRegistryEntriesForEnterpriseStack(
  entries: WorkflowEmployeeRegistryEntry[],
  stack: EnterpriseModStack | null,
): WorkflowEmployeeRegistryEntry[] {
  return entries.filter((entry) => workflowRegistryEntryBelongsToStack(entry, stack))
}

/** 注册表合并源：仅当前企业 Mod 栈相关 manifest（行业包/定制/基础线/工作流载体） */
export function workflowHostVisibleOnPanorama(
  hostModId: string | undefined | null,
  stack: EnterpriseModStack | null,
  entitledModIds?: Iterable<string>,
): boolean {
  const host = String(hostModId || '').trim()
  if (!host || isCustomPhaseEmployeeCarrierModId(host)) return false
  const entitled = new Set(entitledModIds || [])
  if (entitled.size && entitlementMatchesMod(host, entitled)) return true
  if (stack) return modBelongsToEnterpriseStack(host, stack)
  return isWorkflowCarrierModId(host) || isHostBridgeModId(host)
}

export function filterModsForEnterpriseWorkflowRegistry(
  mods: ModWithWorkflowEmployees[] | undefined,
  stack: EnterpriseModStack | null,
  entitledModIds?: Iterable<string>,
): ModWithWorkflowEmployees[] {
  const list = mods || []
  const entitled = new Set(entitledModIds || [])
  if (!stack && !entitled.size) return filterWorkflowRegistrySourceMods(list)

  const stackModIds = new Set([...(stack?.packageModIds || []), ...(stack?.hostLineModIds || [])])
  return list.filter((m) => {
    const id = String(m.id || '').trim()
    if (!id) return false
    const wf = m.workflow_employees || []
    if (!Array.isArray(wf) || !wf.length) return false
    if (isEmployeePackModEntry(m) || isCustomPhaseEmployeeCarrierModId(id)) return false
    if (entitled.size && entitlementMatchesMod(id, entitled)) return true
    if (!stack) return false
    if (stackModIds.has(id)) return true
    return modBelongsToEnterpriseStack(id, stack)
  })
}
