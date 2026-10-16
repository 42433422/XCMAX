import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { useExcelAnalysis } from './useExcelAnalysis'

const addMessage = vi.fn()
const saveMessage = vi.fn().mockResolvedValue(undefined)

function makeMessages() {
  return { addMessage, saveMessage }
}

describe('useExcelAnalysis - extended', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    document.cookie = 'csrf_token=test-csrf'
    global.fetch = vi.fn()
  })

  it('triggerExcelAnalyzeUpload is alias for triggerUpload', () => {
    const api = useExcelAnalysis(makeMessages())
    const click = vi.fn()
    api.excelAnalyzeInputRef.value = { click } as unknown as HTMLInputElement
    api.triggerExcelAnalyzeUpload()
    expect(click).toHaveBeenCalled()
  })

  it('triggerUpload does nothing when already uploading', () => {
    const api = useExcelAnalysis(makeMessages())
    api.excelAnalyzeUploading.value = true
    const click = vi.fn()
    api.excelAnalyzeInputRef.value = { click } as unknown as HTMLInputElement
    api.triggerUpload()
    expect(click).not.toHaveBeenCalled()
  })

  it('triggerUpload does nothing when inputRef is null', () => {
    const api = useExcelAnalysis(makeMessages())
    api.excelAnalyzeInputRef.value = null
    expect(() => api.triggerUpload()).not.toThrow()
  })

  it('onExcelAnalyzeFileChange ignores non-xlsx files', async () => {
    const api = useExcelAnalysis(makeMessages())
    const cb = vi.fn()
    api.setOnMultimodalFileChangeCallback(cb)
    const file = new File(['content'], 'test.txt', { type: 'text/plain' })
    const input = { files: [file], value: '' } as unknown as HTMLInputElement
    await api.onExcelAnalyzeFileChange({ target: input } as unknown as Event)
    expect(cb).toHaveBeenCalled()
    expect(api.excelAnalyzeUploading.value).toBe(false)
  })

  it('keeps multimodal files available until the callback snapshots them', async () => {
    const api = useExcelAnalysis(makeMessages())
    const file = new File(['image'], 'test.png', { type: 'image/png' })
    let liveFiles: File[] = [file]
    let inputValue = '/fake/test.png'
    const input = {
      get files() {
        return liveFiles
      },
      get value() {
        return inputValue
      },
      set value(next: string) {
        inputValue = next
        if (!next) liveFiles = []
      },
    } as unknown as HTMLInputElement
    const cb = vi.fn(async (event: Event) => {
      expect((event.target as HTMLInputElement).files?.[0]).toBe(file)
    })
    api.setOnMultimodalFileChangeCallback(cb)

    await api.onExcelAnalyzeFileChange({ target: input } as unknown as Event)

    expect(cb).toHaveBeenCalledOnce()
    expect(input.value).toBe('')
  })

  it('onExcelAnalyzeFileChange ignores when no file', async () => {
    const api = useExcelAnalysis(makeMessages())
    const input = { files: [], value: '' } as unknown as HTMLInputElement
    await api.onExcelAnalyzeFileChange({ target: input } as unknown as Event)
    expect(addMessage).not.toHaveBeenCalled()
  })

  it('onExcelAnalyzeFileChange processes xlsx file successfully', async () => {
    const onAnalyzed = vi.fn()
    const onAnalyzeStart = vi.fn()
    const onAnalyzeDone = vi.fn()
    const onAnalyzeProgress = vi.fn()

    vi.mocked(global.fetch).mockResolvedValueOnce({
      ok: true,
      text: async () =>
        JSON.stringify({
          success: true,
          fields: [
            { name: '姓名', label: '姓名' },
            { name: '年龄', label: '年龄' },
          ],
          preview_data: {
            sheet_name: 'Sheet1',
            sample_rows: [{ 姓名: '张三', 年龄: 28 }],
            grid_preview: {
              rows: [
                ['姓名', '年龄'],
                ['张三', 28],
              ],
            },
            grid_style_cache: { styles: {}, cell_style_refs: {} },
            tables: [],
          },
        }),
    } as unknown as Response)

    const api = useExcelAnalysis(makeMessages(), {
      onAnalyzed,
      onAnalyzeStart,
      onAnalyzeDone,
      onAnalyzeProgress,
    })

    const file = new File(['data'], 'test.xlsx', {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    })
    const input = { files: [file], value: '' } as unknown as HTMLInputElement
    await api.onExcelAnalyzeFileChange({ target: input } as unknown as Event)

    expect(onAnalyzeStart).toHaveBeenCalledWith({ fileName: 'test.xlsx' })
    expect(onAnalyzed).toHaveBeenCalledWith(expect.objectContaining({ fileName: 'test.xlsx' }))
    expect(onAnalyzeDone).toHaveBeenCalledWith({ fileName: 'test.xlsx', success: true })
    expect(api.excelAnalyzeUploading.value).toBe(false)
  })

  it('onExcelAnalyzeFileChange handles server error', async () => {
    const onAnalyzeDone = vi.fn()

    vi.mocked(global.fetch).mockResolvedValueOnce({
      ok: false,
      status: 500,
      text: async () => JSON.stringify({ success: false, message: '解析失败' }),
    } as unknown as Response)

    const api = useExcelAnalysis(makeMessages(), { onAnalyzeDone })
    const file = new File(['data'], 'test.xlsx', {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    })
    const input = { files: [file], value: '' } as unknown as HTMLInputElement
    await api.onExcelAnalyzeFileChange({ target: input } as unknown as Event)

    expect(onAnalyzeDone).toHaveBeenCalledWith(expect.objectContaining({ success: false }))
    expect(api.excelAnalyzeUploading.value).toBe(false)
  })

  it('onExcelAnalyzeFileChange handles network error', async () => {
    const onAnalyzeDone = vi.fn()

    vi.mocked(global.fetch).mockRejectedValueOnce(new TypeError('Failed to fetch'))

    const api = useExcelAnalysis(makeMessages(), { onAnalyzeDone })
    const file = new File(['data'], 'test.xlsx', {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    })
    const input = { files: [file], value: '' } as unknown as HTMLInputElement
    await api.onExcelAnalyzeFileChange({ target: input } as unknown as Event)

    expect(onAnalyzeDone).toHaveBeenCalledWith(expect.objectContaining({ success: false }))
  })

  it('onExcelAnalyzeFileChange handles abort/timeout', async () => {
    const onAnalyzeDone = vi.fn()

    vi.mocked(global.fetch).mockRejectedValue(Object.assign(new Error('Aborted'), { name: 'AbortError' }))

    const api = useExcelAnalysis(makeMessages(), { onAnalyzeDone })
    const file = new File(['data'], 'test.xlsx', {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    })
    const input = { files: [file], value: '' } as unknown as HTMLInputElement
    await api.onExcelAnalyzeFileChange({ target: input } as unknown as Event)

    expect(onAnalyzeDone).toHaveBeenCalledWith(expect.objectContaining({ success: false }))
  })

  it('onExcelAnalyzeFileChange calls onAnalyzeProgress during processing', async () => {
    const onAnalyzeProgress = vi.fn()

    vi.mocked(global.fetch).mockResolvedValueOnce({
      ok: true,
      text: async () =>
        JSON.stringify({
          success: true,
          fields: [],
          preview_data: {
            sheet_name: 'Sheet1',
            grid_preview: { rows: [] },
            grid_style_cache: { styles: {}, cell_style_refs: {} },
            tables: [],
          },
        }),
    } as unknown as Response)

    const api = useExcelAnalysis(makeMessages(), { onAnalyzeProgress })
    const file = new File(['data'], 'test.xlsx', {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    })
    const input = { files: [file], value: '' } as unknown as HTMLInputElement
    await api.onExcelAnalyzeFileChange({ target: input } as unknown as Event)

    expect(onAnalyzeProgress).toHaveBeenCalledWith(expect.objectContaining({ fileName: 'test.xlsx', step: expect.any(String) }))
  })

  it('summarizeExcelAnalysisResult handles empty result via file upload', async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce({
      ok: true,
      text: async () =>
        JSON.stringify({
          success: true,
          fields: [],
          preview_data: {
            sheet_name: 'Sheet1',
            grid_preview: { rows: [] },
            grid_style_cache: { styles: {}, cell_style_refs: {} },
            tables: [],
          },
        }),
    } as unknown as Response)

    const api = useExcelAnalysis(makeMessages())
    const file = new File(['data'], 'test.xlsx', {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    })
    const input = { files: [file], value: '' } as unknown as HTMLInputElement
    await api.onExcelAnalyzeFileChange({ target: input } as unknown as Event)
    // The summary should contain "Excel 分析完成"
    const calls = addMessage.mock.calls
    const summaryCall = calls.find((c) => String(c[0]).includes('Excel 分析完成'))
    expect(summaryCall).toBeDefined()
  })

  it('summarizeExcelAnalysisResult handles result with sheets via file upload', async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce({
      ok: true,
      text: async () =>
        JSON.stringify({
          success: true,
          sheets: [
            {
              sheet_index: 1,
              sheet_name: '销售数据',
              fields: [
                { name: '产品', label: '产品' },
                { name: '金额', label: '金额' },
              ],
              sample_rows: [{ 产品: 'A', 金额: 100 }],
              grid_preview: {
                rows: [
                  ['产品', '金额'],
                  ['A', 100],
                ],
              },
              style_cache: { styles: {}, cell_style_refs: { '0_0': 1 } },
              tables: [{ table_index: 1, fields: [{ name: '产品' }], sample_rows: [] }],
            },
          ],
          preview_data: {
            sheet_name: '销售数据',
            sheet_names: ['销售数据'],
            grid_preview: { rows: [['产品', '金额']] },
            grid_style_cache: { styles: {}, cell_style_refs: {} },
            tables: [],
          },
          fields: [{ name: '产品', label: '产品' }],
        }),
    } as unknown as Response)

    const api = useExcelAnalysis(makeMessages())
    const file = new File(['data'], 'test.xlsx', {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    })
    const input = { files: [file], value: '' } as unknown as HTMLInputElement
    await api.onExcelAnalyzeFileChange({ target: input } as unknown as Event)
    // The summary should contain sheet name
    const calls = addMessage.mock.calls
    const summaryCall = calls.find((c) => String(c[0]).includes('销售数据'))
    expect(summaryCall).toBeDefined()
  })

  it('onExcelAnalyzeFileChange processes xlsm file', async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce({
      ok: true,
      text: async () =>
        JSON.stringify({
          success: true,
          fields: [],
          preview_data: {
            sheet_name: 'Sheet1',
            grid_preview: { rows: [] },
            grid_style_cache: { styles: {}, cell_style_refs: {} },
            tables: [],
          },
        }),
    } as unknown as Response)

    const api = useExcelAnalysis(makeMessages())
    const file = new File(['data'], 'test.xlsm', {
      type: 'application/vnd.ms-excel.sheet.macroEnabled.12',
    })
    const input = { files: [file], value: '' } as unknown as HTMLInputElement
    await api.onExcelAnalyzeFileChange({ target: input } as unknown as Event)
    expect(addMessage).toHaveBeenCalled()
  })

  it('setOnMultimodalFileChangeCallback stores and uses callback', async () => {
    const api = useExcelAnalysis(makeMessages())
    const cb = vi.fn()
    api.setOnMultimodalFileChangeCallback(cb)

    // Non-xlsx file should trigger callback
    const file = new File(['data'], 'image.png', { type: 'image/png' })
    const input = { files: [file], value: '' } as unknown as HTMLInputElement
    const event = { target: input } as unknown as Event
    await api.onExcelAnalyzeFileChange(event)
    expect(cb).toHaveBeenCalledWith(event)
  })
})

