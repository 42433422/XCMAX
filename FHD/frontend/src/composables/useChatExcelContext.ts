import { ref, computed, type Ref } from 'vue'
import {
  EXCEL_ANALYSIS_STORAGE_PREFIX,
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

export type MultimodalRequestSnapshot = {
  sessionId: string
  rows: MultimodalAttachmentRow[]
}

export function useChatExcelContext(deps: UseChatExcelContextDeps) {
  const { sessionId, addAndSaveMessage } = deps

  const lastExcelAnalysisContext = ref<Record<string, unknown> | null>(null)
  const linkedExcelSheet = ref<LinkedExcelSheet | null>(null)
  const linkedExcelAllSheets = ref(false)
  const multimodalStagingBySession = ref<Record<string, MultimodalAttachmentRow[]>>({})
  const sessionKey = (value: unknown = sessionId.value) => String(value || '').trim() || 'default'
  let excelContextSessionId = sessionKey()
  const multimodalStaging = computed<MultimodalAttachmentRow[]>({
    get: () => multimodalStagingBySession.value[sessionKey()] || [],
    set: (rows) => {
      multimodalStagingBySession.value = {
        ...multimodalStagingBySession.value,
        [sessionKey()]: Array.isArray(rows) ? rows : [],
      }
    },
  })
  const multimodalPendingCount = computed(() => multimodalStaging.value.length)

  function resolveExcelAnalysisContextForRequest(): Record<string, unknown> | null {
    const sid = sessionKey()
    if (excelContextSessionId !== sid) {
      activateSessionContext(sid)
    }
    if (lastExcelAnalysisContext.value) return lastExcelAnalysisContext.value
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

  /**
   * Capture the current session's attachments for one request without removing
   * them. The caller acknowledges the snapshot only after the server accepts
   * the request, so network errors and timeouts remain retryable.
   */
  function consumeMultimodalIntoPlannerContext(
    contextPayload: Record<string, unknown>,
    contextParts: string[]
  ): MultimodalRequestSnapshot | null {
    const rows = multimodalStaging.value
    if (!rows.length) return null
    const snapshot = { sessionId: sessionKey(), rows: rows.slice() }
    contextPayload.multimodal_attachments = rows.map((r) => ({ ...r }))
    contextParts.push(`多模态附件 ${rows.length} 个`)
    return snapshot
  }

  function acknowledgeMultimodalRequest(snapshot: MultimodalRequestSnapshot | null | undefined): void {
    if (!snapshot?.rows.length) return
    const sid = sessionKey(snapshot.sessionId)
    const acknowledged = new Set(snapshot.rows)
    const current = multimodalStagingBySession.value[sid] || []
    if (!current.some((row) => acknowledged.has(row))) return
    multimodalStagingBySession.value = {
      ...multimodalStagingBySession.value,
      [sid]: current.filter((row) => !acknowledged.has(row)),
    }
  }

  function clearMultimodalForSession(targetSessionId: string = sessionKey()): void {
    const sid = sessionKey(targetSessionId)
    if (!(sid in multimodalStagingBySession.value)) return
    const next = { ...multimodalStagingBySession.value }
    delete next[sid]
    multimodalStagingBySession.value = next
  }

  function activateSessionContext(targetSessionId: string): void {
    const sid = sessionKey(targetSessionId)
    excelContextSessionId = sid
    const restored = readPersistedExcelAnalysisContext(sid)
    lastExcelAnalysisContext.value = restored
    linkedExcelAllSheets.value = false
    linkedExcelSheet.value = resolveExcelSheetOptionsFromContext(restored)[0] || null
  }

  function clearSessionContext(targetSessionId: string, clearPersistedExcel = false): void {
    const sid = sessionKey(targetSessionId)
    clearMultimodalForSession(sid)
    if (clearPersistedExcel) persistExcelAnalysisContext(sid, null)
    if (sid === sessionKey()) {
      excelContextSessionId = sid
      lastExcelAnalysisContext.value = null
      linkedExcelSheet.value = null
      linkedExcelAllSheets.value = false
    }
  }

  function clearAllSessionContexts(): void {
    multimodalStagingBySession.value = {}
    lastExcelAnalysisContext.value = null
    linkedExcelSheet.value = null
    linkedExcelAllSheets.value = false
    excelContextSessionId = sessionKey()
    if (typeof sessionStorage === 'undefined') return
    const removeKeys: string[] = []
    for (let i = 0; i < sessionStorage.length; i += 1) {
      const key = String(sessionStorage.key(i) || '')
      if (key.startsWith(EXCEL_ANALYSIS_STORAGE_PREFIX)) removeKeys.push(key)
    }
    removeKeys.forEach((key) => sessionStorage.removeItem(key))
  }

  async function onMultimodalFileChange(ev: Event) {
    const el = ev.target as HTMLInputElement | null
    if (!el?.files?.length) return
    const targetSessionId = sessionKey()
    // FileList is tied to the input and can become empty as soon as value is
    // reset. Snapshot the File objects first; otherwise image/PDF selection is
    // a silent no-op on Electron/macOS.
    const list = Array.from(el.files)
    el.value = ''
    const res = await filesToMultimodalRows(list)
    if (!res.ok) {
      if (targetSessionId === sessionKey()) {
        await addAndSaveMessage(`[附件] ${res.error}`, 'ai')
      }
      return
    }
    const targetRows = multimodalStagingBySession.value[targetSessionId] || []
    multimodalStagingBySession.value = {
      ...multimodalStagingBySession.value,
      [targetSessionId]: [...targetRows, ...res.rows].slice(-6),
    }
    if (targetSessionId !== sessionKey()) return
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
    acknowledgeMultimodalRequest,
    clearMultimodalForSession,
    activateSessionContext,
    clearSessionContext,
    clearAllSessionContexts,
    onMultimodalFileChange,
    bindExcelSheetToChat,
    bindAllExcelSheetsToChat,
    persistExcelAnalysisContextForSession: (sid: string, ctx: Record<string, unknown> | null) =>
      persistExcelAnalysisContext(sid, ctx),
  }
}
