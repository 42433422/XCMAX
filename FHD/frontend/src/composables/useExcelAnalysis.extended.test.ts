import { describe, it, expect, vi, beforeEach } from 'vitest'
import { buildExcelNextStepPrompt, useExcelAnalysis } from './useExcelAnalysis'

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
    expect(addMessage.mock.calls.some((call) => String(call[0]).includes('接下来你想让我做什么？'))).toBe(true)
    expect(api.excelAnalyzeUploading.value).toBe(false)
  })

  it('asks a contextual but open-ended next-step question after analyzing a delivery workbook', () => {
    const prompt = buildExcelNextStepPrompt('国圣化工.xlsx', {
      sheets: [
        { sheet_index: 1, sheet_name: '国圣' },
        { sheet_index: 2, sheet_name: '出货记录' },
        { sheet_index: 3, sheet_name: '借原材料明细' },
      ],
      preview_data: { sheet_name: '国圣', sheet_names: ['国圣', '出货记录', '借原材料明细'] },
    })

    expect(prompt).toContain('我已经读完「国圣化工.xlsx」')
    expect(prompt).toContain('国圣、出货记录、借原材料明细')
    expect(prompt).toContain('接下来你想让我做什么？')
    expect(prompt).toContain('发货或出货记录')
    expect(prompt).toContain('借入借出、原材料或库存明细')
    expect(prompt).toContain('可以直接用自己的话说')
    expect(prompt).toContain('涉及业务数据写入时，会再等你确认')
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
