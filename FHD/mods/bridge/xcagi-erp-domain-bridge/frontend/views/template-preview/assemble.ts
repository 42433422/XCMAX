import { computed, onBeforeUnmount, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useTpTemplateList } from './useTpTemplateList'
import { useTpCreateFlow } from './useTpCreateFlow'
import { useTpTemplateActions } from './useTpTemplateActions'
import { useTpGridTool } from './useTpGridTool'
import { buildScopeOptions, buildScopeTabs, getRequiredTermsByScope, getScopeIconClass } from './tpScopeRules'
import {
  canDeleteTemplate,
  canPreviewVirtualTemplate,
  getExcelPreviewTitle,
  getMatchedScopeLabels,
  getTemplateCoverage,
  getTemplateDisplayTermsText,
  getTemplateFields,
  getTemplateGridData,
  getTemplateSampleRows,
  getTemplateScopeKey,
  getTemplateScopeLabel,
  getTemplateSourceLabel,
  getTemplateTypeLabel,
} from './tpTemplateMeta'

/**
 * 组装模板预览视图全部状态与动作；子组件通过单一 ctx prop 共享，
 * 模板自 TemplatePreviewView.vue 逐字迁移，行为不变。
 */
export function assembleTemplatePreview() {
  const route = useRoute()

  const list = useTpTemplateList()
  const create = useTpCreateFlow({ refreshTemplates: list.refreshTemplates })
  const actions = useTpTemplateActions({
    refreshTemplates: list.refreshTemplates,
    templates: list.templates,
    exportScopedTemplates: list.exportScopedTemplates,
  })
  const gridTool = useTpGridTool()

  const scopeTabs = computed(() => buildScopeTabs())
  const scopeOptions = computed(() => buildScopeOptions())

  watch(
    () => route.query.scope,
    (scope) => list.applyRouteScope(scope),
    { immediate: true }
  )

  onMounted(() => {
    void list.refreshTemplates()
  })

  onBeforeUnmount(() => {
    create.stopProgressTimer()
  })

  return {
    ...list,
    ...create,
    ...actions,
    ...gridTool,
    scopeTabs,
    scopeOptions,
    // 无状态纯函数直出，供子组件模板使用
    getRequiredTermsByScope,
    getScopeIconClass,
    getTemplateScopeKey,
    getTemplateScopeLabel,
    getTemplateSourceLabel,
    getTemplateFields,
    getTemplateSampleRows,
    getTemplateGridData,
    getExcelPreviewTitle,
    getTemplateTypeLabel,
    getTemplateDisplayTermsText,
    getMatchedScopeLabels,
    getTemplateCoverage,
    canPreviewVirtualTemplate,
    canDeleteTemplate,
  }
}

export type TemplatePreviewCtx = ReturnType<typeof assembleTemplatePreview>
