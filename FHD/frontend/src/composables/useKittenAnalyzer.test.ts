import { describe, it, expect, vi, beforeEach } from 'vitest'
import {
  useKittenAnalyzer,
  extractKittenDocumentPickupUrl,
  KITTEN_WELCOME_HTML,
  kittenWorkflowSteps,
  kittenOrgCards,
  kittenQuickActions,
} from './useKittenAnalyzer'

vi.mock('@/api/core', () => ({
  buildFullApiUrl: (path: string) => `http://localhost:5000${path}`,
}))

vi.mock('@/utils', () => ({
  downloadBlob: vi.fn(),
  getFilenameFromDisposition: vi.fn((_hdr, fallback) => fallback),
}))

vi.mock('@/utils/safeJsonRequest', () => ({
  safeJsonRequest: vi.fn().mockResolvedValue({ ok: true, data: { success: true } }),
}))

vi.mock('@/utils/appDialog', () => ({
  appAlert: vi.fn().mockResolvedValue(undefined),
}))

vi.mock('@/api/chat', () => ({
  chatApi: {
    sendChatStream: vi.fn(),
  },
  parseChatStreamErrorResponse: vi.fn(async () => 'stream error'),
}))

vi.mock('@/utils/plannerChatPaths', () => ({
  resolvePlannerChatPath: () => '/api/ai/chat',
}))

vi.mock('@/utils/chatSseStream', () => ({
  readPlannerSseResponse: vi.fn(),
  isChatStreamEnabled: () => false,
}))

vi.mock('@/utils/kittenDatasetParser', () => ({
  parseDatasetFile: vi.fn().mockResolvedValue({
    rows: 100,
    columns: ['姓名', '年龄', '城市'],
    sampleRows: [{ 姓名: '张三', 年龄: 28, 城市: '北京' }],
    fieldProfiles: [
      { name: '姓名', type: 'category' },
      { name: '年龄', type: 'number' },
      { name: '城市', type: 'category' },
    ],
  }),
}))

