import { onMounted, watch } from 'vue'
import { useModsStore } from '@/stores/mods'
import { syncEnterpriseWorkflowRegistry } from '@/utils/syncEnterpriseWorkflowRegistry'

/** 员工可视化 / 副窗 / 流程可视化：与统一员工目录同步注册表 */
export function useWorkflowEmployeeRegistrySync() {
  const modsStore = useModsStore()

  function reportSyncError(error: unknown) {
    console.warn('[workflowEmployeeRegistry] sync failed:', error)
  }

  async function syncRegistry() {
    if (modsStore.clientModsUiOff) return
    try {
      await modsStore.initialize(true)
      await syncEnterpriseWorkflowRegistry({ forceDirectory: true })
    } catch (error) {
      reportSyncError(error)
    }
  }

  onMounted(syncRegistry)

  // 装/卸 Mod 后重拉目录；目录接口自身是唯一员工来源，不再依赖 Mod 清单。
  watch(
    () => [modsStore.modsForWorkflowUi, modsStore.entitledModIds],
    () => {
      if (modsStore.clientModsUiOff) return
      void syncEnterpriseWorkflowRegistry({ forceDirectory: true }).catch(reportSyncError)
    },
    { deep: true },
  )

  return { syncRegistry }
}
