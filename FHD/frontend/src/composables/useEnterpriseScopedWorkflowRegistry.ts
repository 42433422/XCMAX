import { computed, onMounted, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useWorkflowAiEmployeesStore } from '@/stores/workflowAiEmployees'
import type { EnterpriseModStack } from '@/constants/enterpriseModStack'
import { filterWorkflowRegistryEntriesForEnterpriseStack } from '@/utils/workflowEmployeeScope'
import { resolveEnterpriseModStack } from '@/utils/enterpriseModStackApi'

/** 按企业 Mod 栈过滤工作流员工注册表（副窗一键托管等） */
export function useEnterpriseScopedWorkflowRegistry() {
  const workflowAiEmployeesStore = useWorkflowAiEmployeesStore()
  const { registryEntries } = storeToRefs(workflowAiEmployeesStore)
  const enterpriseStack = ref<EnterpriseModStack | null>(null)

  onMounted(() => {
    void resolveEnterpriseModStack().then((stack) => {
      enterpriseStack.value = stack
    })
  })

  const scopedRegistryEntries = computed(() =>
    filterWorkflowRegistryEntriesForEnterpriseStack(registryEntries.value, enterpriseStack.value),
  )

  return { enterpriseStack, scopedRegistryEntries }
}