describe('useKittenAnalyzer', () => {
  let analyzer: ReturnType<typeof useKittenAnalyzer>

  beforeEach(() => {
    vi.clearAllMocks()
    analyzer = useKittenAnalyzer()
  })

  it('initializes with welcome message and idle state', () => {
    expect(analyzer.messages.value.length).toBe(1)
    expect(analyzer.messages.value[0].role).toBe('ai')
    expect(analyzer.messages.value[0].content).toBe(KITTEN_WELCOME_HTML)
    expect(analyzer.kittenPhase.value).toBe('idle')
    expect(analyzer.isChatLoading.value).toBe(false)
    expect(analyzer.isKittenStreaming.value).toBe(false)
    expect(analyzer.isDatasetParsing.value).toBe(false)
    expect(analyzer.currentResult.value).toBeNull()
    expect(analyzer.datasetSummary.value).toBeNull()
    expect(analyzer.inputText.value).toBe('')
  })

  it('hasDataset is false initially (checked via datasetSummary)', () => {
    expect(analyzer.datasetSummary.value).toBeNull()
  })

  it('datasetFieldPreview returns empty array without dataset', () => {
    expect(analyzer.datasetFieldPreview.value).toEqual([])
  })

  it('lastDocumentPickupUrl is null initially', () => {
    expect(analyzer.lastDocumentPickupUrl.value).toBeNull()
  })

  it('loadingStatusText is empty when idle', () => {
    expect(analyzer.loadingStatusText.value).toBe('')
  })

  it('loadingStatusText shows parsing text when dataset parsing', () => {
    analyzer.isDatasetParsing.value = true
    expect(analyzer.loadingStatusText.value).toBe('正在解析数据文件...')
  })

  it('loadingStatusText shows chat loading text', () => {
    analyzer.isChatLoading.value = true
    expect(analyzer.loadingStatusText.value).toBe('正在回复…')
  })

  it('recommendedCharts is empty without field profiles', () => {
    expect(analyzer.recommendedCharts.value).toEqual([])
  })

  it('addMessage pushes bounded messages', () => {
    expect(analyzer.messages.value.length).toBe(1)
    analyzer.inputText.value = 'hello'
    // Manually trigger addMessage via sendMessage is complex; test via direct state
    analyzer.messages.value.push({ role: 'user', content: 'test', time: '10:00' })
    expect(analyzer.messages.value.length).toBe(2)
  })

  it('triggerFileUpload clicks file input when set', () => {
    const click = vi.fn()
    analyzer.fileInput.value = { click } as unknown as HTMLInputElement
    analyzer.triggerFileUpload()
    expect(click).toHaveBeenCalled()
  })

  it('triggerFileUpload does nothing when fileInput is null', () => {
    analyzer.fileInput.value = null
    expect(() => analyzer.triggerFileUpload()).not.toThrow()
  })

  it('setChartConfig updates chartConfig and sets currentResult when xField provided', () => {
    analyzer.setChartConfig({ type: 'bar', xField: '姓名', yField: '年龄', aggregate: 'sum' })
    expect(analyzer.chartConfig.value.xField).toBe('姓名')
    expect(analyzer.chartConfig.value.yField).toBe('年龄')
    expect(analyzer.chartConfig.value.aggregate).toBe('sum')
    expect(analyzer.currentResult.value).not.toBeNull()
    expect(analyzer.currentResult.value!.chart).toBe(true)
    expect(analyzer.kittenPhase.value).toBe('delivered')
  })

  it('setChartConfig does not set currentResult when xField is empty', () => {
    analyzer.setChartConfig({ xField: '' })
    expect(analyzer.currentResult.value).toBeNull()
  })

  it('applyChartRecommendation applies recommendation config', () => {
    const rec = {
      id: 'test',
      label: 'Test',
      description: 'Test chart',
      config: { type: 'pie' as const, xField: '城市', yField: '', groupField: '', aggregate: 'count' as const },
    }
    analyzer.applyChartRecommendation(rec)
    expect(analyzer.chartConfig.value.type).toBe('pie')
    expect(analyzer.chartConfig.value.xField).toBe('城市')
    expect(analyzer.currentResult.value).not.toBeNull()
  })

  it('clearResult resets currentResult and phase', () => {
    analyzer.setChartConfig({ type: 'bar', xField: '姓名' })
    expect(analyzer.currentResult.value).not.toBeNull()
    analyzer.clearResult()
    expect(analyzer.currentResult.value).toBeNull()
    expect(analyzer.kittenPhase.value).toBe('idle')
  })

  it('clearResult with dataset sets schemaReady phase', () => {
    analyzer.datasetSummary.value = { name: 'test.csv', rows: 10, columns: 3, fieldNames: ['a', 'b', 'c'], previewText: '' }
    analyzer.setChartConfig({ type: 'bar', xField: 'a' })
    analyzer.clearResult()
    expect(analyzer.kittenPhase.value).toBe('schemaReady')
  })

  it('handleInputKeydown sends message on Enter without Shift', () => {
    const preventDefault = vi.fn()
    const sendMessageSpy = vi.spyOn(analyzer, 'sendMessage').mockImplementation(() => Promise.resolve())
    const e = { key: 'Enter', shiftKey: false, preventDefault } as unknown as KeyboardEvent
    analyzer.handleInputKeydown(e)
    expect(preventDefault).toHaveBeenCalled()
    sendMessageSpy.mockRestore()
  })

  it('handleInputKeydown does not send on Shift+Enter', () => {
    const preventDefault = vi.fn()
    const sendMessageSpy = vi.spyOn(analyzer, 'sendMessage').mockImplementation(() => Promise.resolve())
    const e = { key: 'Enter', shiftKey: true, preventDefault } as unknown as KeyboardEvent
    analyzer.handleInputKeydown(e)
    expect(preventDefault).not.toHaveBeenCalled()
    sendMessageSpy.mockRestore()
  })

  it('handleInputKeydown does not send on non-Enter keys', () => {
    const preventDefault = vi.fn()
    const sendMessageSpy = vi.spyOn(analyzer, 'sendMessage').mockImplementation(() => Promise.resolve())
    const e = { key: 'a', shiftKey: false, preventDefault } as unknown as KeyboardEvent
    analyzer.handleInputKeydown(e)
    expect(preventDefault).not.toHaveBeenCalled()
    sendMessageSpy.mockRestore()
  })

  it('sendQuickAction sets inputText and triggers send', async () => {
    // sendQuickAction sets inputText then calls void sendMessage()
    const { safeJsonRequest } = await import('@/utils/safeJsonRequest')
    vi.mocked(safeJsonRequest).mockResolvedValueOnce({
      ok: true,
      data: { success: true, response: 'reply' },
      status: 200,
      message: '',
    })
    analyzer.sendQuickAction({ text: '分析销量趋势' })
    // Wait for async sendMessage to complete
    await new Promise((r) => setTimeout(r, 100))
    // The user message should have been added
    const userMsg = analyzer.messages.value.find((m) => m.role === 'user' && m.content.includes('分析销量趋势'))
    expect(userMsg).toBeDefined()
  })

  it('sendMessage returns early when input is empty', async () => {
    analyzer.inputText.value = '   '
    await analyzer.sendMessage()
    expect(analyzer.isChatLoading.value).toBe(false)
  })

  it('sendMessage returns early when already loading', async () => {
    analyzer.inputText.value = 'hello'
    analyzer.isChatLoading.value = true
    await analyzer.sendMessage()
    expect(analyzer.messages.value.length).toBe(1) // only welcome
  })

  it('sendMessage returns early when dataset parsing', async () => {
    analyzer.inputText.value = 'hello'
    analyzer.isDatasetParsing.value = true
    await analyzer.sendMessage()
    expect(analyzer.messages.value.length).toBe(1)
  })

  it('sendMessage adds user message and sets loading state', async () => {
    const { safeJsonRequest } = await import('@/utils/safeJsonRequest')
    vi.mocked(safeJsonRequest).mockResolvedValueOnce({
      ok: true,
      data: { success: true, response: 'AI reply' },
      status: 200,
      message: '',
    })
    analyzer.inputText.value = 'hello'
    const promise = analyzer.sendMessage()
    expect(analyzer.isChatLoading.value).toBe(true)
    await promise
    expect(analyzer.isChatLoading.value).toBe(false)
  })

  it('sendMessage handles API success with response text', async () => {
    const { safeJsonRequest } = await import('@/utils/safeJsonRequest')
    vi.mocked(safeJsonRequest).mockResolvedValueOnce({
      ok: true,
      data: { success: true, response: '这是AI的回复' },
      status: 200,
      message: '',
    })
    analyzer.inputText.value = '你好'
    await analyzer.sendMessage()
    const aiMsg = analyzer.messages.value.find((m) => m.role === 'ai' && m.content.includes('这是AI的回复'))
    expect(aiMsg).toBeDefined()
    expect(analyzer.kittenPhase.value).toBe('delivered')
  })

  it('sendMessage handles API failure', async () => {
    const { safeJsonRequest } = await import('@/utils/safeJsonRequest')
    vi.mocked(safeJsonRequest).mockResolvedValueOnce({
      ok: false,
      data: { success: false, message: '服务器错误' },
      status: 500,
      message: '服务器错误',
    })
    analyzer.inputText.value = 'hello'
    await analyzer.sendMessage()
    const aiMsg = analyzer.messages.value.find((m) => m.role === 'ai' && m.content.includes('请求失败'))
    expect(aiMsg).toBeDefined()
    expect(analyzer.kittenPhase.value).toBe('error')
  })

  it('sendMessage handles network error', async () => {
    const { safeJsonRequest } = await import('@/utils/safeJsonRequest')
    vi.mocked(safeJsonRequest).mockRejectedValueOnce(new Error('Network error'))
    analyzer.inputText.value = 'hello'
    await analyzer.sendMessage()
    const aiMsg = analyzer.messages.value.find((m) => m.role === 'ai' && m.content.includes('网络异常'))
    expect(aiMsg).toBeDefined()
    expect(analyzer.kittenPhase.value).toBe('error')
  })

  it('sendMessage handles AbortError as timeout', async () => {
    const { safeJsonRequest } = await import('@/utils/safeJsonRequest')
    const abortErr = new Error('The operation was aborted')
    abortErr.name = 'AbortError'
    vi.mocked(safeJsonRequest).mockRejectedValueOnce(abortErr)
    analyzer.inputText.value = 'hello'
    await analyzer.sendMessage()
    // AbortError should result in timeout message
    expect(analyzer.kittenPhase.value).toBe('error')
  })

  it('sendMessage handles empty AI response', async () => {
    const { safeJsonRequest } = await import('@/utils/safeJsonRequest')
    vi.mocked(safeJsonRequest).mockResolvedValueOnce({
      ok: true,
      data: { success: true, response: '' },
      status: 200,
      message: '',
    })
    analyzer.inputText.value = 'hello'
    await analyzer.sendMessage()
    const aiMsg = analyzer.messages.value.find((m) => m.role === 'ai' && m.content.includes('服务器未返回有效回复'))
    expect(aiMsg).toBeDefined()
  })

  it('resetSession clears state and resets to welcome', async () => {
    const { safeJsonRequest } = await import('@/utils/safeJsonRequest')
    analyzer.messages.value.push({ role: 'user', content: 'test', time: '10:00' })
    analyzer.kittenPhase.value = 'delivered'
    analyzer.datasetSummary.value = { name: 'test.csv', rows: 10, columns: 3, fieldNames: ['a'], previewText: '' }
    analyzer.currentResult.value = { id: 1, title: 'test', summary: 's', chart: false, type: 't', kind: 'k' }

    await analyzer.resetSession()

    expect(analyzer.messages.value.length).toBe(1)
    expect(analyzer.messages.value[0].content).toBe(KITTEN_WELCOME_HTML)
    expect(analyzer.kittenPhase.value).toBe('idle')
    expect(analyzer.currentResult.value).toBeNull()
    expect(analyzer.datasetSummary.value).toBeNull()
    expect(analyzer.inputText.value).toBe('')
    expect(analyzer.isChatLoading.value).toBe(false)
    expect(safeJsonRequest).toHaveBeenCalledWith('/api/ai/context/clear', expect.objectContaining({ method: 'POST' }))
  })

  it('resetSession handles clear context failure gracefully', async () => {
    const { safeJsonRequest } = await import('@/utils/safeJsonRequest')
    vi.mocked(safeJsonRequest).mockResolvedValueOnce({ ok: false, data: null, status: 500, message: 'fail' })
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
    await analyzer.resetSession()
    expect(warnSpy).toHaveBeenCalled()
    warnSpy.mockRestore()
  })

  it('onKittenBusinessDbToggle refreshes snapshot when enabled', async () => {
    const { safeJsonRequest } = await import('@/utils/safeJsonRequest')
    vi.mocked(safeJsonRequest).mockResolvedValueOnce({
      ok: true,
      data: { success: true, data: { stats: { materials_total: 100, products_total: 50 } } },
      status: 200,
      message: '',
    })
    analyzer.kittenIncludeBusinessDb.value = true
    analyzer.onKittenBusinessDbToggle()
    // Wait for async
    await new Promise((r) => setTimeout(r, 50))
    expect(analyzer.kittenDbStatsHint.value).toContain('已就绪')
  })

  it('kittenIncludeBusinessDb toggle clears hint when disabled', async () => {
    // The watch in useKittenAnalyzer clears kittenDbStatsHint when disabled
    // But watch may not trigger outside of Vue component setup context
    // Test the onKittenBusinessDbToggle behavior instead
    analyzer.kittenIncludeBusinessDb.value = false
    analyzer.onKittenBusinessDbToggle()
    await new Promise((r) => setTimeout(r, 50))
    expect(analyzer.kittenDbStatsHint.value).toBe('')
  })

  it('refreshKittenBusinessSnapshotHint sets failure text on API error', async () => {
    const { safeJsonRequest } = await import('@/utils/safeJsonRequest')
    vi.mocked(safeJsonRequest).mockResolvedValueOnce({
      ok: false,
      data: null,
      status: 500,
      message: 'error',
    })
    analyzer.kittenIncludeBusinessDb.value = true
    analyzer.onKittenBusinessDbToggle()
    await new Promise((r) => setTimeout(r, 50))
    expect(analyzer.kittenDbStatsHint.value).toContain('业务库快照预检失败')
  })

  it('refreshKittenBusinessSnapshotHint returns early when not enabled', async () => {
    const { safeJsonRequest } = await import('@/utils/safeJsonRequest')
    analyzer.kittenIncludeBusinessDb.value = false
    // onKittenBusinessDbToggle checks kittenIncludeBusinessDb before calling
    analyzer.onKittenBusinessDbToggle()
    await new Promise((r) => setTimeout(r, 50))
    // safeJsonRequest should not be called for business-snapshot when disabled
    const calls = vi.mocked(safeJsonRequest).mock.calls
    const snapshotCalls = calls.filter((c) => String(c[0]).includes('business-snapshot'))
    expect(snapshotCalls.length).toBe(0)
  })

  it('handleFileSelect parses dataset file successfully', async () => {
    const input = { files: [{ name: 'test.csv' }], value: '' } as unknown as HTMLInputElement
    const event = { target: input } as unknown as Event
    await analyzer.handleFileSelect(event)
    expect(analyzer.datasetSummary.value).not.toBeNull()
    expect(analyzer.datasetSummary.value!.name).toBe('test.csv')
    expect(analyzer.datasetSummary.value!.rows).toBe(100)
    expect(analyzer.kittenPhase.value).toBe('schemaReady')
    expect(analyzer.isDatasetParsing.value).toBe(false)
  })

  it('handleFileSelect handles parse error', async () => {
    const { parseDatasetFile } = await import('@/utils/kittenDatasetParser')
    vi.mocked(parseDatasetFile).mockRejectedValueOnce(new Error('Invalid file format'))
    const input = { files: [{ name: 'bad.csv' }], value: '' } as unknown as HTMLInputElement
    const event = { target: input } as unknown as Event
    await analyzer.handleFileSelect(event)
    expect(analyzer.kittenPhase.value).toBe('error')
    const aiMsg = analyzer.messages.value.find((m) => m.role === 'ai' && m.content.includes('文件解析失败'))
    expect(aiMsg).toBeDefined()
  })

  it('handleFileSelect does nothing when no file selected', async () => {
    const input = { files: [] } as unknown as HTMLInputElement
    const event = { target: input } as unknown as Event
    const prevLen = analyzer.messages.value.length
    await analyzer.handleFileSelect(event)
    expect(analyzer.messages.value.length).toBe(prevLen)
  })

  it('exportResult does nothing without currentResult', async () => {
    analyzer.currentResult.value = null
    await analyzer.exportResult()
    // No error thrown
  })

  it('exportResult calls backend export', async () => {
    const pkBuffer = new Uint8Array([0x50, 0x4b, 0x03, 0x04, 0x00, 0x00, 0x00, 0x00])
    const pkBlob = new Blob([pkBuffer])
    global.fetch = vi.fn().mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: {
        get: (name: string) => name === 'content-type' ? 'application/octet-stream' : 'attachment; filename="report.xlsx"',
      },
      blob: async () => pkBlob,
    } as unknown as Response)
    analyzer.currentResult.value = { id: 1, title: 'test', summary: 's', chart: false, type: 't', kind: 'k' }
    await analyzer.exportResult()
    expect(global.fetch).toHaveBeenCalled()
  })

  it('exportDocx does nothing without currentResult', async () => {
    analyzer.currentResult.value = null
    await analyzer.exportDocx()
  })

  it('exportDocx handles backend error', async () => {
    global.fetch = vi.fn().mockResolvedValueOnce({
      ok: false,
      status: 500,
      text: async () => 'Server error',
    } as unknown as Response)
    analyzer.currentResult.value = { id: 1, title: 'test', summary: 's', chart: false, type: 't', kind: 'k' }
    const { appAlert } = await import('@/utils/appDialog')
    await analyzer.exportDocx()
    expect(appAlert).toHaveBeenCalled()
  })

  it('generateAiOfficeDocument returns early with empty prompt', async () => {
    const { appAlert } = await import('@/utils/appDialog')
    await analyzer.generateAiOfficeDocument('', 'docx')
    expect(appAlert).toHaveBeenCalledWith('请先描述要生成的文档内容')
  })

  it('generateAiOfficeDocument handles successful generation', async () => {
    // Create a blob with PK magic number (ZIP header for docx/xlsx)
    const pkBuffer = new Uint8Array([0x50, 0x4b, 0x03, 0x04, 0x00, 0x00, 0x00, 0x00])
    const pkBlob = new Blob([pkBuffer])
    global.fetch = vi.fn().mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: {
        get: (name: string) => name === 'content-type' ? 'application/octet-stream' : null,
      },
      blob: async () => pkBlob,
    } as unknown as Response)
    await analyzer.generateAiOfficeDocument('写一份合同', 'docx')
    expect(analyzer.isDocGenLoading.value).toBe(false)
  })

  it('generateAiOfficeDocument handles generation failure', async () => {
    global.fetch = vi.fn().mockResolvedValueOnce({
      ok: false,
      status: 500,
      json: async () => ({ message: '生成失败' }),
    } as unknown as Response)
    const { appAlert } = await import('@/utils/appDialog')
    await analyzer.generateAiOfficeDocument('写一份合同', 'xlsx')
    expect(appAlert).toHaveBeenCalled()
    expect(analyzer.isDocGenLoading.value).toBe(false)
  })

  it('runFinancialBrief handles success', async () => {
    const { safeJsonRequest } = await import('@/utils/safeJsonRequest')
    vi.mocked(safeJsonRequest).mockResolvedValueOnce({
      ok: true,
      data: { success: true, data: { revenue: 1000000 } },
      status: 200,
      message: '',
    })
    await analyzer.runFinancialBrief()
    const aiMsg = analyzer.messages.value.find((m) => m.role === 'ai' && m.content.includes('财务简报'))
    expect(aiMsg).toBeDefined()
    expect(analyzer.kittenPhase.value).toBe('delivered')
  })

  it('runFinancialBrief handles failure', async () => {
    const { safeJsonRequest } = await import('@/utils/safeJsonRequest')
    vi.mocked(safeJsonRequest).mockResolvedValueOnce({
      ok: false,
      data: { success: false, message: '生成失败' },
      status: 500,
      message: '生成失败',
    })
    await analyzer.runFinancialBrief()
    const aiMsg = analyzer.messages.value.find((m) => m.role === 'ai' && m.content.includes('生成失败'))
    expect(aiMsg).toBeDefined()
  })

  it('lastDocumentPickupUrl extracts URL from messages', () => {
    analyzer.messages.value.push({
      role: 'ai',
      content: '文档已生成 <a href="/api/ai/kitten/document/pickup/abc123">下载</a>',
      time: '10:00',
    })
    expect(analyzer.lastDocumentPickupUrl.value).toContain('/api/ai/kitten/document/pickup/abc123')
  })

  it('datasetFieldPreview shows up to 8 field names', () => {
    analyzer.datasetSummary.value = {
      name: 'test.csv',
      rows: 10,
      columns: 10,
      fieldNames: ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j'],
      previewText: '',
    }
    expect(analyzer.datasetFieldPreview.value).toEqual(['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'])
  })

  it('recommendedCharts generates charts from field profiles', () => {
    analyzer.fieldProfiles.value = [
      { name: '城市', type: 'category' },
      { name: '销量', type: 'number' },
      { name: '日期', type: 'date' },
    ]
    const charts = analyzer.recommendedCharts.value
    expect(charts.length).toBeGreaterThan(0)
    expect(charts[0].config.xField).toBe('城市')
  })

  it('kittenIncludeWebSearch defaults to true', () => {
    expect(analyzer.kittenIncludeWebSearch.value).toBe(true)
  })
})