describe('workbook detail fallback and response deadlines', () => {
  const file = new File(['workbook'], 'details.xlsx')
  const event = () => ({ target: { files: [file], value: 'selected' } }) as unknown as Event
  const response = (body: unknown, ok = true) => ({ ok, status: ok ? 200 : 500, text: async () => JSON.stringify(body) }) as Response
  beforeEach(() => { vi.clearAllMocks(); document.cookie = 'csrf_token=test-csrf'; global.fetch = vi.fn() })
  afterEach(() => vi.useRealTimers())
  it('fetches each missing sheet detail, preserves successful sheets and tolerates individual failures', async () => {
    const onAnalyzed = vi.fn(), progress = vi.fn(), done = vi.fn()
    const api = useExcelAnalysis(makeMessages(), { onAnalyzed, onAnalyzeProgress: progress, onAnalyzeDone: done })
    vi.mocked(fetch).mockResolvedValueOnce(response({ success: true, fields: [' Product '], preview_data: { sheet_names: ['Sales', ' ', 'Empty', 'Unavailable', 'Offline'] } }))
      .mockResolvedValueOnce(response({ success: true, fields: [{ label: 'Product' }], preview_data: { sample_rows: [{ Product: 'A' }], grid_preview: { rows: [['A']] }, grid_style_cache: { cell_style_refs: { A1: 'bold' } }, tables: [{ fields: ['Product'] }] } }))
      .mockResolvedValueOnce(response({ success: true }))
      .mockResolvedValueOnce(response({ success: false }, false))
      .mockRejectedValueOnce(new Error('offline')).mockRejectedValueOnce(new Error('offline'))
    await api.onExcelAnalyzeFileChange(event())
    expect(fetch).toHaveBeenCalledTimes(6)
    expect(vi.mocked(fetch).mock.calls.slice(1).map(([, init]) => (init!.body as FormData).get('sheet_name'))).toEqual(['Sales', 'Empty', 'Unavailable', 'Offline', 'Offline'])
    expect((vi.mocked(fetch).mock.calls[1][1]!.body as FormData).get('analyze_all_sheets')).toBe('false')
    const result = onAnalyzed.mock.calls[0][0]
    expect(result.result.sheets).toHaveLength(2)
    expect(result.result.preview_data.all_sheets).toEqual(result.result.sheets)
    expect(result.result.sheets[1]).toMatchObject({ sheet_index: 3, sheet_name: 'Empty', fields: [], sample_rows: [], tables: [] })
    expect(result.summary).toContain('样式缓存单元格：1')
    expect(result.summary).toContain('词条：Product')
    expect(progress).toHaveBeenCalledWith(expect.objectContaining({ step: '补全分表详情 5/5', progress: 100 }))
    expect(done).toHaveBeenCalledWith({ fileName: file.name, success: true })
    expect(api.excelAnalyzeUploading.value).toBe(false)
  })
  it.each(['', '{invalid'])('treats an empty or malformed response as a failed analysis: %j', async (body) => {
    const done = vi.fn(), api = useExcelAnalysis(makeMessages(), { onAnalyzeDone: done })
    vi.mocked(fetch).mockResolvedValueOnce({ ok: true, status: 200, text: async () => body } as Response)
    await api.onExcelAnalyzeFileChange(event())
    expect(done).toHaveBeenCalledWith({ fileName: file.name, success: false, message: 'Excel 分析失败：HTTP 200' })
    expect(api.excelAnalyzeUploading.value).toBe(false)
  })
  it('releases the uploading state if response-body reading stalls after a successful connection', async () => {
    vi.useFakeTimers()
    const done = vi.fn(), api = useExcelAnalysis(makeMessages(), { onAnalyzeDone: done })
    vi.mocked(fetch).mockResolvedValueOnce({ ok: true, text: () => new Promise(() => {}) } as unknown as Response)
    const pending = api.onExcelAnalyzeFileChange(event())
    await vi.advanceTimersByTimeAsync(120000); await pending
    expect(done).toHaveBeenCalledWith({ fileName: file.name, success: false, message: expect.stringContaining('响应读取超时（120 秒）') })
    expect(api.excelAnalyzeUploading.value).toBe(false)
    expect(vi.getTimerCount()).toBe(0)
  })
  it('aborts a stalled sheet extraction without discarding the valid workbook summary', async () => {
    vi.useFakeTimers()
    const analyzed = vi.fn(), api = useExcelAnalysis(makeMessages(), { onAnalyzed: analyzed })
    vi.mocked(fetch).mockResolvedValueOnce(response({ success: true, preview_data: { sheet_names: ['Slow', ' '] } }))
      .mockImplementationOnce((_url, init) => new Promise((_resolve, reject) => { init!.signal!.addEventListener('abort', () => reject(new DOMException('timeout', 'AbortError'))) }))
    const pending = api.onExcelAnalyzeFileChange(event())
    await vi.advanceTimersByTimeAsync(90000); await pending
    expect(analyzed).toHaveBeenCalledOnce()
    expect(analyzed.mock.calls[0][0].result.sheets).toBeUndefined()
    expect(api.excelAnalyzeUploading.value).toBe(false)
    expect(vi.getTimerCount()).toBe(0)
  })
})
