import { computed, ref } from 'vue'
import templatePreviewApi from '@/api/templatePreview'
import { TEMPLATE_SCOPE_CONFIG } from './tpScopeRules'
import { createVirtualTemplate, getTemplateScopeKey, isExportTemplate } from './tpTemplateMeta'
import type { TplRecord } from './tpTemplateMeta'
import type { TplDecomposeResponse, TplDetailResponse, TplListResponse } from './tpApiContracts'

/** 兼容旧 lib.dom：AbortSignal.timeout 为较新 API，运行时探测可用性 */
type AbortSignalConstructorWithTimeout = typeof AbortSignal & {
  timeout?: (ms: number) => AbortSignal
}

/** 模板列表加载 + 业务范围过滤（对应原视图 data 的 templates/loading/error/activeScopeTab 与相关方法） */
export function useTpTemplateList() {
  const templates = ref<TplRecord[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)
  const activeScopeTab = ref('all')
  /** 用于忽略过期的后台词条补全（快速连续点「刷新」时） */
  let templateListRefreshGen = 0

  const exportScopedTemplates = computed<TplRecord[]>(() => {
    const realTemplates = Array.isArray(templates.value) ? templates.value.filter(t => isExportTemplate(t)) : []
    const scopedExcelTemplates = realTemplates.filter(t => t.category === 'excel')
    const existingScopes = new Set(
      scopedExcelTemplates
        .map(t => getTemplateScopeKey(t))
        .filter(Boolean)
    )

    for (const scopeKey of Object.keys(TEMPLATE_SCOPE_CONFIG)) {
      if (scopeKey === 'custom') continue
      if (!existingScopes.has(scopeKey)) {
        realTemplates.push(createVirtualTemplate(scopeKey))
      }
    }
    return realTemplates
  })

  const filteredTemplates = computed<TplRecord[]>(() => {
    if (activeScopeTab.value === 'all') return exportScopedTemplates.value
    const tab = activeScopeTab.value
    return exportScopedTemplates.value.filter((t) => {
      const scopeKey = getTemplateScopeKey(t)
      if (t.category === 'word' && !scopeKey) {
        // 未配置 business_scope 且无法推断：与「全部」一致，在各业务分组中均可看到
        return true
      }
      return scopeKey === tab
    })
  })

  function applyRouteScope(routeScopeRaw: unknown) {
    const queryScope = String(routeScopeRaw || '').trim()
    if (queryScope && Object.prototype.hasOwnProperty.call(TEMPLATE_SCOPE_CONFIG, queryScope)) {
      activeScopeTab.value = queryScope
    } else if (!activeScopeTab.value) {
      activeScopeTab.value = 'all'
    }
  }

  async function refreshTemplates() {
    loading.value = true
    error.value = null
    const refreshGen = ++templateListRefreshGen
    const listSignal =
      typeof AbortSignal !== 'undefined' && typeof (AbortSignal as AbortSignalConstructorWithTimeout).timeout === 'function'
        ? (AbortSignal as AbortSignalConstructorWithTimeout).timeout(120000)
        : undefined
    try {
      const res = (await templatePreviewApi.listTemplates(listSignal ? { signal: listSignal } : undefined)) as TplListResponse
      if (refreshGen !== templateListRefreshGen) return
      if (res && res.success) {
        const list = (res.templates || []).filter((t: TplRecord) => {
          // 兼容后端旧版本：前端主动隐藏已软删除模板。
          return !(t && (t.is_active === 0 || t.is_active === false))
        })

        templates.value = list
        // 列表已就绪即结束全页 loading；词条/分解在后台补全（避免 detail/decompose 慢或挂起导致一直「模板加载中」）
        loading.value = false
        void hydrateExcelTemplatesInBackground(refreshGen)
      } else {
        error.value = (res && res.message) || '加载失败'
      }
    } catch (err) {
      console.error('加载模板列表失败:', err)
      const errRec = (err && typeof err === 'object' ? err : {}) as { name?: unknown; message?: unknown }
      const msg = errRec.name === 'TimeoutError'
        ? '请求超时，请检查网络或后端服务'
        : (typeof errRec.message === 'string' && errRec.message) || '未知错误'
      error.value = '加载模板列表失败：' + msg
    } finally {
      loading.value = false
    }
  }

  async function hydrateExcelTemplatesInBackground(refreshGen: number) {
    const list = Array.isArray(templates.value) ? templates.value : []
    for (const tpl of list) {
      if (refreshGen !== templateListRefreshGen) return
      if (tpl.category === 'excel' && !tpl.virtual) {
        try {
          await hydrateTemplateTerms(tpl)
        } catch (e) {
          console.warn('后台补全模板词条失败:', e)
        }
      }
    }
  }

  async function hydrateTemplateTerms(tpl: TplRecord) {
    if (String(tpl?.source || '').trim() === 'system-default' && Array.isArray(tpl?.fields) && tpl.fields.length > 0) {
      return
    }
    let hydratedByDetail = false
    try {
      const detailRes = (await templatePreviewApi.getTemplateDetail(tpl.id)) as TplDetailResponse
      if (detailRes && detailRes.success && detailRes.template) {
        Object.assign(tpl, detailRes.template)
        hydratedByDetail = true
      }
    } catch (e) {
      console.warn(`获取模板 ${tpl.id} 详情失败:`, e)
    }

    const hasFields = Array.isArray(tpl.fields) && tpl.fields.length > 0
    if (hydratedByDetail && hasFields) return

    // 兜底：按“真实模板文件”分解，确保每个模板都按实际内容匹配。
    try {
      const filePath = String(tpl.file_path || tpl.path || '').trim()
      const fileName = String(tpl.filename || '').trim()
      if (!filePath && !fileName) return

      const decomposePayload: Record<string, unknown> = {
        sample_rows: 8
      }
      if (filePath) {
        decomposePayload.file_path = filePath
      } else {
        decomposePayload.filename = fileName
      }

      const decomposeRes = (await templatePreviewApi.decomposeTemplate(decomposePayload)) as TplDecomposeResponse
      if (!decomposeRes?.success) return

      const decomposition = decomposeRes?.decomposition
      const entries = Array.isArray(decomposition?.editable_entries) ? decomposition.editable_entries : []
      const sampleRows = Array.isArray(decomposition?.sample_rows) ? decomposition.sample_rows : []

      let fields = entries
        .map((item) => {
          const rec = (item && typeof item === 'object' ? item : {}) as { name?: unknown }
          return {
            label: String(rec.name || '').trim(),
            value: '',
            type: 'dynamic'
          }
        })
        .filter((item) => item.label)

      if (!fields.length && sampleRows.length) {
        const keys = Array.from(
          new Set(
            sampleRows.flatMap((row) => Object.keys(row || {}))
          )
        )
        fields = keys.map(k => ({ label: String(k || '').trim(), value: '', type: 'dynamic' })).filter(f => f.label)
      }

      if (fields.length) {
        tpl.fields = fields
      }

      tpl.preview_data = {
        ...(tpl.preview_data || {}),
        sample_rows: sampleRows
      }
    } catch (e) {
      console.warn(`分解模板 ${tpl.id} 失败:`, e)
    }
  }

  return {
    templates,
    loading,
    error,
    activeScopeTab,
    exportScopedTemplates,
    filteredTemplates,
    applyRouteScope,
    refreshTemplates,
  }
}
