import { nextTick } from 'vue'
import type { Router } from 'vue-router'
import type { AssistantFloatState } from './useAssistantFloatState'

/** xcagi:excel-sheet-context 事件 detail 的宽松结构（与原实现字段一一对应） */
interface ExcelSheetContextDetail {
  selected_sheet?: { sheet_name?: string; sheet_index?: number } | null
  excel_analysis?: {
    preview_data?: {
      all_sheets?: Array<{
        sheet_name?: string
        sheet_index?: number
        grid_preview?: Record<string, unknown>
        fields?: unknown[]
        sample_rows?: unknown[]
      }>
    }
  } | null
}

/**
 * 关联 Excel 网格状态同步（由 TopAssistantFloat.vue 机械切出，行为不变）。
 */
export function useAssistantLinkedGrid(
  state: AssistantFloatState,
  { router, fillChatInputWithRetry }: { router: Router; fillChatInputWithRetry: (text: string) => Promise<void> },
) {
  const {
    linkedSheetName,
    linkedSheetIndex,
    linkedGridData,
    linkedSheetFields,
    linkedSheetSampleRows,
    topScrollRef,
    excelPreviewRef,
    topScrollInnerWidth,
  } = state

  const applyExcelSheetContext = (detail: ExcelSheetContextDetail | null | undefined) => {
    const selected = detail?.selected_sheet || {}
    const excel = detail?.excel_analysis || {}
    linkedSheetName.value = String(selected?.sheet_name || '').trim()
    linkedSheetIndex.value = Number(selected?.sheet_index || 0)
    const allSheets = Array.isArray(excel?.preview_data?.all_sheets) ? excel.preview_data.all_sheets : []
    const target = allSheets.find((s) => {
      const n = String(s?.sheet_name || '').trim()
      const i = Number(s?.sheet_index || 0)
      return (linkedSheetName.value && n === linkedSheetName.value) || (linkedSheetIndex.value > 0 && i === linkedSheetIndex.value)
    }) || allSheets[0]
    linkedGridData.value = target?.grid_preview && typeof target.grid_preview === 'object' ? target.grid_preview : null
    linkedSheetFields.value = Array.isArray(target?.fields) ? target.fields : []
    linkedSheetSampleRows.value = Array.isArray(target?.sample_rows) ? target.sample_rows : []
  }

  const syncTopScrollMetrics = async () => {
    await nextTick()
    const root = excelPreviewRef.value?.$el || excelPreviewRef.value
    const excelContainer = root?.querySelector?.('.excel-container')
    if (!excelContainer) {
      topScrollInnerWidth.value = 0
      return
    }
    excelContainer.removeEventListener('scroll', onExcelScroll)
    excelContainer.addEventListener('scroll', onExcelScroll, { passive: true })
    const targetWidth = Math.max(excelContainer.scrollWidth || 0, excelContainer.clientWidth || 0)
    topScrollInnerWidth.value = targetWidth
  }

  const onTopScroll = (evt: { target?: { scrollLeft?: number } | null }) => {
    const root = excelPreviewRef.value?.$el || excelPreviewRef.value
    const excelContainer = root?.querySelector?.('.excel-container')
    if (!excelContainer) return
    excelContainer.scrollLeft = evt?.target?.scrollLeft || 0
  }

  const onExcelScroll = () => {
    const root = excelPreviewRef.value?.$el || excelPreviewRef.value
    const excelContainer = root?.querySelector?.('.excel-container')
    if (!excelContainer || !topScrollRef.value) return
    topScrollRef.value.scrollLeft = excelContainer.scrollLeft || 0
  }

  const onExcelSheetContext = (evt: { detail?: ExcelSheetContextDetail | null }) => {
    const detail = evt?.detail || {}
    applyExcelSheetContext(detail)
  }

  const triggerGridReadFromChat = async () => {
    if (!linkedSheetName.value) return
    const text = `请调用业务对接的上传并提取能力，读取并展示 Sheet ${linkedSheetIndex.value || ''}（${linkedSheetName.value}）的网格结构`
    await router.push({ name: 'chat' })
    await nextTick()
    await fillChatInputWithRetry(text)
  }

  return {
    applyExcelSheetContext,
    syncTopScrollMetrics,
    onTopScroll,
    onExcelScroll,
    onExcelSheetContext,
    triggerGridReadFromChat,
  }
}
