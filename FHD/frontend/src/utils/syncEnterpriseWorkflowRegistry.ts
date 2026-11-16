import type { EnterpriseModStack } from '@/constants/enterpriseModStack'
import { fetchEmployeeDirectory } from '@/api/employeeDirectory'
import { useModsStore } from '@/stores/mods'
import { useWorkflowAiEmployeesStore } from '@/stores/workflowAiEmployees'
import { resolveEnterpriseModStack } from '@/utils/enterpriseModStackApi'
import type { ModWithWorkflowEmployees } from '@/utils/modWorkflowEmployees'
import { harvestOfficialCarrierEmployeesForStack } from '@/utils/workflowEmployeeScope'

/** 统一员工目录 → 注册表源形态（每个员工包一行工位）。 */
export function directoryToWorkflowMods(
  rows: Array<{ pack_id: string; label: string; prompt_only?: boolean }>,
): ModWithWorkflowEmployees[] {
  return rows
    .filter((row) => String(row.pack_id || '').trim())
    .map((row) => {
      const packId = String(row.pack_id).trim()
      return {
        id: packId,
        directory_sourced: true,
        workflow_employees: [
          { id: packId, label: String(row.label || packId), prompt_only: row.prompt_only === true },
        ],
      }
    })
}

/**
 * 员工注册表来源统一为后端员工目录（智能对话同源），
 * 不再从 /api/mods 的 workflow_employees 按行业栈/授权二次筛选。
 */
export async function syncEnterpriseWorkflowRegistry(options?: {
  forceStack?: boolean
  forceDirectory?: boolean
}): Promise<EnterpriseModStack> {
  const stack = await resolveEnterpriseModStack(Boolean(options?.forceStack))
  let scopedMods: ModWithWorkflowEmployees[] = []
  try {
    scopedMods = directoryToWorkflowMods(
      await fetchEmployeeDirectory({ force: options?.forceDirectory }),
    )
  } catch (e) {
    console.warn('[workflowEmployeeRegistry] employee-directory failed:', e)
  }
  const modsStore = useModsStore()
  const harvested = harvestOfficialCarrierEmployeesForStack(
    modsStore.modsForWorkflowUi,
    stack,
    modsStore.entitledModIds,
  )
  const wfStore = useWorkflowAiEmployeesStore()
  wfStore.hydrateFromMods(scopedMods)
  wfStore.pruneOrphanWorkflowEmployeeToggles(scopedMods)
  await wfStore.loadRegistry(scopedMods)
  harvested.forEach((entry) => wfStore.registerEmployee(entry))
  wfStore.ensureEnabledKeys()
  return stack
}
