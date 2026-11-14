import { ref } from 'vue'
import type { ComputedRef, Ref } from 'vue'
import { useRouter } from 'vue-router'
import templatePreviewApi from '@/api/templatePreview'
import { appAlert, appConfirm } from '@/utils/appDialog'
import { pushErpPage } from '@/utils/erpPagePaths'
import { buildTemplatePayloadFromExcelAnalysis, buildTemplatePayloadFromSourceTemplate } from './tpAnalysisPayload'
import { canDeleteTemplate, getMatchedScopeKeys, getTemplateFields, getTemplateTypeLabel } from './tpTemplateMeta'
import type { TplRecord } from './tpTemplateMeta'
import type { TplApiResponse } from './tpApiContracts'

export interface TpTemplateActionsDeps {
  refreshTemplates: () => void | Promise<void>
  templates: Ref<TplRecord[]>
  exportScopedTemplates: ComputedRef<TplRecord[]>
}

/** 查看 / 编辑 / 替代 / 删除等模板操作（对应原视图预览、编辑、替代、删除相关方法） */
export function useTpTemplateActions(deps: TpTemplateActionsDeps) {
  const router = useRouter()

  const showPreviewModal = ref(false)
  const previewingTemplate = ref<TplRecord | null>(null)
  const showEditModal = ref(false)
  const editingTemplate = ref<TplRecord | null>(null)
  const showReplaceModal = ref(false)
  const replaceSourceTemplate = ref<TplRecord | null>(null)
  const replaceTargetTemplateId = ref('')
  const replacingTemplate = ref(false)

  function previewTemplate(tpl: TplRecord) {
    previewingTemplate.value = tpl
    showPreviewModal.value = true
  }

  function closePreviewModal() {
    showPreviewModal.value = false
    previewingTemplate.value = null
  }

  async function openTemplateTarget(tpl: TplRecord) {
    if (tpl.category === 'label') {
      if (!String(tpl.id || '').trim()) {
        await appAlert('模板缺少标识，无法打开。请刷新模板列表后重试。')
        return
      }
      pushErpPage(router, { path: '/label-editor', query: { templateId: String(tpl.id) } })
    } else if (tpl.category === 'word') {
      const p = String(tpl.file_path || tpl.path || '').trim()
      await appAlert(p ? `请在资源管理器中打开：\n${p}` : '未记录 Word 模板文件路径')
    } else {
      const p = String(tpl.file_path || tpl.path || '').trim()
      await appAlert(
        p
          ? `Excel 模板文件路径（请在资源管理器中打开）：\n${p}`
          : '未记录 Excel 模板文件路径；可在「编辑」中核对元数据或重新上传分析。'
      )
    }
  }

  function editTemplate(tpl: TplRecord) {
    editingTemplate.value = { ...tpl }
    showEditModal.value = true
  }

  function closeEditModal() {
    showEditModal.value = false
    editingTemplate.value = null
  }

  async function openReplaceTemplateDialog(sourceTemplate: TplRecord) {
    const candidates = getReplaceCandidates(sourceTemplate)
    if (!candidates.length) {
      await appAlert('暂无同业务范围可替代模板')
      return
    }
    replaceSourceTemplate.value = sourceTemplate
    replaceTargetTemplateId.value = candidates[0].id
    showReplaceModal.value = true
  }

  function closeReplaceModal() {
    showReplaceModal.value = false
    replaceSourceTemplate.value = null
    replaceTargetTemplateId.value = ''
    replacingTemplate.value = false
  }

  function getReplaceCandidates(sourceTemplate: TplRecord): TplRecord[] {
    if (!sourceTemplate || sourceTemplate.category !== 'excel') return []
    const sourceScopes = getMatchedScopeKeys(sourceTemplate)
    if (!sourceScopes.length) return []
    return deps.exportScopedTemplates.value.filter((tpl) => {
      if (!tpl || tpl.virtual || tpl.category !== 'excel') return false
      if (String(tpl.id) === String(sourceTemplate.id)) return false
      if (!String(tpl.id || '').startsWith('db:')) return false
      const targetScopes = getMatchedScopeKeys(tpl)
      return targetScopes.some(scope => sourceScopes.includes(scope))
    })
  }

  async function confirmReplaceTemplate() {
    if (!replaceSourceTemplate.value || !replaceTargetTemplateId.value) return
    replacingTemplate.value = true
    try {
      // 优先使用“分析Excel”工具上下文；无上下文时对源模板执行同套去数据清洗逻辑。
      const excelAnalysisPayload = buildTemplatePayloadFromExcelAnalysis()
      const sourceSanitizedPayload = buildTemplatePayloadFromSourceTemplate(replaceSourceTemplate.value)
      const replacementPayload = excelAnalysisPayload || sourceSanitizedPayload
      const replacementFields = replacementPayload?.fields || getTemplateFields(replaceSourceTemplate.value, 'excel')
      const replacementPreviewData = replacementPayload?.preview_data || { ...(replaceSourceTemplate.value.preview_data || {}) }
      const sourceScopes = getMatchedScopeKeys(replaceSourceTemplate.value)
      const businessScope = sourceScopes[0] || replaceSourceTemplate.value.business_scope || ''
      const payload = {
        id: replaceTargetTemplateId.value,
        name: replaceSourceTemplate.value.name,
        template_type: replaceSourceTemplate.value.template_type || getTemplateTypeLabel(replaceSourceTemplate.value),
        business_scope: businessScope,
        fields: replacementFields,
        preview_data: replacementPreviewData,
        source: 'template-preview-replace',
        enforce_scope_match: true,
        replace_mode: true
      }
      const res = (await templatePreviewApi.replaceTemplateById(payload)) as TplApiResponse
      if (!res?.success) {
        throw new Error(res?.message || '替代失败')
      }
      if (replacementPayload) {
        await appAlert('模板替代成功（已执行模板/数据分离：去除数据，仅保留模板结构）')
      } else {
        await appAlert('模板替代成功')
      }
      closeReplaceModal()
      deps.refreshTemplates()
      window.dispatchEvent(new CustomEvent('xcagi:templates-updated', { detail: { source: 'template-replace' } }))
    } catch (err) {
      await appAlert('模板替代失败：' + (err instanceof Error ? (err.message || '未知错误') : String(err)))
    } finally {
      replacingTemplate.value = false
    }
  }

  async function saveTemplateEdit() {
    if (!editingTemplate.value) return

    try {
      const res = (await templatePreviewApi.updateTemplate({
        id: editingTemplate.value.id,
        name: editingTemplate.value.name,
        category: editingTemplate.value.category
      })) as TplApiResponse

      if (res && res.success) {
        await appAlert('更新成功！')
        closeEditModal()
        deps.refreshTemplates()
        window.dispatchEvent(new CustomEvent('xcagi:templates-updated', { detail: { source: 'template-edit' } }))
      } else {
        throw new Error((res && res.message) || '更新失败')
      }
    } catch (err) {
      await appAlert('更新失败：' + (err instanceof Error ? (err.message || '未知错误') : String(err)))
    }
  }

  function openLabelEditor() {
    pushErpPage(router, {
      path: '/label-editor',
      query: {
        mode: 'create',
        autoUpload: '1'
      }
    })
  }

  async function confirmDeleteTemplate(tpl: TplRecord) {
    if (!canDeleteTemplate(tpl)) {
      await appAlert('当前模板不支持删除');
      return;
    }
    if (await appConfirm(`确定要删除模板 "${tpl.name}" 吗？`, { danger: true })) {
      deleteTemplate(tpl)
    }
  }

  async function deleteTemplate(tpl: TplRecord) {
    try {
      const res = (await templatePreviewApi.deleteTemplate({ id: tpl.id })) as TplApiResponse

      if (res && res.success) {
        deps.templates.value = (deps.templates.value || []).filter(item => String(item?.id || '') !== String(tpl?.id || ''))
        await appAlert('删除成功！')
        deps.refreshTemplates()
      } else {
        throw new Error((res && res.message) || '删除失败')
      }
    } catch (err) {
      await appAlert('删除失败：' + (err instanceof Error ? (err.message || '未知错误') : String(err)))
    }
  }

  return {
    showPreviewModal,
    previewingTemplate,
    showEditModal,
    editingTemplate,
    showReplaceModal,
    replaceSourceTemplate,
    replaceTargetTemplateId,
    replacingTemplate,
    previewTemplate,
    closePreviewModal,
    openTemplateTarget,
    editTemplate,
    closeEditModal,
    openReplaceTemplateDialog,
    closeReplaceModal,
    confirmReplaceTemplate,
    saveTemplateEdit,
    openLabelEditor,
    confirmDeleteTemplate,
    deleteTemplate,
  }
}
