import type { EnterpriseModStack } from '@/constants/enterpriseModStack'
import { useWorkflowAiEmployeesStore } from '@/stores/workflowAiEmployees'
import { resolveEnterpriseModStack } from '@/utils/enterpriseModStackApi'
import { filterModsForEnterpriseWorkflowRegistry } from '@/utils/workflowEmployeeScope'
import type { ModWithWorkflowEmployees } from '@/utils/modWorkflowEmployees'

/** 按企业 Mod 栈合并工作流员工注册表（避免磁盘上 workshop 员工包串入副窗/员工空间） */
export async function syncEnterpriseWorkflowRegistry(
  mods: ModWithWorkflowEmployees[],
  options?: { forceStack?: boolean },
): Promise<EnterpriseModStack> {
  const stack = await resolveEnterpriseModStack(Boolean(options?.forceStack))
  const scopedMods = filterModsForEnterpriseWorkflowRegistry(mods, stack)
  const wfStore = useWorkflowAiEmployeesStore()
  wfStore.hydrateFromMods(scopedMods)
  wfStore.pruneOrphanWorkflowEmployeeToggles(scopedMods)
  await wfStore.loadRegistry(scopedMods)
  return stack
}
