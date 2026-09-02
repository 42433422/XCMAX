import { computed, ref } from 'vue'
import templatePreviewApi from '@/api/templatePreview'
import { stripGridPreviewData, stripSampleRowsKeepTemplateShape } from '@/shared/templatePreviewSanitize.js'
import { appAlert, appConfirm } from '@/utils/appDialog'
import { extractTemplateTermSet } from './tpTemplateMeta'
import type { TplField, TplPreviewData } from './tpTemplateMeta'
import { getRequiredTermsByScope, getScopeMeta, hasEquivalentTerm } from './tpScopeRules'
import type { TemplateScopeMeta } from './tpScopeRules'

export interface TpCreateFlowDeps {
  refreshTemplates: () => void | Promise<void>
}

/** FileUploadStep file-selected 事件载荷 */
interface TpFileSelectedData {
  selectedFile: File | null
  templateName: string
  recognizedType: unknown
}

/** 模板分析接口返回（宽松契约） */
interface AnalyzeTemplateResponse {
  success?: boolean
  message?: string
  template_type?: string
  task_id?: string | number
  fields?: TplField[]
  preview_data?: TplPreviewData | null
  missing_terms?: unknown[]
  [key: string]: unknown
}

/** 分析进度轮询返回（宽松契约） */
interface AnalysisProgressResponse {
  success?: boolean
  progress?: number
  step?: number
  message?: string
  completed?: boolean
  [key: string]: unknown
}

/** 保存模板接口返回（宽松契约） */
interface TemplateMutationResponse {
  success?: boolean
  message?: string
  [key: string]: unknown
}

