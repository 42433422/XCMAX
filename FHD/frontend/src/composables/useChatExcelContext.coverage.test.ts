/**
 * Coverage ramp 测试：useChatExcelContext
 *
 * 目标：覆盖 useChatExcelContext.ts 中所有分支
 * - resolveExcelAnalysisContextForRequest（缓存命中/未命中/持久化恢复/空 sessionId）
 * - excelSheetOptions computed
 * - injectExcelContextPayload（无上下文/全部工作表/单表/预览/文件路径）
 * - consumeMultimodalIntoPlannerContext（空/非空）
 * - onMultimodalFileChange（无文件/错误/成功/超过6个截断）
 * - bindExcelSheetToChat（无效输入/有效输入）
 * - bindAllExcelSheetsToChat（无上下文/无工作表/成功）
 * - persistExcelAnalysisContextForSession
 *
 * 铁律3：覆盖 happy path、空值/None、边界值、异常路径
 * 铁律4：仅 mock 外部边界（useChatPersistence / multimodalAttachments），被测 composable 真实调用
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { ref } from 'vue'
import { useChatExcelContext } from './useChatExcelContext'

// ── mock 外部边界 ──────────────────────────────────────────────────
const mockReadPersistedExcelAnalysisContext = vi.fn()
const mockPersistExcelAnalysisContext = vi.fn()
const mockResolveExcelFilePathFromAnalysis = vi.fn()
const mockResolveExcelSheetOptionsFromContext = vi.fn()
const mockResolveLinkedSheetGridPreview = vi.fn()
const mockFilesToMultimodalRows = vi.fn()

vi.mock('./useChatPersistence', () => ({
  readPersistedExcelAnalysisContext: (...args: unknown[]) =>
    mockReadPersistedExcelAnalysisContext(...args),
  persistExcelAnalysisContext: (...args: unknown[]) =>
    mockPersistExcelAnalysisContext(...args),
  resolveExcelFilePathFromAnalysis: (...args: unknown[]) =>
    mockResolveExcelFilePathFromAnalysis(...args),
  resolveExcelSheetOptionsFromContext: (...args: unknown[]) =>
    mockResolveExcelSheetOptionsFromContext(...args),
  resolveLinkedSheetGridPreview: (...args: unknown[]) =>
    mockResolveLinkedSheetGridPreview(...args),
}))

vi.mock('@/utils/multimodalAttachments', () => ({
  filesToMultimodalRows: (...args: unknown[]) => mockFilesToMultimodalRows(...args),
}))

// ── helpers ──────────────────────────────────────────────────────

/** 构造 composable 依赖 */
function makeDeps(
  overrides: Partial<{
    sessionId: string
    addAndSaveMessage: ReturnType<typeof vi.fn>
  }> = {},
) {
  const sessionId = ref(overrides.sessionId ?? 'session-1')
  const addAndSaveMessage =
    overrides.addAndSaveMessage ?? vi.fn().mockResolvedValue(undefined)
  return { sessionId, addAndSaveMessage }
}

/** 构造工作表对象 */
function makeSheet(name: string, index: number) {
  return { sheet_name: name, sheet_index: index }
}

/** 构造多模态附件行 */
function makeRow(filename: string, kind: 'image' | 'pdf' = 'image') {
  return {
    kind,
    filename,
    mime_type: kind === 'pdf' ? 'application/pdf' : 'image/png',
    data_url: `data:${kind === 'pdf' ? 'application/pdf' : 'image/png'};base64,xxx`,
  }
}

/** 构造文件输入事件 */
function makeFileInputEvent(files: { name: string }[] | null) {
  const el: Record<string, unknown> = {
    files: files ? { length: files.length, item: (i: number) => files[i] } : null,
    value: 'initial',
  }
  return { target: el } as unknown as Event
}

