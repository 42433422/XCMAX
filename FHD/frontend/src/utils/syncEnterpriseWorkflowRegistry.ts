import type { EnterpriseModStack } from '@/constants/enterpriseModStack'
import { employeeDirectoryScope, fetchEmployeeDirectory } from '@/api/employeeDirectory'
import { useModsStore } from '@/stores/mods'
import { useWorkflowAiEmployeesStore } from '@/stores/workflowAiEmployees'
import { resolveEnterpriseModStack } from '@/utils/enterpriseModStackApi'
import type { ModWithWorkflowEmployees } from '@/utils/modWorkflowEmployees'
import { harvestOfficialCarrierEmployeesForStack } from '@/utils/workflowEmployeeScope'

let requestGeneration = 0
let pending: { scope: string; promise: Promise<EnterpriseModStack> } | null = null

/** 统一员工目录 → 注册表源形态（每个员工包一行工位）。 */
export function directoryToWorkflowMods(
  rows: Array<{ pack_id: string; label: string; prompt_only?: boolean; enterprise_layer?: string }>,
): ModWithWorkflowEmployees[] {
  return rows
    .filter((row) => String(row.pack_id || '').trim())
    .map((row) => {
      const packId = String(row.pack_id).trim()
      return {
        id: packId,
        directory_sourced: true,
        workflow_employees: [
          { id: packId, label: String(row.label || packId), prompt_only: row.prompt_only === true,
            ...(row.enterprise_layer ? { enterprise_layer: row.enterprise_layer } : {}) },
        ],
      }
    })
}

/**
 * 员工注册表来源统一为后端员工目录（智能对话同源），
 * 不再从 /api/mods 的 workflow_employees 按行业栈/授权二次筛选。
 */
type RegistrySyncOptions = {
  forceStack?: boolean
  forceDirectory?: boolean
}

export async function syncEnterpriseWorkflowRegistry(options?: RegistrySyncOptions): Promise<EnterpriseModStack> {
  const scope = employeeDirectoryScope()
  if (pending?.scope === scope) return pending.promise
  const promise = synchronizeRegistry(options)
  pending = { scope, promise }
  try { return await promise } finally { if (pending?.promise === promise) pending = null }
}

async function synchronizeRegistry(options?: RegistrySyncOptions): Promise<EnterpriseModStack> {
  const scope = employeeDirectoryScope()
  const generation = ++requestGeneration
  const isCurrent = () => scope === employeeDirectoryScope() && generation === requestGeneration
  const stack = await resolveEnterpriseModStack(Boolean(options?.forceStack))
  if (!isCurrent()) throw new Error('员工目录上下文已变更，请重试')
  const scopedMods = directoryToWorkflowMods(await fetchEmployeeDirectory({ force: options?.forceDirectory }))
  if (!isCurrent()) throw new Error('员工目录上下文已变更，请重试')
  const modsStore = useModsStore()
  const harvested = harvestOfficialCarrierEmployeesForStack(
    modsStore.modsForWorkflowUi,
    stack,
    modsStore.entitledModIds,
  )
  const wfStore = useWorkflowAiEmployeesStore()
  wfStore.hydrateFromMods(scopedMods)
  wfStore.pruneOrphanWorkflowEmployeeToggles(scopedMods)
  await wfStore.loadRegistry(scopedMods, isCurrent)
  if (!isCurrent()) throw new Error('员工目录上下文已变更，请重试')
  harvested.forEach((entry) => wfStore.registerEmployee(entry))
  wfStore.ensureEnabledKeys()
  return stack
}