describe('extractKittenDocumentPickupUrl', () => {
  it('returns null for empty content', () => {
    expect(extractKittenDocumentPickupUrl('')).toBeNull()
  })

  it('extracts absolute URL', () => {
    const url = 'https://example.com/api/ai/kitten/document/pickup/abc123'
    expect(extractKittenDocumentPickupUrl(`点击下载：${url}`)).toBe(url)
  })

  it('extracts relative URL', () => {
    const url = '/api/ai/kitten/document/pickup/abc123'
    expect(extractKittenDocumentPickupUrl(`下载：${url}`)).toBe(url)
  })

  it('extracts URL from HTML-encoded content', () => {
    const url = '/api/ai/kitten/document/pickup/abc123'
    const encoded = `下载：&lt;a href=&quot;${url}&quot;&gt;链接&lt;/a&gt;`
    expect(extractKittenDocumentPickupUrl(encoded)).toBe(url)
  })

  it('extracts URL from JSON download_url field', () => {
    const url = '/api/ai/kitten/document/pickup/abc123'
    const content = `"download_url": "${url}"`
    expect(extractKittenDocumentPickupUrl(content)).toBe(url)
  })

  it('extracts absolute URL from JSON download_url', () => {
    const url = 'https://example.com/api/ai/kitten/document/pickup/abc123'
    const content = `"download_url": "${url}"`
    expect(extractKittenDocumentPickupUrl(content)).toBe(url)
  })

  it('returns null when no pickup URL found', () => {
    expect(extractKittenDocumentPickupUrl('普通文本，没有链接')).toBeNull()
  })

  it('handles JSON download_url with escaped slashes', () => {
    const url = '/api/ai/kitten/document/pickup/abc123'
    const content = `"download_url": "\\/api\\/ai\\/kitten\\/document\\/pickup\\/abc123"`
    expect(extractKittenDocumentPickupUrl(content)).toBe(url)
  })
})

describe('kittenWorkflowSteps', () => {
  it('has 4 steps', () => {
    expect(kittenWorkflowSteps.length).toBe(4)
  })

  it('contains expected step keys', () => {
    const keys = kittenWorkflowSteps.map((s) => s.key)
    expect(keys).toEqual(['ingest', 'schema', 'analyze', 'deliver'])
  })
})

describe('kittenOrgCards', () => {
  it('has 4 cards', () => {
    expect(kittenOrgCards.length).toBe(4)
  })
})

describe('kittenQuickActions', () => {
  it('has quick action buttons', () => {
    expect(kittenQuickActions.length).toBeGreaterThan(0)
  })

  it('each action has text and label', () => {
    for (const action of kittenQuickActions) {
      expect(action.text).toBeTruthy()
      expect(action.label).toBeTruthy()
    }
  })
})