describe('useChatExcelContext — coverage ramp', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // 默认返回值
    mockReadPersistedExcelAnalysisContext.mockReturnValue(null)
    mockPersistExcelAnalysisContext.mockReturnValue(undefined)
    mockResolveExcelFilePathFromAnalysis.mockReturnValue('')
    mockResolveExcelSheetOptionsFromContext.mockReturnValue([])
    mockResolveLinkedSheetGridPreview.mockReturnValue(null)
    mockFilesToMultimodalRows.mockResolvedValue({ ok: true, rows: [] })
  })

  // ── resolveExcelAnalysisContextForRequest ──────────────────────

  describe('resolveExcelAnalysisContextForRequest', () => {
    it('缓存命中时直接返回缓存值，不读持久化', () => {
      const ctx = useChatExcelContext(makeDeps())
      const cached = { foo: 'bar' }
      ctx.lastExcelAnalysisContext.value = cached
      expect(ctx.resolveExcelAnalysisContextForRequest()).toStrictEqual(cached)
      expect(mockReadPersistedExcelAnalysisContext).not.toHaveBeenCalled()
    })

    it('缓存未命中且持久化有值时恢复并缓存', () => {
      const ctx = useChatExcelContext(makeDeps({ sessionId: 'sid-1' }))
      const persisted = { file_path: '/a.xlsx' }
      mockReadPersistedExcelAnalysisContext.mockReturnValue(persisted)
      expect(ctx.resolveExcelAnalysisContextForRequest()).toStrictEqual(persisted)
      expect(ctx.lastExcelAnalysisContext.value).toStrictEqual(persisted)
      expect(mockReadPersistedExcelAnalysisContext).toHaveBeenCalledWith('sid-1')
    })

    it('sessionId 为空字符串时使用 default 作为 key', () => {
      const ctx = useChatExcelContext(makeDeps({ sessionId: '' }))
      ctx.resolveExcelAnalysisContextForRequest()
      expect(mockReadPersistedExcelAnalysisContext).toHaveBeenCalledWith('default')
    })

    it('sessionId 为纯空白时使用 default 作为 key', () => {
      const ctx = useChatExcelContext(makeDeps({ sessionId: '   ' }))
      ctx.resolveExcelAnalysisContextForRequest()
      expect(mockReadPersistedExcelAnalysisContext).toHaveBeenCalledWith('default')
    })

    it('缓存未命中且持久化无值时返回 null', () => {
      const ctx = useChatExcelContext(makeDeps())
      mockReadPersistedExcelAnalysisContext.mockReturnValue(null)
      expect(ctx.resolveExcelAnalysisContextForRequest()).toBeNull()
    })
  })

  // ── excelSheetOptions computed ────────────────────────────────

  describe('excelSheetOptions computed', () => {
    it('根据上下文解析工作表选项', () => {
      const ctx = useChatExcelContext(makeDeps())
      ctx.lastExcelAnalysisContext.value = { preview_data: {} }
      const sheets = [makeSheet('S1', 1)]
      mockResolveExcelSheetOptionsFromContext.mockReturnValue(sheets)
      expect(ctx.excelSheetOptions.value).toBe(sheets)
      expect(mockResolveExcelSheetOptionsFromContext).toHaveBeenCalledWith({
        preview_data: {},
      })
    })

    it('无上下文时返回空数组', () => {
      const ctx = useChatExcelContext(makeDeps())
      mockResolveExcelSheetOptionsFromContext.mockReturnValue([])
      expect(ctx.excelSheetOptions.value).toEqual([])
    })
  })

  // ── injectExcelContextPayload ─────────────────────────────────

  describe('injectExcelContextPayload', () => {
    it('无 Excel 上下文时返回 false 且不注入', () => {
      const ctx = useChatExcelContext(makeDeps())
      mockReadPersistedExcelAnalysisContext.mockReturnValue(null)
      const payload: Record<string, unknown> = {}
      const parts: string[] = []
      const result = ctx.injectExcelContextPayload(payload, parts)
      expect(result).toBe(false)
      expect(payload).toEqual({})
      expect(parts).toEqual([])
    })

    it('有上下文但无关联表时仅注入基础上下文', () => {
      const ctx = useChatExcelContext(makeDeps())
      const excelCtx = { preview_data: {} }
      ctx.lastExcelAnalysisContext.value = excelCtx
      mockResolveExcelFilePathFromAnalysis.mockReturnValue('')
      mockResolveExcelSheetOptionsFromContext.mockReturnValue([])
      const payload: Record<string, unknown> = {}
      const parts: string[] = []
      const result = ctx.injectExcelContextPayload(payload, parts)
      expect(result).toBe(true)
      expect(payload.excel_analysis).toStrictEqual(excelCtx)
      expect(parts).toContain('Excel上下文 1 份')
      expect(payload.excel_file_path).toBeUndefined()
    })

    it('有文件路径时注入 excel_file_path', () => {
      const ctx = useChatExcelContext(makeDeps())
      const excelCtx = { preview_data: {} }
      ctx.lastExcelAnalysisContext.value = excelCtx
      mockResolveExcelFilePathFromAnalysis.mockReturnValue('/path/to/file.xlsx')
      mockResolveExcelSheetOptionsFromContext.mockReturnValue([])
      const payload: Record<string, unknown> = {}
      const parts: string[] = []
      ctx.injectExcelContextPayload(payload, parts)
      expect(payload.excel_file_path).toBe('/path/to/file.xlsx')
    })

    it('全部工作表模式且有预览时注入预览列表', () => {
      const ctx = useChatExcelContext(makeDeps())
      const excelCtx = { preview_data: {} }
      ctx.lastExcelAnalysisContext.value = excelCtx
      const sheets = [makeSheet('S1', 1), makeSheet('S2', 2)]
      mockResolveExcelSheetOptionsFromContext.mockReturnValue(sheets)
      const preview = { sheet_name: 'S1', preview_text: '...' }
      mockResolveLinkedSheetGridPreview.mockReturnValue(preview)
      ctx.linkedExcelAllSheets.value = true
      const payload: Record<string, unknown> = {}
      const parts: string[] = []
      const result = ctx.injectExcelContextPayload(payload, parts)
      expect(result).toBe(true)
      expect(payload.excel_analysis_select_all_sheets).toBe(true)
      expect(payload.excel_analysis_selected_sheets).toBe(sheets)
      expect(payload.excel_linked_grid_previews).toEqual([preview, preview])
      expect(parts).toContain('已关联全部工作表 2 个')
      expect(parts).toContain('真实网格预览 2 份')
    })

    it('全部工作表模式但无预览时不注入预览', () => {
      const ctx = useChatExcelContext(makeDeps())
      const excelCtx = { preview_data: {} }
      ctx.lastExcelAnalysisContext.value = excelCtx
      const sheets = [makeSheet('S1', 1)]
      mockResolveExcelSheetOptionsFromContext.mockReturnValue(sheets)
      mockResolveLinkedSheetGridPreview.mockReturnValue(null)
      ctx.linkedExcelAllSheets.value = true
      const payload: Record<string, unknown> = {}
      const parts: string[] = []
      ctx.injectExcelContextPayload(payload, parts)
      expect(payload.excel_linked_grid_previews).toBeUndefined()
      expect(parts).toContain('已关联全部工作表 1 个')
      expect(parts).not.toContain('真实网格预览 1 份')
    })

    it('全部工作表模式但 allSheets 为空时不进入全部模式分支', () => {
      const ctx = useChatExcelContext(makeDeps())
      const excelCtx = { preview_data: {} }
      ctx.lastExcelAnalysisContext.value = excelCtx
      mockResolveExcelSheetOptionsFromContext.mockReturnValue([])
      ctx.linkedExcelAllSheets.value = true
      const payload: Record<string, unknown> = {}
      const parts: string[] = []
      ctx.injectExcelContextPayload(payload, parts)
      // allSheets.length 为 0，不进入全部模式分支
      expect(payload.excel_analysis_select_all_sheets).toBeUndefined()
    })

    it('单表模式且有预览时注入单表预览', () => {
      const ctx = useChatExcelContext(makeDeps())
      const excelCtx = { preview_data: {} }
      ctx.lastExcelAnalysisContext.value = excelCtx
      mockResolveExcelSheetOptionsFromContext.mockReturnValue([])
      const preview = { sheet_name: 'S1', preview_text: '...' }
      mockResolveLinkedSheetGridPreview.mockReturnValue(preview)
      ctx.linkedExcelSheet.value = makeSheet('Sheet1', 2)
      const payload: Record<string, unknown> = {}
      const parts: string[] = []
      const result = ctx.injectExcelContextPayload(payload, parts)
      expect(result).toBe(true)
      expect(payload.excel_analysis_selected_sheet).toEqual({
        sheet_name: 'Sheet1',
        sheet_index: 2,
      })
      expect(payload.preferred_sheet_name).toBe('Sheet1')
      expect(payload.preferred_sheet_index).toBe(2)
      expect(payload.excel_linked_grid_preview).toBe(preview)
      expect(parts).toContain('已关联表 2:Sheet1')
      expect(parts).toContain('真实网格预览 1 份')
    })

    it('单表模式但无预览时不注入预览', () => {
      const ctx = useChatExcelContext(makeDeps())
      const excelCtx = { preview_data: {} }
      ctx.lastExcelAnalysisContext.value = excelCtx
      mockResolveExcelSheetOptionsFromContext.mockReturnValue([])
      mockResolveLinkedSheetGridPreview.mockReturnValue(null)
      ctx.linkedExcelSheet.value = makeSheet('Sheet1', 2)
      const payload: Record<string, unknown> = {}
      const parts: string[] = []
      ctx.injectExcelContextPayload(payload, parts)
      expect(payload.excel_linked_grid_preview).toBeUndefined()
      expect(parts).toContain('已关联表 2:Sheet1')
      expect(parts).not.toContain('真实网格预览 1 份')
    })
  })

  // ── consumeMultimodalIntoPlannerContext ───────────────────────

  describe('consumeMultimodalIntoPlannerContext', () => {
    it('无附件时直接返回不注入', () => {
      const ctx = useChatExcelContext(makeDeps())
      const payload: Record<string, unknown> = {}
      const parts: string[] = []
      ctx.consumeMultimodalIntoPlannerContext(payload, parts)
      expect(payload.multimodal_attachments).toBeUndefined()
      expect(parts).toEqual([])
    })

    it('有附件时注入并清空暂存', () => {
      const ctx = useChatExcelContext(makeDeps())
      const rows = [makeRow('a.png'), makeRow('b.pdf', 'pdf')]
      ctx.multimodalStaging.value = [...rows]
      const payload: Record<string, unknown> = {}
      const parts: string[] = []
      ctx.consumeMultimodalIntoPlannerContext(payload, parts)
      expect(payload.multimodal_attachments).toHaveLength(2)
      // 应该是浅拷贝
      expect(payload.multimodal_attachments).not.toBe(rows)
      expect(parts).toContain('多模态附件 2 个')
      expect(ctx.multimodalStaging.value).toEqual([])
    })
  })

  // ── onMultimodalFileChange ────────────────────────────────────

  describe('onMultimodalFileChange', () => {
    it('target 为 null 时直接返回', async () => {
      const addAndSaveMessage = vi.fn().mockResolvedValue(undefined)
      const ctx = useChatExcelContext(makeDeps({ addAndSaveMessage }))
      const ev = { target: null } as unknown as Event
      await ctx.onMultimodalFileChange(ev)
      expect(mockFilesToMultimodalRows).not.toHaveBeenCalled()
      expect(addAndSaveMessage).not.toHaveBeenCalled()
    })

    it('files 为 null 时直接返回', async () => {
      const addAndSaveMessage = vi.fn().mockResolvedValue(undefined)
      const ctx = useChatExcelContext(makeDeps({ addAndSaveMessage }))
      await ctx.onMultimodalFileChange(makeFileInputEvent(null))
      expect(mockFilesToMultimodalRows).not.toHaveBeenCalled()
      expect(addAndSaveMessage).not.toHaveBeenCalled()
    })

    it('files 为空数组（length=0）时直接返回', async () => {
      const addAndSaveMessage = vi.fn().mockResolvedValue(undefined)
      const ctx = useChatExcelContext(makeDeps({ addAndSaveMessage }))
      await ctx.onMultimodalFileChange(makeFileInputEvent([]))
      expect(mockFilesToMultimodalRows).not.toHaveBeenCalled()
      expect(addAndSaveMessage).not.toHaveBeenCalled()
    })

    it('转换失败时发送错误消息', async () => {
      const addAndSaveMessage = vi.fn().mockResolvedValue(undefined)
      const ctx = useChatExcelContext(makeDeps({ addAndSaveMessage }))
      mockFilesToMultimodalRows.mockResolvedValue({
        ok: false,
        error: '文件过大',
      })
      await ctx.onMultimodalFileChange(makeFileInputEvent([{ name: 'big.png' }]))
      expect(addAndSaveMessage).toHaveBeenCalledWith('[附件] 文件过大', 'ai')
      // 失败时不加入暂存
      expect(ctx.multimodalStaging.value).toEqual([])
    })

    it('转换成功时加入暂存并发送确认消息', async () => {
      const addAndSaveMessage = vi.fn().mockResolvedValue(undefined)
      const ctx = useChatExcelContext(makeDeps({ addAndSaveMessage }))
      const rows = [makeRow('a.png')]
      mockFilesToMultimodalRows.mockResolvedValue({ ok: true, rows })
      await ctx.onMultimodalFileChange(makeFileInputEvent([{ name: 'a.png' }]))
      expect(ctx.multimodalStaging.value).toHaveLength(1)
      expect(ctx.multimodalStaging.value[0].filename).toBe('a.png')
      expect(addAndSaveMessage).toHaveBeenCalledWith(
        expect.stringContaining('已加入 1 个文件'),
        'ai',
      )
    })

    it('转换成功消息包含所有文件名', async () => {
      const addAndSaveMessage = vi.fn().mockResolvedValue(undefined)
      const ctx = useChatExcelContext(makeDeps({ addAndSaveMessage }))
      const rows = [makeRow('a.png'), makeRow('b.png')]
      mockFilesToMultimodalRows.mockResolvedValue({ ok: true, rows })
      await ctx.onMultimodalFileChange(makeFileInputEvent([{ name: 'a.png' }]))
      const callArgs = addAndSaveMessage.mock.calls[0][0] as string
      expect(callArgs).toContain('a.png')
      expect(callArgs).toContain('b.png')
    })

    it('超过 6 个附件时截断到最近 6 个', async () => {
      const addAndSaveMessage = vi.fn().mockResolvedValue(undefined)
      const ctx = useChatExcelContext(makeDeps({ addAndSaveMessage }))
      // 先放入 4 个
      ctx.multimodalStaging.value = Array.from({ length: 4 }, (_, i) =>
        makeRow(`old${i}.png`),
      )
      // 新增 4 个
      const newRows = Array.from({ length: 4 }, (_, i) => makeRow(`new${i}.png`))
      mockFilesToMultimodalRows.mockResolvedValue({ ok: true, rows: newRows })
      await ctx.onMultimodalFileChange(makeFileInputEvent([{ name: 'new0.png' }]))
      // 4 + 4 = 8, slice(-6) = 6
      expect(ctx.multimodalStaging.value).toHaveLength(6)
      // 应该保留最后 6 个（old2, old3, new0, new1, new2, new3）
      expect(ctx.multimodalStaging.value[0].filename).toBe('old2.png')
      expect(ctx.multimodalStaging.value[5].filename).toBe('new3.png')
    })

    it('清空 input 的 value', async () => {
      const ctx = useChatExcelContext(makeDeps())
      mockFilesToMultimodalRows.mockResolvedValue({ ok: true, rows: [] })
      const ev = makeFileInputEvent([{ name: 'a.png' }])
      await ctx.onMultimodalFileChange(ev)
      expect((ev.target as unknown as { value: string }).value).toBe('')
    })
  })

  // ── bindExcelSheetToChat ──────────────────────────────────────

  describe('bindExcelSheetToChat', () => {
    it('name 为空时不执行', async () => {
      const ctx = useChatExcelContext(makeDeps())
      const dispatchSpy = vi.spyOn(window, 'dispatchEvent')
      await ctx.bindExcelSheetToChat(makeSheet('', 1))
      expect(dispatchSpy).not.toHaveBeenCalled()
      dispatchSpy.mockRestore()
    })

    it('name 为纯空白时不执行', async () => {
      const ctx = useChatExcelContext(makeDeps())
      const dispatchSpy = vi.spyOn(window, 'dispatchEvent')
      await ctx.bindExcelSheetToChat(makeSheet('   ', 1))
      expect(dispatchSpy).not.toHaveBeenCalled()
      dispatchSpy.mockRestore()
    })

    it('index <= 0 时不执行', async () => {
      const ctx = useChatExcelContext(makeDeps())
      const dispatchSpy = vi.spyOn(window, 'dispatchEvent')
      await ctx.bindExcelSheetToChat(makeSheet('Sheet1', 0))
      expect(dispatchSpy).not.toHaveBeenCalled()
      dispatchSpy.mockRestore()
    })

    it('index 为负数时不执行', async () => {
      const ctx = useChatExcelContext(makeDeps())
      const dispatchSpy = vi.spyOn(window, 'dispatchEvent')
      await ctx.bindExcelSheetToChat(makeSheet('Sheet1', -1))
      expect(dispatchSpy).not.toHaveBeenCalled()
      dispatchSpy.mockRestore()
    })

    it('sheet 为 null 时不执行', async () => {
      const ctx = useChatExcelContext(makeDeps())
      const dispatchSpy = vi.spyOn(window, 'dispatchEvent')
      await ctx.bindExcelSheetToChat(
        null as unknown as Parameters<typeof ctx.bindExcelSheetToChat>[0],
      )
      expect(dispatchSpy).not.toHaveBeenCalled()
      dispatchSpy.mockRestore()
    })

    it('有效输入时绑定单表并发送两个事件', async () => {
      const ctx = useChatExcelContext(makeDeps())
      ctx.lastExcelAnalysisContext.value = { preview_data: {} }
      const dispatchSpy = vi.spyOn(window, 'dispatchEvent')
      await ctx.bindExcelSheetToChat(makeSheet('Sheet1', 2))
      expect(ctx.linkedExcelAllSheets.value).toBe(false)
      expect(ctx.linkedExcelSheet.value).toEqual({
        sheet_name: 'Sheet1',
        sheet_index: 2,
      })
      // 2 个事件
      expect(dispatchSpy).toHaveBeenCalledTimes(2)
      const firstEvent = dispatchSpy.mock.calls[0][0] as CustomEvent
      expect(firstEvent.type).toBe('xcagi:excel-sheet-context')
      expect(firstEvent.detail.select_all_sheets).toBe(false)
      expect(firstEvent.detail.selected_sheet).toEqual({
        sheet_name: 'Sheet1',
        sheet_index: 2,
      })
      expect(firstEvent.detail.excel_analysis).toEqual({ preview_data: {} })
      const secondEvent = dispatchSpy.mock.calls[1][0] as CustomEvent
      expect(secondEvent.type).toBe('xcagi:open-assistant-float')
      expect(secondEvent.detail.forceOpen).toBe(true)
      dispatchSpy.mockRestore()
    })
  })

  // ── bindAllExcelSheetsToChat ──────────────────────────────────

  describe('bindAllExcelSheetsToChat', () => {
    it('无 Excel 上下文时不执行', async () => {
      const ctx = useChatExcelContext(makeDeps())
      mockReadPersistedExcelAnalysisContext.mockReturnValue(null)
      const dispatchSpy = vi.spyOn(window, 'dispatchEvent')
      await ctx.bindAllExcelSheetsToChat()
      expect(dispatchSpy).not.toHaveBeenCalled()
      dispatchSpy.mockRestore()
    })

    it('无工作表时不执行', async () => {
      const ctx = useChatExcelContext(makeDeps())
      ctx.lastExcelAnalysisContext.value = { preview_data: {} }
      mockResolveExcelSheetOptionsFromContext.mockReturnValue([])
      const dispatchSpy = vi.spyOn(window, 'dispatchEvent')
      await ctx.bindAllExcelSheetsToChat()
      expect(dispatchSpy).not.toHaveBeenCalled()
      dispatchSpy.mockRestore()
    })

    it('有上下文和工作表时绑定全部并发送事件', async () => {
      const ctx = useChatExcelContext(makeDeps())
      const excelCtx = { preview_data: {} }
      ctx.lastExcelAnalysisContext.value = excelCtx
      const sheets = [makeSheet('S1', 1), makeSheet('S2', 2)]
      mockResolveExcelSheetOptionsFromContext.mockReturnValue(sheets)
      const dispatchSpy = vi.spyOn(window, 'dispatchEvent')
      await ctx.bindAllExcelSheetsToChat()
      expect(ctx.linkedExcelAllSheets.value).toBe(true)
      expect(ctx.linkedExcelSheet.value).toEqual(sheets[0])
      expect(dispatchSpy).toHaveBeenCalledTimes(2)
      const firstEvent = dispatchSpy.mock.calls[0][0] as CustomEvent
      expect(firstEvent.type).toBe('xcagi:excel-sheet-context')
      expect(firstEvent.detail.select_all_sheets).toBe(true)
      expect(firstEvent.detail.selected_sheets).toBe(sheets)
      expect(firstEvent.detail.selected_sheet).toEqual(sheets[0])
      expect(firstEvent.detail.excel_analysis).toStrictEqual(excelCtx)
      const secondEvent = dispatchSpy.mock.calls[1][0] as CustomEvent
      expect(secondEvent.type).toBe('xcagi:open-assistant-float')
      dispatchSpy.mockRestore()
    })
  })

  // ── persistExcelAnalysisContextForSession ─────────────────────

  describe('persistExcelAnalysisContextForSession', () => {
    it('委托给 persistExcelAnalysisContext（有值）', () => {
      const ctx = useChatExcelContext(makeDeps())
      const ctxData = { foo: 'bar' }
      ctx.persistExcelAnalysisContextForSession('sid-1', ctxData)
      expect(mockPersistExcelAnalysisContext).toHaveBeenCalledWith('sid-1', ctxData)
    })

    it('委托给 persistExcelAnalysisContext（null）', () => {
      const ctx = useChatExcelContext(makeDeps())
      ctx.persistExcelAnalysisContextForSession('sid-1', null)
      expect(mockPersistExcelAnalysisContext).toHaveBeenCalledWith('sid-1', null)
    })
  })

  // ── multimodalPendingCount computed ──────────────────────────

  describe('multimodalPendingCount computed', () => {
    it('初始为 0', () => {
      const ctx = useChatExcelContext(makeDeps())
      expect(ctx.multimodalPendingCount.value).toBe(0)
    })

    it('反映暂存区大小', () => {
      const ctx = useChatExcelContext(makeDeps())
      ctx.multimodalStaging.value = [makeRow('a.png'), makeRow('b.png')]
      expect(ctx.multimodalPendingCount.value).toBe(2)
    })
  })

  // ── 返回值完整性 ──────────────────────────────────────────────

  describe('返回值完整性', () => {
    it('返回所有预期的属性和方法', () => {
      const ctx = useChatExcelContext(makeDeps())
      expect(ctx).toHaveProperty('lastExcelAnalysisContext')
      expect(ctx).toHaveProperty('linkedExcelSheet')
      expect(ctx).toHaveProperty('linkedExcelAllSheets')
      expect(ctx).toHaveProperty('multimodalStaging')
      expect(ctx).toHaveProperty('multimodalPendingCount')
      expect(ctx).toHaveProperty('excelSheetOptions')
      expect(ctx).toHaveProperty('resolveExcelAnalysisContextForRequest')
      expect(ctx).toHaveProperty('injectExcelContextPayload')
      expect(ctx).toHaveProperty('consumeMultimodalIntoPlannerContext')
      expect(ctx).toHaveProperty('onMultimodalFileChange')
      expect(ctx).toHaveProperty('bindExcelSheetToChat')
      expect(ctx).toHaveProperty('bindAllExcelSheetsToChat')
      expect(ctx).toHaveProperty('persistExcelAnalysisContextForSession')
    })
  })
})
