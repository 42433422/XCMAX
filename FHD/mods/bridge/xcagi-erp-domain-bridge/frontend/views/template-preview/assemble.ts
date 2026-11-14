import { computed, onActivated, onBeforeUnmount, onDeactivated, onMounted, watch } from 'vue'
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
  getTemplateCategoryIcon,
  getTemplateCategoryLabel,
  getTemplateCoverage,
  getTemplateDisplayTermsText,
  getTemplateFields,
  getTemplateGridData,
  getTemplateSampleRows,
  getTemplateScopeKey,
  getTemplateScopeLabel,
  getTemplateSourceLabel,
  getTemplateTypeLabel,
  isGridTemplateCategory,
} from './tpTemplateMeta'

/** 全局搜索向模板库交接关键词的 sessionStorage 键（顶部搜索框与模板库共用）。 */
export const TEMPLATE_SEARCH_STORAGE_KEY = 'xcagi_template_search_keyword'

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

  watch(
    () => route.query.keyword,
    (keyword) => list.applyRouteKeyword(keyword),
    { immediate: true }
  )

  /** 顶部全局搜索跳转时通过 sessionStorage 交接关键词，避免依赖挂载时序。 */
  function consumeGlobalSearchHandoff() {
    try {
      const keyword = sessionStorage.getItem(TEMPLATE_SEARCH_STORAGE_KEY) || ''
      if (!keyword) return
      sessionStorage.removeItem(TEMPLATE_SEARCH_STORAGE_KEY)
      list.applyRouteKeyword(keyword)
    } catch {
      /* 无 sessionStorage（隐私模式等）时忽略 */
    }
  }

  /** 已在模板库页面时不会重新挂载，改由事件即时应用关键词。 */
  function onGlobalSearchEvent(event: Event) {
    const keyword = String((event as CustomEvent<{ keyword?: string }>).detail?.keyword || '').trim()
    if (keyword) list.applyRouteKeyword(keyword)
    try {
      sessionStorage.removeItem(TEMPLATE_SEARCH_STORAGE_KEY)
    } catch {
      /* 忽略 */
    }
  }

  onMounted(() => {
    active = true
    consumeGlobalSearchHandoff()
    window.addEventListener('xcagi:template-search', onGlobalSearchEvent)
    window.addEventListener('xcagi:templates-updated', templatesUpdated)
    void list.refreshTemplates()
  })

  let active = false
  let dirty = false
  function templatesUpdated() {
    if (active) void list.refreshTemplates()
    else dirty = true
  }
  onActivated(() => {
    active = true
    if (dirty) { dirty = false; void list.refreshTemplates() }
  })
  onDeactivated(() => { active = false })

  onBeforeUnmount(() => {
    window.removeEventListener('xcagi:template-search', onGlobalSearchEvent)
    window.removeEventListener('xcagi:templates-updated', templatesUpdated)
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
    getTemplateCategoryLabel,
    getTemplateCategoryIcon,
    isGridTemplateCategory,
    getTemplateDisplayTermsText,
    getMatchedScopeLabels,
    getTemplateCoverage,
    canPreviewVirtualTemplate,
    canDeleteTemplate,
  }
}

export type TemplatePreviewCtx = ReturnType<typeof assembleTemplatePreview>
