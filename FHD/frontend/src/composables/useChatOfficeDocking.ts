/**
 * 解析办公文件：上传后走数据对接 ELT。工作表是可选模板，保存后提交入库审批。
 */
import { computed, ref } from 'vue'
import api from '@/api/core'
import { isOfficeDockingFileSupported, uploadChatOfficeFile } from '@/utils/officeEmployeeReadApi'
import { asArray, asRecord, asString } from '@/utils/typeGuards'
import { pickOptionalTemplate } from '@/domain/optionalTemplateSelection'
import {
  newItemId,
  type ChatOfficeDockingReviewItem,
  type UseChatOfficeDockingDeps,
} from './officeDocking/officeDockingShared'

export type { ChatOfficeDockingReviewItem } from './officeDocking/officeDockingShared'

function blankItem(fileName: string): ChatOfficeDockingReviewItem {
  return {
    id: newItemId(),
    fileName,
    employeeId: 'elt',
    employeeLabel: 'ELT',
    kindLabel: '办公文件',
    status: 'running',
    commitStatus: '',
    intentId: 'pending',
    intentLabel: 'ELT 解析',
    intentSummary: '正在用数据对接解析，工作表模板可选',
    databaseTargetLabel: '',
    databaseAction: '',
    databaseDisabledReason: '',
    selectedKnowledge: false,
    selectedDatabase: false,
    summary: '',
    warnings: [],
    error: '',
    outputFiles: [],
    knowledgeText: '',
    fieldNames: [],
    sampleRows: [],
    rowCount: 0,
    textPreview: '',
    worksheetTemplates: [],
    selectedTemplateIndex: -1,
    pipeline: 'elt',
  }
}

export function useChatOfficeDocking(deps: UseChatOfficeDockingDeps) {
  const officeDockingInputRef = ref<HTMLInputElement | null>(null)
  const officeDockingProcessing = ref(false)
  const officeDockingPanelOpen = ref(false)
  const officeDockingReviewItems = ref<ChatOfficeDockingReviewItem[]>([])
  const officeDockingPendingCount = computed(() => officeDockingReviewItems.value.filter((item) => item.status === 'ready' && item.commitStatus !== 'committed').length)

  function triggerOfficeDocking() {
    if (officeDockingProcessing.value) return
    officeDockingInputRef.value?.click()
  }

  function touchItems() {
    officeDockingReviewItems.value = [...officeDockingReviewItems.value]
  }

  async function analyzeFile(file: File): Promise<void> {
    const item = blankItem(file.name)
    officeDockingReviewItems.value = [...officeDockingReviewItems.value, item]
    officeDockingPanelOpen.value = true
    if (!isOfficeDockingFileSupported(file.name)) {
      item.status = 'error'
      item.error = '不支持的办公文件'
      touchItems()
      return
    }
    try {
      const upload = await uploadChatOfficeFile(file)
      item.upload = upload
      if (upload.attachment_warning) item.warnings.push(upload.attachment_warning)
      const body = asRecord(await api.post('/api/platform-shell/office/confirm', {
        intent: 'elt_parse',
        file_path: upload.file_path,
        workspace_root: upload.workspace_root,
        source_name: file.name,
        template_index: -1,
      }))
      const data = asRecord(body.data)
      if (body.success === false) throw new Error(asString(body.message || data.summary) || '解析失败')
      item.worksheetTemplates = asArray<Record<string, unknown>>(data.templates).map((row) => ({
        id: asString(row.id || row.sheet || row.label),
        label: asString(row.label || row.sheet || row.id),
        sheet: asString(row.sheet || row.label || row.id),
      })).filter((row) => row.id)
      item.selectedTemplateIndex = -1
      item.rowCount = Number(data.row_count) || 0
      item.fieldNames = asArray(data.headers).map((field) => asString(field)).filter(Boolean)
      item.summary = asString(data.summary) || '已用 ELT 解析，工作表模板可选'
      item.intentSummary = '保存后提交入库审批，通过后才写入'
      item.status = 'ready'
      item.pipeline = 'elt'
      const sheets = item.worksheetTemplates.map((template, index) => ({
        sheet_name: template.label,
        sheet_index: index + 1,
      }))
      deps.stageExcelAnalysisContext({
        file_name: file.name,
        ...(upload.upload_id ? { upload_id: upload.upload_id } : {}),
        file_path: upload.file_path,
        summary: item.summary,
        fields: item.fieldNames,
        sheets,
      })
    } catch (err) {
      item.status = 'error'
      item.error = err instanceof Error ? err.message : '解析失败'
    }
    touchItems()
  }

  async function onOfficeDockingFileChange(event: Event): Promise<void> {
    const input = event.target as HTMLInputElement | null
    const files = Array.from(input?.files || [])
    if (input) input.value = ''
    if (!files.length) return
    officeDockingProcessing.value = true
    try {
      for (const file of files) await analyzeFile(file)
    } finally {
      officeDockingProcessing.value = false
      touchItems()
    }
  }

  function toggleOfficeDockingTarget() {
    /* 入库目标由 ELT 审批决定，不再在这里改写路径。 */
  }

  function pickOfficeWorksheetTemplate(id: string, index: number) {
    const item = officeDockingReviewItems.value.find((row) => row.id === id)
    if (!item || item.commitStatus === 'committing') return
    if (index < 0) {
      item.selectedTemplateIndex = -1
      touchItems()
      return
    }
    const next = pickOptionalTemplate(item.worksheetTemplates?.length || 0, index, false)
    if (next === null) return
    item.selectedTemplateIndex = next
    touchItems()
  }

  async function confirmOfficeDockingReview(): Promise<void> {
    const ready = officeDockingReviewItems.value.filter((item) => item.status === 'ready' && item.commitStatus !== 'committed' && item.upload?.file_path)
    if (!ready.length) return
    for (const item of ready) {
      item.commitStatus = 'committing'
      item.error = ''
      touchItems()
      try {
        const body = asRecord(await api.post('/api/platform-shell/office/confirm', {
          intent: 'elt_save',
          file_path: item.upload?.file_path,
          workspace_root: item.upload?.workspace_root,
          source_name: item.fileName,
          template_index: item.selectedTemplateIndex ?? -1,
        }))
        const data = asRecord(body.data)
        const ingest = asRecord(data.auto_ingest || data)
        if (body.success === false || (ingest.status && ingest.status !== 'awaiting_approval')) {
          throw new Error(asString(body.message || data.summary) || '入库审批没有排队')
        }
        item.commitStatus = 'committed'
        item.summary = `已提交审批：数据对接入库：${item.fileName}。通过后才会写入。`
        await deps.addAndSaveMessage(item.summary, 'ai')
      } catch (err) {
        item.commitStatus = 'failed'
        item.error = err instanceof Error ? err.message : '提交失败'
      }
      touchItems()
    }
  }

  function clearOfficeDockingReview() {
    officeDockingReviewItems.value = []
    officeDockingPanelOpen.value = false
  }

  return {
    officeDockingInputRef,
    officeDockingProcessing,
    officeDockingPanelOpen,
    officeDockingReviewItems,
    officeDockingPendingCount,
    triggerOfficeDocking,
    onOfficeDockingFileChange,
    toggleOfficeDockingTarget,
    pickOfficeWorksheetTemplate,
    confirmOfficeDockingReview,
    clearOfficeDockingReview,
  }
}
