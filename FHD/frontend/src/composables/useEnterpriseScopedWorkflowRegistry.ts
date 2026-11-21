import { computed, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useWorkflowAiEmployeesStore } from '@/stores/workflowAiEmployees'
import type { EnterpriseModStack } from '@/constants/enterpriseModStack'
import { filterWorkflowRegistryEntriesForEnterpriseStack } from '@/utils/workflowEmployeeScope'
import { resolveEnterpriseModStack } from '@/utils/enterpriseModStackApi'
import { employeeDirectoryScope } from '@/api/employeeDirectory'
import { useModsStore } from '@/stores/mods'

/** 按企业 Mod 栈过滤工作流员工注册表（副窗一键托管等） */
export function useEnterpriseScopedWorkflowRegistry() {
  const workflowAiEmployeesStore = useWorkflowAiEmployeesStore()
  const { registryEntries } = storeToRefs(workflowAiEmployeesStore)
  const enterpriseStack = ref<EnterpriseModStack | null>(null)
  const modsStore = useModsStore()
  const error = ref('')
  let requestGeneration = 0

  async function refresh(force = false) {
    const scope = employeeDirectoryScope()
    const generation = ++requestGeneration
    const isCurrent = () => scope === employeeDirectoryScope() && generation === requestGeneration
    error.value = ''
    try {
      const stack = await resolveEnterpriseModStack(force)
      if (isCurrent()) enterpriseStack.value = stack
    } catch (reason) {
      if (isCurrent()) error.value = reason instanceof Error ? reason.message : '企业分区读取失败，请重试'
    }
  }

  watch(() => [employeeDirectoryScope(), modsStore.activeModId], (_scope, _old, onCleanup) => {
    onCleanup(() => { requestGeneration++ })
    enterpriseStack.value = null
    void refresh()
  }, { immediate: true, flush: 'sync' })

  const scopedRegistryEntries = computed(() =>
    filterWorkflowRegistryEntriesForEnterpriseStack(registryEntries.value, enterpriseStack.value),
  )

  return { enterpriseStack, scopedRegistryEntries, error, refresh: () => refresh(true) }
}
