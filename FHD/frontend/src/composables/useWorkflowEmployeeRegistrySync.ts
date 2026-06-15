import { onMounted, watch } from 'vue'
import { useModsStore } from '@/stores/mods'
import { syncEnterpriseWorkflowRegistry } from '@/utils/syncEnterpriseWorkflowRegistry'

/** 员工可视化 / 副窗 / 流程全景：与 Mod 列表同步工作流员工注册表 */
export function useWorkflowEmployeeRegistrySync() {
  const modsStore = useModsStore()

  async function syncRegistry() {
    if (modsStore.clientModsUiOff) return
    await modsStore.initialize(true)
    await syncEnterpriseWorkflowRegistry(modsStore.modsForWorkflowUi)
  }

  onMounted(syncRegistry)

  watch(
    () => modsStore.modsForWorkflowUi,
    (list) => {
      if (modsStore.clientModsUiOff) return
      void syncEnterpriseWorkflowRegistry(list)
    },
    { deep: true },
  )

  return { syncRegistry }
}
