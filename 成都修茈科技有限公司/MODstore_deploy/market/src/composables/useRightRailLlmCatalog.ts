import { computed, ref, watch, type ComputedRef, type WritableComputedRef } from 'vue'
import { api } from '../api'
import {
  categoryLabel,
  modelOptionLabel,
  modelsForCategory,
  type LlmProviderBlock,
} from './llmCatalogModelHelpers'
import { AUTO_EMPLOYEE_LLM_SENTINEL } from '../domain/llm/defaultEmployeeLlm'
import type { EmployeeNodeData } from './useWorkbenchManifest'

/** RightRail 模型目录域：/api/llm/catalog 拉取、厂商/模型选择行与联动 watch（自 RightRail.vue 原样迁移） */
export function useRightRailLlmCatalog(deps: {
  modelProvider: WritableComputedRef<string>
  modelName: WritableComputedRef<string>
  selectedNodeData: ComputedRef<EmployeeNodeData | null>
}) {
  const { modelProvider, modelName, selectedNodeData } = deps

  /** 与钱包页「大模型 API」同源：`GET /api/llm/catalog` */
  const llmCatalog = ref<Record<string, unknown> | null>(null)
  const llmCatalogLoading = ref(false)

  const employeeProviderBlock = computed((): LlmProviderBlock | null => {
    const c = llmCatalog.value as { providers?: LlmProviderBlock[] } | undefined
    const provs = c?.providers
    if (!provs?.length) return null
    return provs.find((p) => p.provider === modelProvider.value) ?? null
  })

  /** 文案与模板首项 `<option>` 共用；`auto` 必须在 DOM 中固定在第一条，避免仅靠计算数组排序被缓存/旧包省略 */
  const AUTO_LLM_ROW = {
    provider: AUTO_EMPLOYEE_LLM_SENTINEL,
    label: '自动（跟随账户可用密钥）',
  } as const

  /** 目录里的厂商（不含 auto；auto 由模板静态首项渲染） */
  const catalogProviderPickerRows = computed(() => {
    const c = llmCatalog.value as { providers?: LlmProviderBlock[] } | undefined
    const cur = modelProvider.value
    const skipAuto = (pid: string) => pid !== AUTO_EMPLOYEE_LLM_SENTINEL

    if (c?.providers?.length) {
      let rows = c.providers
        .filter((p) => skipAuto(String(p.provider ?? '').trim()))
        .map((p) => ({
          provider: p.provider,
          label: p.label || p.provider,
        }))
      if (cur && cur !== AUTO_EMPLOYEE_LLM_SENTINEL && !rows.some((r) => r.provider === cur)) {
        rows = [{ provider: cur, label: `${cur}（当前 manifest）` }, ...rows]
      }
      return rows
    }
    const fb = [
      { provider: 'deepseek', label: 'DeepSeek' },
      { provider: 'openai', label: 'OpenAI' },
      { provider: 'anthropic', label: 'Anthropic' },
      { provider: 'local', label: 'Local' },
    ]
    if (cur && cur !== AUTO_EMPLOYEE_LLM_SENTINEL && !fb.some((r) => r.provider === cur)) {
      return [{ provider: cur, label: `${cur}（当前 manifest）` }, ...fb]
    }
    return fb
  })

  const employeeHasStructuredModels = computed(() => {
    const b = employeeProviderBlock.value
    if (!b) return false
    if (b.models_detailed?.length) return true
    return !!(b.models?.length)
  })

  function employeeCategoryLabel(cat: string) {
    return categoryLabel(llmCatalog.value, cat)
  }

  function employeeModelsForCategory(cat: string) {
    return modelsForCategory(employeeProviderBlock.value, cat)
  }

  function employeeModelOptionLabel(row: { id: string; capability?: Record<string, unknown> }) {
    return modelOptionLabel(row)
  }

  function syncEmployeeModelAfterCatalog() {
    if (modelProvider.value === AUTO_EMPLOYEE_LLM_SENTINEL) return
    const block = employeeProviderBlock.value
    const models = block?.models || []
    if (!models.length) return
    if (!modelName.value || !models.includes(modelName.value)) {
      modelName.value = models[0] || ''
    }
  }

  function onEmployeeLlmProviderPicked() {
    if (modelProvider.value === AUTO_EMPLOYEE_LLM_SENTINEL) {
      modelName.value = AUTO_EMPLOYEE_LLM_SENTINEL
      return
    }
    syncEmployeeModelAfterCatalog()
  }

  async function loadWorkbenchLlmCatalog(manualRefresh: boolean) {
    if (!localStorage.getItem('modstore_token')) return
    llmCatalogLoading.value = true
    try {
      llmCatalog.value = (await api.llmCatalog(manualRefresh)) as Record<string, unknown>
      syncEmployeeModelAfterCatalog()
    } catch {
      // 保留本地回退厂商列表，不阻断编辑
    } finally {
      llmCatalogLoading.value = false
    }
  }

  async function refreshWorkbenchLlmCatalog() {
    await loadWorkbenchLlmCatalog(true)
  }

  const hasAuthToken = computed(
    () => typeof localStorage !== 'undefined' && !!localStorage.getItem('modstore_token'),
  )

  watch(
    () => selectedNodeData.value?.moduleKind,
    (kind) => {
      if (kind === 'prompt') void loadWorkbenchLlmCatalog(false)
    },
    { immediate: true },
  )

  watch(llmCatalog, (c) => {
    if (c) syncEmployeeModelAfterCatalog()
  })

  watch(
    () => modelProvider.value,
    (p) => {
      if (p === AUTO_EMPLOYEE_LLM_SENTINEL && modelName.value !== AUTO_EMPLOYEE_LLM_SENTINEL) {
        modelName.value = AUTO_EMPLOYEE_LLM_SENTINEL
      }
    },
    { immediate: true },
  )

  return {
    llmCatalog,
    llmCatalogLoading,
    AUTO_LLM_ROW,
    catalogProviderPickerRows,
    employeeHasStructuredModels,
    employeeCategoryLabel,
    employeeModelsForCategory,
    employeeModelOptionLabel,
    onEmployeeLlmProviderPicked,
    loadWorkbenchLlmCatalog,
    refreshWorkbenchLlmCatalog,
    hasAuthToken,
  }
}

export type RightRailLlmCatalogApi = ReturnType<typeof useRightRailLlmCatalog>
