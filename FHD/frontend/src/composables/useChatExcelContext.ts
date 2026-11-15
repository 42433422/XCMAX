import { ref, computed, watch, getCurrentScope, onScopeDispose, type Ref } from 'vue'
import {
  readPersistedExcelAnalysisContext,
  persistExcelAnalysisContext,
  resolveExcelFilePathFromAnalysis,
  resolveExcelSheetOptionsFromContext,
  resolveLinkedSheetGridPreview,
  type LinkedExcelSheet,
} from './useChatPersistence'
import { filesToMultimodalRows, type MultimodalAttachmentRow } from '@/utils/multimodalAttachments'
import { removeChatArtifactId, uploadChatArtifactsDetailed } from '@/utils/chatArtifactContext'
import { resolveChatIdentity } from '@/utils/chatStorageKeys'

export interface UseChatExcelContextDeps {
  sessionId: Ref<string>
  addAndSaveMessage: (content: string, role?: 'user' | 'ai' | 'task', extras?: Record<string, unknown>) => Promise<void>
  resolveExcelAnalysisContextForRequest?: () => Record<string, unknown> | null
  getIdentity?: () => string
  captureIsCurrent?: () => () => boolean
}

export function useChatExcelContext(deps: UseChatExcelContextDeps) {
  const { sessionId, addAndSaveMessage } = deps

  const lastExcelAnalysisContext = ref<Record<string, unknown> | null>(null)
  const linkedExcelSheet = ref<LinkedExcelSheet | null>(null)
  const linkedExcelAllSheets = ref(false)
  const multimodalStaging = ref<MultimodalAttachmentRow[]>([])
  /** 已上传成后端工件的文件（如整批 Excel）：在输入框以芯片展示，发送时随 artifact_ids 提交。 */
  const artifactStaging = ref<Array<{ filename: string; artifact_id: string }>>([])
  const multimodalPendingCount = computed(
    () => multimodalStaging.value.length + artifactStaging.value.length,
  )
  const scopeKey = () => JSON.stringify([sessionId.value, (deps.getIdentity || resolveChatIdentity)()])
  let activeScope = scopeKey(), revision = 0
  function syncScope() {
    const next = scopeKey()
    if (next === activeScope) return
    activeScope = next
    revision += 1
    lastExcelAnalysisContext.value = readPersistedExcelAnalysisContext(String(sessionId.value || '').trim() || 'default')
    linkedExcelSheet.value = null
    linkedExcelAllSheets.value = false
    multimodalStaging.value = []
    artifactStaging.value = []
  }
  watch(scopeKey, syncScope, { flush: 'sync' })
  if (getCurrentScope()) onScopeDispose(() => { revision += 1 })

  function resolveExcelAnalysisContextForRequest(): Record<string, unknown> | null {
    syncScope()
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
    const uploadId = typeof excelCtx.upload_id === 'string' ? excelCtx.upload_id.trim() : ''
    if (uploadId) contextPayload.attachment_upload_ids = [uploadId]
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
        sheet_index: linkedExcelSheet.value.sheet_index,
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

  function consumeMultimodalIntoPlannerContext(contextPayload: Record<string, unknown>, contextParts: string[]) {
    syncScope()
    // 工件已随 artifact_ids 提交，本轮芯片一并收起；发送失败时仍可从后端工件重新提问。
    artifactStaging.value = []
    const rows = multimodalStaging.value
    if (!rows.length) return
    contextPayload.multimodal_attachments = rows.map((r) => ({ ...r }))
    contextParts.push(`多模态附件 ${rows.length} 个`)
    multimodalStaging.value = []
  }

  /** 整批 Excel 等文件：上传成后端工件，并在输入框逐个显示可移除的芯片。 */
  async function stageArtifactFiles(list: File[]): Promise<number> {
    if (!list.length) return 0
    syncScope()
    const uploaded = await uploadChatArtifactsDetailed(list)
    if (!uploaded.length) return 0
    artifactStaging.value = [
      ...artifactStaging.value,
      ...uploaded.map((row) => ({ filename: row.name, artifact_id: row.id })),
    ].slice(-50)
    return uploaded.length
  }

  function removeArtifactFile(artifactId: string) {
    removeChatArtifactId(artifactId)
    artifactStaging.value = artifactStaging.value.filter((row) => row.artifact_id !== artifactId)
  }

  function removeMultimodalFile(row: MultimodalAttachmentRow) {
    const index = multimodalStaging.value.indexOf(row)
    if (index >= 0) multimodalStaging.value.splice(index, 1)
  }

  async function stageMultimodalFiles(list: File[]) {
    if (!list.length) return
    syncScope()
    // 额外登记后端工件（失败静默）：对话侧可用 artifact_id 取数，不影响现有解析与摘要。
    void uploadChatArtifactsDetailed(list)
    const capturedScope = activeScope, capturedRevision = revision
    const isCurrent = deps.captureIsCurrent?.() || (() => true)
    const res = await filesToMultimodalRows(list, { skipUnsupported: list.length > 1 })
    if (capturedRevision !== revision || capturedScope !== scopeKey() || !isCurrent()) return
    if (!res.ok) {
      await addAndSaveMessage(`[附件] ${res.error}`, 'ai')
      return
    }
    multimodalStaging.value = [...multimodalStaging.value, ...res.rows].slice(-50)
    const names = res.rows.slice(0, 5).map((r) => r.filename).join('、')
    const suffix = res.rows.length > 5 ? ` 等 ${res.rows.length} 个文件` : ''
    await addAndSaveMessage(
      `[附件] 已加入 ${res.rows.length} 个文件（${names}${suffix}），发送下一条消息时将一并提交给模型。`,
      'ai',
    )
  }

  async function onMultimodalFileChange(ev: Event) {
    const el = ev.target as HTMLInputElement | null
    if (!el?.files?.length) return
    // FileList is tied to the input and can become empty as soon as value is
    // reset. Snapshot the File objects first; otherwise image/PDF selection is
    // a silent no-op on Electron/macOS.
    const list = Array.from(el.files)
    el.value = ''
    await stageMultimodalFiles(list)
  }

  async function bindExcelSheetToChat(sheet: LinkedExcelSheet): Promise<void> {
    const name = String(sheet?.sheet_name || '').trim()
    const idx = Number(sheet?.sheet_index || 0)
    if (!name || idx <= 0) return
    linkedExcelAllSheets.value = false
    linkedExcelSheet.value = { sheet_name: name, sheet_index: idx }
    const excelCtx = resolveExcelAnalysisContextForRequest()
    window.dispatchEvent(
      new CustomEvent('xcagi:excel-sheet-context', {
        detail: {
          select_all_sheets: false,
          selected_sheet: linkedExcelSheet.value,
          excel_analysis: excelCtx,
        },
      }),
    )
    window.dispatchEvent(
      new CustomEvent('xcagi:open-assistant-float', {
        detail: {
          feature: 'assistant',
          forceOpen: true,
          task: true,
        },
      }),
    )
    // 仅更新上下文，不插入聊天提示，避免打断会话阅读。
  }

  async function bindAllExcelSheetsToChat(): Promise<void> {
    const excelCtx = resolveExcelAnalysisContextForRequest()
    if (!excelCtx) return
    const allSheets = resolveExcelSheetOptionsFromContext(excelCtx)
    if (!allSheets.length) return
    linkedExcelAllSheets.value = true
    linkedExcelSheet.value = allSheets[0]
    window.dispatchEvent(
      new CustomEvent('xcagi:excel-sheet-context', {
        detail: {
          selected_sheet: linkedExcelSheet.value,
          select_all_sheets: true,
          selected_sheets: allSheets,
          excel_analysis: excelCtx,
        },
      }),
    )
    window.dispatchEvent(
      new CustomEvent('xcagi:open-assistant-float', {
        detail: {
          feature: 'assistant',
          forceOpen: true,
          task: true,
        },
      }),
    )
  }

  return {
    lastExcelAnalysisContext,
    linkedExcelSheet,
    linkedExcelAllSheets,
    multimodalStaging,
    artifactStaging,
    multimodalPendingCount,
    stageArtifactFiles,
    removeArtifactFile,
    removeMultimodalFile,
    excelSheetOptions,
    resolveExcelAnalysisContextForRequest,
    injectExcelContextPayload,
    consumeMultimodalIntoPlannerContext,
    onMultimodalFileChange,
    stageMultimodalFiles,
    bindExcelSheetToChat,
    bindAllExcelSheetsToChat,
    persistExcelAnalysisContextForSession: (sid: string, ctx: Record<string, unknown> | null) => persistExcelAnalysisContext(sid, ctx),
  }
}