/** 创建模板弹窗全流程：选择文件 → 分析 → 编辑字段 → 保存（对应原视图创建相关状态与方法） */
export function useTpCreateFlow(deps: TpCreateFlowDeps) {
  const showCreateModal = ref(false)
  const createStep = ref(1)
  const selectedFile = ref<File | null>(null)
  const templateName = ref('')
  const templateScope = ref('orders')
  const customScopeLabel = ref('')
  const customTemplateType = ref('')
  const recognizedType = ref<unknown>(null)
  const editorFields = ref<TplField[]>([])
  const editorTemplateType = ref('excel')
  /** 分析接口返回的完整 preview_data（保存时做脱敏后写入） */
  const analyzedPreviewData = ref<TplPreviewData | null>(null)
  const analyzedFilePath = ref('')
  const analyzedOriginalFilename = ref('')
  const uploadValidationResult = ref<{ valid: boolean; missing: string[] } | null>(null)
  // 分析进度
  const analyzing = ref(false)
  const progressStep = ref(1)
  const progressPercent = ref(0)
  const progressMessage = ref('准备上传...')
  let progressTimer: ReturnType<typeof setInterval> | null = null

  const isCustomScope = computed(() => String(templateScope.value || '') === 'custom')
  const selectedScopeRequiredTerms = computed(() => getRequiredTermsByScope(templateScope.value))
  const canProceedStep1 = computed(() => selectedFile.value && templateName.value.trim())

  function stopProgressTimer() {
    if (progressTimer) {
      clearInterval(progressTimer)
      progressTimer = null
    }
  }

  function onFileSelected(data: TpFileSelectedData) {
    selectedFile.value = data.selectedFile
    templateName.value = data.templateName
    recognizedType.value = data.recognizedType
  }

  function closeCreateModal() {
    stopProgressTimer()
    showCreateModal.value = false
    resetCreateState()
  }

  function resetCreateState() {
    createStep.value = 1
    selectedFile.value = null
    templateName.value = ''
    templateScope.value = 'orders'
    customScopeLabel.value = ''
    customTemplateType.value = ''
    recognizedType.value = null
    editorFields.value = []
    editorTemplateType.value = 'excel'
    analyzedPreviewData.value = null
    analyzedFilePath.value = ''
    analyzedOriginalFilename.value = ''
    uploadValidationResult.value = null
  }

  function prevStep() {
    if (createStep.value > 1) {
      createStep.value--
    }
  }

  async function nextStep() {
    if (createStep.value === 1 && canProceedStep1.value) {
      const passed = await analyzeFile()
      if (passed) {
        createStep.value = 2
      }
    }
  }

  async function analyzeFile() {
    try {
      if (!selectedFile.value) {
        await appAlert('请先选择文件')
        return false
      }

      const name = String(selectedFile.value.name || '')
      const ext = (name.split('.').pop() || '').toLowerCase()
      if (!['xlsx', 'xls', 'docx'].includes(ext)) {
        await appAlert('请上传 Excel（.xlsx / .xls）或 Word（.docx）模板文件')
        return false
      }

      analyzing.value = true
      progressStep.value = 1
      progressPercent.value = 0
      progressMessage.value = '准备上传文件...'
      analyzedPreviewData.value = null
      analyzedFilePath.value = ''
      analyzedOriginalFilename.value = ''

      const formData = new FormData()
      formData.append('file', selectedFile.value)
      formData.append('template_name', templateName.value)
      formData.append('template_scope', templateScope.value)

      const res = (await templatePreviewApi.analyzeTemplate(formData)) as AnalyzeTemplateResponse

      if (res && res.success) {
        const kind = String(res.template_type || '').toLowerCase()
        if (kind !== 'excel' && kind !== 'word') {
          analyzing.value = false
          await appAlert('本页仅支持创建 Excel 或 Word 导出模板')
          return false
        }

        const validation = validateUploadedTemplate(res)
        uploadValidationResult.value = validation
        if (!validation.valid) {
          analyzing.value = false
          const missingText = validation.missing.join('、')
          const proceed = await appConfirm(
            `模板词条校验未通过，缺少：${missingText}。\n\n仍要以「自定义」业务继续创建吗？`
          )
          if (!proceed) {
            return false
          }
          templateScope.value = 'custom'
          if (!customScopeLabel.value.trim()) {
            customScopeLabel.value = String(templateName.value || '').trim() || '自定义业务'
          }
          analyzing.value = true
        }

        const taskId = res.task_id
        if (taskId) {
          await pollProgress(taskId)
        } else {
          analyzing.value = false
        }

        const preview = res.preview_data && typeof res.preview_data === 'object' ? { ...res.preview_data } : {}
        analyzedPreviewData.value = preview
        analyzedFilePath.value = String(preview.file_path || '').trim()
        analyzedOriginalFilename.value = String(preview.original_filename || selectedFile.value.name || '').trim()

        editorFields.value = Array.isArray(res.fields) ? [...res.fields] : []
        editorTemplateType.value = kind === 'word' ? 'word' : 'excel'

        await new Promise(resolve => setTimeout(resolve, 300))
        return true
      }

      analyzing.value = false
      const missing = Array.isArray(res?.missing_terms) ? res.missing_terms.filter(Boolean) : []
      if (missing.length && !isCustomScope.value) {
        const switchCustom = await appConfirm(
          `${res?.message || '模板缺少必备词条'}：${missing.join('、')}。\n\n是否改为「自定义（不限业务）」后继续创建？`
        )
        if (switchCustom) {
          templateScope.value = 'custom'
          if (!customScopeLabel.value.trim()) {
            customScopeLabel.value = String(templateName.value || '').trim() || '自定义业务'
          }
          return await analyzeFile()
        }
        return false
      }
      await appAlert((res && res.message) || '分析失败')
      return false
    } catch (err) {
      analyzing.value = false
      const errRec = (err && typeof err === 'object' ? err : {}) as {
        data?: unknown
        response?: { data?: unknown } | null
        message?: unknown
      }
      const data = (errRec.data || errRec.response?.data || {}) as {
        missing_terms?: unknown
        message?: unknown
      }
      const missing = Array.isArray(data?.missing_terms) ? data.missing_terms.filter(Boolean) : []
      if (missing.length && !isCustomScope.value) {
        const switchCustom = await appConfirm(
          `${data?.message || errRec.message || '模板缺少必备词条'}：${missing.join('、')}。\n\n是否改为「自定义（不限业务）」后继续创建？`
        )
        if (switchCustom) {
          templateScope.value = 'custom'
          if (!customScopeLabel.value.trim()) {
            customScopeLabel.value = String(templateName.value || '').trim() || '自定义业务'
          }
          return await analyzeFile()
        }
        return false
      }
      await appAlert('分析失败：' + (err instanceof Error ? err.message : String(err)))
      return false
    }
  }

  function pollProgress(taskId: string | number) {
    stopProgressTimer()
    return new Promise<void>((resolve) => {
      const pollInterval = setInterval(async () => {
        try {
          const data = (await templatePreviewApi.getAnalysisProgress(taskId)) as AnalysisProgressResponse

          if (data.success) {
            progressPercent.value = data.progress as number
            progressStep.value = data.step as number
            progressMessage.value = data.message || '分析中...'

            if (data.completed) {
              clearInterval(pollInterval)
              progressTimer = null
              analyzing.value = false
              resolve()
            }
          }
        } catch (err) {
          console.error('轮询进度失败:', err)
        }
      }, 1000)

      progressTimer = pollInterval
    })
  }

  function onUpdateField(index: number, field: TplField) {
    editorFields.value.splice(index, 1, field)
  }

  function onDeleteField(index: number) {
    editorFields.value.splice(index, 1)
  }

  function onAddField(field: TplField) {
    editorFields.value.push(field)
  }

  function onFieldsChange(fields: TplField[]) {
    editorFields.value = [...fields]
  }

  function onFieldChange() {}

  function onFieldsUpdate(fields: TplField[]) {
    editorFields.value = fields
  }

  async function saveTemplate() {
    try {
      const fields = Array.isArray(editorFields.value) ? [...editorFields.value] : []
      const isCustom = isCustomScope.value
      const scopeMeta: Partial<TemplateScopeMeta> = getScopeMeta(templateScope.value) || {}
      const isWord = editorTemplateType.value === 'word'
      const category = isWord ? 'word' : 'excel'
      const customLabel = String(customScopeLabel.value || '').trim()
      const customType = String(customTemplateType.value || '').trim()
      const templateType = isCustom
        ? (customType || String(templateName.value || '').trim() || scopeMeta.templateType || '自定义模板')
        : (scopeMeta.templateType || '自定义模板')

      const basePreview =
        analyzedPreviewData.value && typeof analyzedPreviewData.value === 'object'
          ? { ...analyzedPreviewData.value }
          : {}

      let preview_data: Record<string, unknown>
      if (isWord) {
        preview_data = {
          ...basePreview,
          placeholders: Array.isArray(basePreview.placeholders) ? [...basePreview.placeholders] : []
        }
      } else {
        const strippedSampleRows = stripSampleRowsKeepTemplateShape(
          basePreview.sample_rows,
          fields
        )
        const strippedGrid = stripGridPreviewData(basePreview.grid_preview, basePreview.sample_rows)
        preview_data = {
          ...basePreview,
          sample_rows: strippedSampleRows,
          grid_preview: strippedGrid
        }
      }
      if (isCustom && customLabel) {
        preview_data.custom_scope_label = customLabel
      }

      const file_path =
        String(analyzedFilePath.value || preview_data.file_path || '').trim() || undefined

      const saveData = {
        name: templateName.value,
        category,
        template_type: templateType,
        business_scope: templateScope.value || 'custom',
        fields,
        preview_data,
        file_path,
        original_filename:
          analyzedOriginalFilename.value ||
          String(selectedFile.value?.name || preview_data.original_filename || '').trim() ||
          undefined,
        source: 'generated'
      }

      const res = (await templatePreviewApi.createTemplate(saveData)) as TemplateMutationResponse

      if (res && res.success) {
        await appAlert('模板保存成功！')
        closeCreateModal()
        deps.refreshTemplates()
        window.dispatchEvent(new CustomEvent('xcagi:templates-updated', { detail: { source: 'template-preview' } }))
      } else {
        throw new Error((res && res.message) || '保存失败')
      }
    } catch (err) {
      await appAlert('保存失败：' + (err instanceof Error ? (err.message || '未知错误') : String(err)))
    }
  }

  function openCreateModal() {
    resetCreateState()
    showCreateModal.value = true
  }

  function startCreateForScope(scopeKey?: string) {
    const meta = getScopeMeta(scopeKey)
    resetCreateState()
    templateScope.value = scopeKey || 'orders'
    if (meta && !templateName.value) {
      templateName.value = `${meta.label}模板`
    }
    showCreateModal.value = true
  }

  function validateUploadedTemplate(analyzeResult: AnalyzeTemplateResponse) {
    const kind = String(analyzeResult?.template_type || '').toLowerCase()
    if (kind !== 'excel' && kind !== 'word') {
      return { valid: false, missing: ['仅支持 Excel 或 Word 模板'] }
    }
    const required = getRequiredTermsByScope(templateScope.value)
    if (!required.length) {
      return { valid: true, missing: [] as string[] }
    }
    const termSet = extractTemplateTermSet(analyzeResult?.fields, analyzeResult?.preview_data)
    const missing = required.filter(term => !hasEquivalentTerm(termSet, term))
    return {
      valid: missing.length === 0,
      missing
    }
  }

  return {
    showCreateModal,
    createStep,
    selectedFile,
    templateName,
    templateScope,
    customScopeLabel,
    customTemplateType,
    recognizedType,
    editorFields,
    editorTemplateType,
    analyzedPreviewData,
    analyzedFilePath,
    analyzedOriginalFilename,
    uploadValidationResult,
    analyzing,
    progressStep,
    progressPercent,
    progressMessage,
    isCustomScope,
    selectedScopeRequiredTerms,
    canProceedStep1,
    stopProgressTimer,
    onFileSelected,
    closeCreateModal,
    resetCreateState,
    prevStep,
    nextStep,
    analyzeFile,
    pollProgress,
    onUpdateField,
    onDeleteField,
    onAddField,
    onFieldsChange,
    onFieldChange,
    onFieldsUpdate,
    saveTemplate,
    openCreateModal,
    startCreateForScope,
    validateUploadedTemplate,
  }
}
