import { onMounted, ref, watch } from 'vue'
import { useModsStore } from '@/stores/mods'
import { useWorkflowAiEmployeesStore } from '@/stores/workflowAiEmployees'
import { employeeDirectoryScope } from '@/api/employeeDirectory'
import { syncEnterpriseWorkflowRegistry } from '@/utils/syncEnterpriseWorkflowRegistry'

/** 员工可视化 / 副窗 / 流程可视化：与统一员工目录同步注册表 */
export function useWorkflowEmployeeRegistrySync() {
  const modsStore = useModsStore()
  const error = ref('')
  let requestGeneration = 0

  function reportSyncError(reason: unknown) {
    error.value = reason instanceof Error ? reason.message : '员工目录同步失败，请重试'
  }

  async function syncRegistry() {
    if (modsStore.clientModsUiOff) return
    const scope = employeeDirectoryScope()
    const generation = ++requestGeneration
    try {
      await modsStore.initialize(true)
      if (scope !== employeeDirectoryScope() || generation !== requestGeneration) return
      await syncEnterpriseWorkflowRegistry({ forceDirectory: true })
      if (scope === employeeDirectoryScope() && generation === requestGeneration) error.value = ''
    } catch (reason) {
      if (scope === employeeDirectoryScope() && generation === requestGeneration) reportSyncError(reason)
    }
  }

  onMounted(syncRegistry)

  // 装/卸 Mod 后重拉目录；目录接口自身是唯一员工来源，不再依赖 Mod 清单。
  watch(
    () => [employeeDirectoryScope(), modsStore.activeModId, modsStore.modsForWorkflowUi, modsStore.entitledModIds],
    (current, previous) => {
      if (current[0] !== previous?.[0]) {
        useWorkflowAiEmployeesStore().registryEntries = []
        error.value = ''
      }
      if (modsStore.clientModsUiOff) return
      const scope = employeeDirectoryScope()
      const generation = ++requestGeneration
      void syncEnterpriseWorkflowRegistry({ forceDirectory: true }).then(() => {
        if (scope === employeeDirectoryScope() && generation === requestGeneration) error.value = ''
      }).catch(reason => {
        if (scope === employeeDirectoryScope() && generation === requestGeneration) reportSyncError(reason)
      })
    },
    { deep: true },
  )

  return { syncRegistry, refresh: syncRegistry, error }
}
