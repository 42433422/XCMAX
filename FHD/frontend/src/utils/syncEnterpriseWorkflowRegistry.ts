import type { EnterpriseModStack } from '@/constants/enterpriseModStack'
import { fetchEmployeeDirectory } from '@/api/employeeDirectory'
import { useWorkflowAiEmployeesStore } from '@/stores/workflowAiEmployees'
import { resolveEnterpriseModStack } from '@/utils/enterpriseModStackApi'
import type { ModWithWorkflowEmployees } from '@/utils/modWorkflowEmployees'

/** 统一员工目录 → 注册表源形态（每个员工包一行工位）。 */
export function directoryToWorkflowMods(
  rows: Array<{ pack_id: string; label: string }>,
): ModWithWorkflowEmployees[] {
  return rows
    .filter((row) => String(row.pack_id || '').trim())
    .map((row) => {
      const packId = String(row.pack_id).trim()
      return {
        id: packId,
        directory_sourced: true,
        workflow_employees: [{ id: packId, label: String(row.label || packId) }],
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
  const wfStore = useWorkflowAiEmployeesStore()
  wfStore.hydrateFromMods(scopedMods)
  wfStore.pruneOrphanWorkflowEmployeeToggles(scopedMods)
  await wfStore.loadRegistry(scopedMods)
  return stack
}
