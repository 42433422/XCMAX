import { onMounted, watch } from 'vue'
import { useModsStore } from '@/stores/mods'
import { useWorkflowAiEmployeesStore } from '@/stores/workflowAiEmployees'

/** 员工可视化 / 副窗 / 流程全景：与 Mod 列表同步工作流员工注册表 */
export function useWorkflowEmployeeRegistrySync() {
  const modsStore = useModsStore()
  const workflowAiEmployeesStore = useWorkflowAiEmployeesStore()

  async function syncRegistry() {
    if (modsStore.clientModsUiOff) return
    await modsStore.initialize(true)
    workflowAiEmployeesStore.hydrateFromMods(modsStore.modsForWorkflowUi)
    workflowAiEmployeesStore.pruneOrphanWorkflowEmployeeToggles(modsStore.modsForWorkflowUi)
    await workflowAiEmployeesStore.loadRegistry(modsStore.modsForWorkflowUi)
  }

  onMounted(syncRegistry)

  watch(
    () => modsStore.modsForWorkflowUi,
    (list) => {
      if (modsStore.clientModsUiOff) return
      workflowAiEmployeesStore.hydrateFromMods(list)
      workflowAiEmployeesStore.pruneOrphanWorkflowEmployeeToggles(list)
      if (!workflowAiEmployeesStore.registryLoaded) {
        workflowAiEmployeesStore.loadRegistry(list)
      }
    },
    { deep: true },
  )

  return { syncRegistry }
}
