import { ref, computed, type Ref } from 'vue'
import {
  readPersistedExcelAnalysisContext,
  persistExcelAnalysisContext,
  resolveExcelFilePathFromAnalysis,
  resolveExcelSheetOptionsFromContext,
  resolveLinkedSheetGridPreview,
  type LinkedExcelSheet,
} from './useChatPersistence'
import { filesToMultimodalRows, type MultimodalAttachmentRow } from '@/utils/multimodalAttachments'

export interface UseChatExcelContextDeps {
  sessionId: Ref<string>
  addAndSaveMessage: (content: string, role?: 'user' | 'ai' | 'task', extras?: Record<string, unknown>) => Promise<void>
  resolveExcelAnalysisContextForRequest?: () => Record<string, unknown> | null
}

export function useChatExcelContext(deps: UseChatExcelContextDeps) {
  const { sessionId, addAndSaveMessage } = deps

  const lastExcelAnalysisContext = ref<Record<string, unknown> | null>(null)
  const linkedExcelSheet = ref<LinkedExcelSheet | null>(null)
  const linkedExcelAllSheets = ref(false)
  const multimodalStaging = ref<MultimodalAttachmentRow[]>([])
  const multimodalPendingCount = computed(() => multimodalStaging.value.length)

  function resolveExcelAnalysisContextForRequest(): Record<string, unknown> | null {
    if (lastExcelAnalysisContext.value) return lastExcelAnalysisContext.value
    const sid = String(sessionId.value || '').trim() || 'default'
    const restored = readPersistedExcelAnalysisContext(sid)
    if (restored) {
      lastExcelAnalysisContext.value = restored
      return restored
    }
    return null
  }

  const excelSheetOptions = computed(() => {
    const ctx = resolveExcelAnalysisContextForRequest()
    return resolveExcelSheetOptionsFromContext(ctx)
  })

  function injectExcelContextPayload(contextPayload: Record<string, unknown>, contextParts: string[]): boolean {
    const excelCtx = resolveExcelAnalysisContextForRequest()
    if (!excelCtx) return false
    contextPayload.excel_analysis = excelCtx
    contextParts.push('Excel上下文 1 份')
    const fp = resolveExcelFilePathFromAnalysis(excelCtx)
    if (fp) {
      contextPayload.excel_file_path = fp
    }

    const allSheets = resolveExcelSheetOptionsFromContext(excelCtx)
    if (linkedExcelAllSheets.value && allSheets.length) {
      contextPayload.excel_analysis_select_all_sheets = true
      contextPayload.excel_analysis_selected_sheets = allSheets
      contextParts.push(`已关联全部工作表 ${allSheets.length} 个`)
      const previews = allSheets
        .slice(0, 8)
        .map((sheet) => resolveLinkedSheetGridPreview(excelCtx, sheet))
        .filter(Boolean)
      if (previews.length) {
        contextPayload.excel_linked_grid_previews = previews
        contextParts.push(`真实网格预览 ${previews.length} 份`)
      }
      return true
    }

    if (linkedExcelSheet.value?.sheet_name) {
      contextPayload.excel_analysis_selected_sheet = {
        sheet_name: linkedExcelSheet.value.sheet_name,
        sheet_index: linkedExcelSheet.value.sheet_index
      }
      contextPayload.preferred_sheet_name = linkedExcelSheet.value.sheet_name
      contextPayload.preferred_sheet_index = linkedExcelSheet.value.sheet_index
      contextParts.push(`已关联表 ${linkedExcelSheet.value.sheet_index}:${linkedExcelSheet.value.sheet_name}`)
      const preview = resolveLinkedSheetGridPreview(excelCtx, linkedExcelSheet.value)
      if (preview) {
        contextPayload.excel_linked_grid_preview = preview
        contextParts.push('真实网格预览 1 份')
      }
    }
    return true
  }

  function consumeMultimodalIntoPlannerContext(
    contextPayload: Record<string, unknown>,
    contextParts: string[]
  ) {
    const rows = multimodalStaging.value
    if (!rows.length) return
    contextPayload.multimodal_attachments = rows.map((r) => ({ ...r }))
    contextParts.push(`多模态附件 ${rows.length} 个`)
    multimodalStaging.value = []
  }

  async function onMultimodalFileChange(ev: Event) {
    const el = ev.target as HTMLInputElement | null
    if (!el?.files?.length) return
    const list = el.files
    el.value = ''
    const res = await filesToMultimodalRows(list)
    if (!res.ok) {
      await addAndSaveMessage(`[附件] ${res.error}`, 'ai')
      return
    }
    multimodalStaging.value = [...multimodalStaging.value, ...res.rows].slice(-6)
    await addAndSaveMessage(
      `[附件] 已加入 ${res.rows.length} 个文件（${res.rows.map((r) => r.filename).join('、')}），发送下一条消息时将一并提交给模型。`,
      'ai'
    )
  }


  async function bindExcelSheetToChat(sheet: LinkedExcelSheet): Promise<void> {
    const name = String(sheet?.sheet_name || '').trim()
    const idx = Number(sheet?.sheet_index || 0)
    if (!name || idx <= 0) return
    linkedExcelAllSheets.value = false
    linkedExcelSheet.value = { sheet_name: name, sheet_index: idx }
    const excelCtx = resolveExcelAnalysisContextForRequest()
    window.dispatchEvent(new CustomEvent('xcagi:excel-sheet-context', {
      detail: {
        select_all_sheets: false,
        selected_sheet: linkedExcelSheet.value,
        excel_analysis: excelCtx
      }
    }))
    window.dispatchEvent(new CustomEvent('xcagi:open-assistant-float', {
      detail: {
        feature: 'assistant',
        forceOpen: true,
        task: true
      }
    }))
    // 仅更新上下文，不插入聊天提示，避免打断会话阅读。
  }

  async function bindAllExcelSheetsToChat(): Promise<void> {
    const excelCtx = resolveExcelAnalysisContextForRequest()
    if (!excelCtx) return
    const allSheets = resolveExcelSheetOptionsFromContext(excelCtx)
    if (!allSheets.length) return
    linkedExcelAllSheets.value = true
    linkedExcelSheet.value = allSheets[0]
    window.dispatchEvent(new CustomEvent('xcagi:excel-sheet-context', {
      detail: {
        selected_sheet: linkedExcelSheet.value,
        select_all_sheets: true,
        selected_sheets: allSheets,
        excel_analysis: excelCtx
      }
    }))
    window.dispatchEvent(new CustomEvent('xcagi:open-assistant-float', {
      detail: {
        feature: 'assistant',
        forceOpen: true,
        task: true
      }
    }))
  }

  return {
    lastExcelAnalysisContext,
    linkedExcelSheet,
    linkedExcelAllSheets,
    multimodalStaging,
    multimodalPendingCount,
    excelSheetOptions,
    resolveExcelAnalysisContextForRequest,
    injectExcelContextPayload,
    consumeMultimodalIntoPlannerContext,
    onMultimodalFileChange,
    bindExcelSheetToChat,
    bindAllExcelSheetsToChat,
    persistExcelAnalysisContextForSession: (sid: string, ctx: Record<string, unknown> | null) =>
      persistExcelAnalysisContext(sid, ctx),
  }
}
