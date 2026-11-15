import type { EnterpriseModStack } from '@/constants/enterpriseModStack'
import { useModsStore } from '@/stores/mods'
import { useWorkflowAiEmployeesStore } from '@/stores/workflowAiEmployees'
import { resolveEnterpriseModStack } from '@/utils/enterpriseModStackApi'
import {
  filterModsForEnterpriseWorkflowRegistry,
  harvestOfficialCarrierEmployeesForStack,
} from '@/utils/workflowEmployeeScope'
import type { ModWithWorkflowEmployees } from '@/utils/modWorkflowEmployees'

/** 按企业 Mod 栈合并工作流员工注册表（避免磁盘上 workshop 员工包串入副窗/员工空间） */
export async function syncEnterpriseWorkflowRegistry(
  mods: ModWithWorkflowEmployees[],
  options?: { forceStack?: boolean },
): Promise<EnterpriseModStack> {
  const stack = await resolveEnterpriseModStack(Boolean(options?.forceStack))
  const entitled = useModsStore().entitledModIds
  const scopedMods = filterModsForEnterpriseWorkflowRegistry(mods, stack, entitled)
  const harvested = harvestOfficialCarrierEmployeesForStack(mods, stack, entitled)
  const wfStore = useWorkflowAiEmployeesStore()
  wfStore.hydrateFromMods(scopedMods)
  wfStore.pruneOrphanWorkflowEmployeeToggles(scopedMods)
  await wfStore.loadRegistry(scopedMods)
  for (const entry of harvested) {
    wfStore.registerEmployee(entry)
  }
  wfStore.ensureEnabledKeys()
  return stack
}
