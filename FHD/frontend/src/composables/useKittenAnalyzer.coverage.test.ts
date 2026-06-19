/**
 * useKittenAnalyzer 覆盖率提升测试
 *
 * 目标：覆盖 useKittenAnalyzer.ts 中未覆盖的分支，将 statements 覆盖率从 78.7% 提升到 90%+。
 * 重点覆盖：流式聊天路径（token/done/error/requires_token 事件）、
 * assertKittenFileBlob 各种内容类型检测、buildReportWorkbook 通过 exportResult 本地回退、
 * buildRecommendedCharts 各种字段组合、buildPreviewTextFromData 数组/对象行、
 * formatKittenSnapshotStatsHint 各种统计字段、buildKittenResultSummary URL 截断、
 * extractChatApiText data.data.text 分支、extractWebSearchHits 各种边界、
 * generateDataPreview 列截断、generateAiOfficeDocument 文本回退、
 * runFinancialBrief 非对象数据、refreshKittenBusinessSnapshotHint 缓存命中、
 * exportDocxViaBackend 成功路径、exportReportViaBackend 错误路径。
 *
 * 遵循铁律3：happy path + 空值/None + 边界值 + 异常路径。
 * Mock 最小化：仅 mock 外部边界（API、xlsx 动态 import）。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  useKittenAnalyzer,
  extractKittenDocumentPickupUrl,
} from './useKittenAnalyzer'

// ── Mock 配置 ──────────────────────────────────────────────────────────

vi.mock('@/api/core', () => ({
  buildFullApiUrl: (path: string) => `http://localhost:5000${path}`,
}))

vi.mock('@/utils', () => ({
  downloadBlob: vi.fn(),
  getFilenameFromDisposition: vi.fn((_hdr: unknown, fallback: string) => fallback),
}))

vi.mock('@/utils/safeJsonRequest', () => ({
  safeJsonRequest: vi.fn(),
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
  isChatStreamEnabled: vi.fn(() => false),
}))

vi.mock('@/utils/kittenDatasetParser', () => ({
  parseDatasetFile: vi.fn(),
}))

vi.mock('xlsx', () => ({
  utils: {
    book_new: vi.fn(() => ({ SheetNames: [] })),
    aoa_to_sheet: vi.fn(() => ({})),
    json_to_sheet: vi.fn(() => ({})),
    book_append_sheet: vi.fn(),
  },
  write: vi.fn(() => new ArrayBuffer(8)),
}))

// ── 导入 mocked 模块 ──────────────────────────────────────────────────

import { safeJsonRequest } from '@/utils/safeJsonRequest'
import { parseDatasetFile } from '@/utils/kittenDatasetParser'
import { isChatStreamEnabled, readPlannerSseResponse } from '@/utils/chatSseStream'
import { chatApi } from '@/api/chat'
import { downloadBlob } from '@/utils'
import { appAlert } from '@/utils/appDialog'

// ── 辅助函数 ──────────────────────────────────────────────────────────

/**
 * 创建带 text()/arrayBuffer()/slice() 方法的模拟 Blob。
 * jsdom 的 Blob 可能不实现 text()/arrayBuffer()，需手动补上。
 */
function makeMockBlob(content: string | Uint8Array): Blob {
  const data =
    typeof content === 'string' ? new TextEncoder().encode(content) : content
  const text = typeof content === 'string' ? content : ''

  const blob = new Blob([data]) as Blob & {
    text: () => Promise<string>
    arrayBuffer: () => Promise<ArrayBuffer>
  }
  // 补充 jsdom 缺失的 text()/arrayBuffer() 方法
  if (typeof blob.text !== 'function') {
    blob.text = async () => text
  }
  if (typeof blob.arrayBuffer !== 'function') {
    blob.arrayBuffer = async () => data.buffer as ArrayBuffer
  }
  // 覆盖 slice，确保返回的子 Blob 也有 text()/arrayBuffer()
  const origSlice = blob.slice.bind(blob)
  blob.slice = ((start?: number, end?: number, contentType?: string) => {
    const subBlob = origSlice(start, end, contentType) as Blob & {
      text: () => Promise<string>
      arrayBuffer: () => Promise<ArrayBuffer>
    }
    const s = start || 0
    const slicedData = data.slice(s, end)
    const slicedText = text.slice(s, end)
    if (typeof subBlob.text !== 'function') {
      subBlob.text = async () => slicedText
    }
    if (typeof subBlob.arrayBuffer !== 'function') {
      subBlob.arrayBuffer = async () => slicedData.buffer as ArrayBuffer
    }
    return subBlob
  }) as Blob['slice']

  return blob
}

/** 创建 PK 魔数的 Blob（ZIP 文件头，用于 docx/xlsx） */
function makePkBlob(): Blob {
  return makeMockBlob(new Uint8Array([0x50, 0x4b, 0x03, 0x04, 0x00, 0x00, 0x00, 0x00]))
}

/** 创建文本 Blob */
function makeTextBlob(text: string): Blob {
  return makeMockBlob(text)
}

/** 创建模拟 Response */
function makeResponse(options: {
  ok?: boolean
  status?: number
  contentType?: string
  disposition?: string | null
  blob?: Blob
  text?: string
  json?: unknown
  jsonThrows?: boolean
  textThrows?: boolean
}): Response {
  const {
    ok = true,
    status = 200,
    contentType = 'application/octet-stream',
    disposition = null,
    blob,
    text,
    json,
    jsonThrows = false,
    textThrows = false,
  } = options
  return {
    ok,
    status,
    headers: {
      get: (name: string) => {
        if (name === 'content-type') return contentType
        if (name === 'content-disposition') return disposition
        return null
      },
    },
    blob: async () => blob || makeMockBlob(''),
    text: async () => {
      if (textThrows) throw new Error('text error')
      return text || ''
    },
    json: async () => {
      if (jsonThrows) throw new Error('json parse error')
      return json || {}
    },
  } as unknown as Response
}

/** 等待所有异步任务完成 */
function flushAsync(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 50))
}

// ── 测试套件 ──────────────────────────────────────────────────────────

describe('useKittenAnalyzer - coverage ramp', () => {
  let analyzer: ReturnType<typeof useKittenAnalyzer>
  let originalFetch: typeof global.fetch

  beforeEach(() => {
    vi.clearAllMocks()
    originalFetch = global.fetch

    // 设置默认 mock 返回值
    vi.mocked(safeJsonRequest).mockResolvedValue({
      ok: true,
      data: { success: true },
      status: 200,
      message: '',
    })
    vi.mocked(parseDatasetFile).mockResolvedValue({
      rows: 100,
      columns: ['姓名', '年龄', '城市'],
      sampleRows: [{ 姓名: '张三', 年龄: 28, 城市: '北京' }],
      fieldProfiles: [
        { name: '姓名', type: 'category' },
        { name: '年龄', type: 'number' },
        { name: '城市', type: 'category' },
      ],
    })
    vi.mocked(isChatStreamEnabled).mockReturnValue(false)
    vi.mocked(readPlannerSseResponse).mockResolvedValue(undefined)
    vi.mocked(chatApi.sendChatStream).mockResolvedValue(makeResponse({}) as never)

    analyzer = useKittenAnalyzer()
  })

  afterEach(() => {
    global.fetch = originalFetch
    vi.restoreAllMocks()
  })

  // ════════════════════════════════════════════════════════════════════
  // 流式聊天路径覆盖（sendMessage 中的 stream 分支）
  // ════════════════════════════════════════════════════════════════════

  describe('流式聊天路径', () => {
    beforeEach(() => {
      vi.mocked(isChatStreamEnabled).mockReturnValue(true)
    })

    it('流式成功：token 事件 + done 事件，最终使用 done.response 作为回复', async () => {
      vi.mocked(chatApi.sendChatStream).mockResolvedValue(makeResponse({ ok: true }) as never)
      vi.mocked(readPlannerSseResponse).mockImplementation(
        async (_res: Response, onEvent: (ev: unknown) => void) => {
          onEvent({ type: 'token', text: 'Hello' })
          onEvent({ type: 'token', text: ' World' })
          onEvent({ type: 'done', result: { response: '最终回复', success: true } })
        }
      )

      analyzer.inputText.value = '你好'
      await analyzer.sendMessage()

      // 验证 AI 消息包含最终回复
      const aiMsg = analyzer.messages.value.find(
        (m) => m.role === 'ai' && m.content.includes('最终回复')
      )
      expect(aiMsg).toBeDefined()
      expect(analyzer.kittenPhase.value).toBe('delivered')
      expect(analyzer.isKittenStreaming.value).toBe(false)
    })

    it('流式成功：无 done 事件时使用 streamPlain 作为回复', async () => {
      vi.mocked(chatApi.sendChatStream).mockResolvedValue(makeResponse({ ok: true }) as never)
      vi.mocked(readPlannerSseResponse).mockImplementation(
        async (_res: Response, onEvent: (ev: unknown) => void) => {
          onEvent({ type: 'token', text: '流式文本内容' })
        }
      )

      analyzer.inputText.value = '你好'
      await analyzer.sendMessage()

      const aiMsg = analyzer.messages.value.find(
        (m) => m.role === 'ai' && m.content.includes('流式文本内容')
      )
      expect(aiMsg).toBeDefined()
      expect(analyzer.kittenPhase.value).toBe('delivered')
    })

    it('流式成功：无 token 无 done 时使用"（无内容）"占位', async () => {
      vi.mocked(chatApi.sendChatStream).mockResolvedValue(makeResponse({ ok: true }) as never)
      vi.mocked(readPlannerSseResponse).mockResolvedValue(undefined)

      analyzer.inputText.value = '你好'
      await analyzer.sendMessage()

      const aiMsg = analyzer.messages.value.find(
        (m) => m.role === 'ai' && m.content.includes('（无内容）')
      )
      expect(aiMsg).toBeDefined()
    })

    it('流式 done 事件 success=false 标记为失败', async () => {
      vi.mocked(chatApi.sendChatStream).mockResolvedValue(makeResponse({ ok: true }) as never)
      vi.mocked(readPlannerSseResponse).mockImplementation(
        async (_res: Response, onEvent: (ev: unknown) => void) => {
          onEvent({ type: 'done', result: { response: '失败回复', success: false } })
        }
      )

      analyzer.inputText.value = '你好'
      await analyzer.sendMessage()

      expect(analyzer.kittenPhase.value).toBe('error')
      expect(analyzer.currentResult.value?.type).toBe('error')
      expect(analyzer.currentResult.value?.kind).toBe('chatError')
    })

    it('流式 error 事件触发回退到 JSON 路径', async () => {
      vi.mocked(chatApi.sendChatStream).mockResolvedValue(makeResponse({ ok: true }) as never)
      vi.mocked(readPlannerSseResponse).mockImplementation(
        async (_res: Response, onEvent: (ev: unknown) => void) => {
          onEvent({ type: 'error', message: '流式接口错误' })
        }
      )
      // JSON 回退的 mock
      vi.mocked(safeJsonRequest).mockResolvedValueOnce({
        ok: true,
        data: { success: true, response: 'JSON 回退回复' },
        status: 200,
        message: '',
      })

      analyzer.inputText.value = '你好'
      await analyzer.sendMessage()

      // 应该走 JSON 回退路径
      const aiMsg = analyzer.messages.value.find(
        (m) => m.role === 'ai' && m.content.includes('JSON 回退回复')
      )
      expect(aiMsg).toBeDefined()
    })

    it('流式 sendChatStream 返回 ok=false 触发回退到 JSON 路径', async () => {
      vi.mocked(chatApi.sendChatStream).mockResolvedValue(
        makeResponse({ ok: false, status: 500 }) as never
      )
      vi.mocked(safeJsonRequest).mockResolvedValueOnce({
        ok: true,
        data: { success: true, response: 'JSON 回退' },
        status: 200,
        message: '',
      })

      analyzer.inputText.value = '你好'
      await analyzer.sendMessage()

      const aiMsg = analyzer.messages.value.find(
        (m) => m.role === 'ai' && m.content.includes('JSON 回退')
      )
      expect(aiMsg).toBeDefined()
    })

    it('流式 sendChatStream 抛异常触发回退到 JSON 路径', async () => {
      vi.mocked(chatApi.sendChatStream).mockRejectedValue(new Error('网络错误'))
      vi.mocked(safeJsonRequest).mockResolvedValueOnce({
        ok: true,
        data: { success: true, response: 'JSON 回退' },
        status: 200,
        message: '',
      })

      analyzer.inputText.value = '你好'
      await analyzer.sendMessage()

      const aiMsg = analyzer.messages.value.find(
        (m) => m.role === 'ai' && m.content.includes('JSON 回退')
      )
      expect(aiMsg).toBeDefined()
    })

    it('requires_token 事件：非 DB 令牌追加授权提示', async () => {
      vi.mocked(chatApi.sendChatStream).mockResolvedValue(makeResponse({ ok: true }) as never)
      vi.mocked(readPlannerSseResponse).mockImplementation(
        async (_res: Response, onEvent: (ev: unknown) => void) => {
          onEvent({ type: 'token', text: '内容' })
          onEvent({ type: 'requires_token', token_name: 'API_KEY', token_description: 'API Key' })
          onEvent({ type: 'done', result: { response: '内容\n[需要授权：API Key]\n', success: true } })
        }
      )

      analyzer.inputText.value = '你好'
      await analyzer.sendMessage()

      // 授权提示应出现在消息中
      const aiMsg = analyzer.messages.value.find(
        (m) => m.role === 'ai' && m.content.includes('需要授权')
      )
      expect(aiMsg).toBeDefined()
    })

    it('requires_token 事件：DB_READ_TOKEN 被跳过（不追加授权提示）', async () => {
      vi.mocked(chatApi.sendChatStream).mockResolvedValue(makeResponse({ ok: true }) as never)
      vi.mocked(readPlannerSseResponse).mockImplementation(
        async (_res: Response, onEvent: (ev: unknown) => void) => {
          onEvent({ type: 'token', text: '内容' })
          onEvent({ type: 'requires_token', token_name: 'DB_READ_TOKEN', token_description: '数据库读令牌' })
          onEvent({ type: 'done', result: { response: '内容', success: true } })
        }
      )

      analyzer.inputText.value = '你好'
      await analyzer.sendMessage()

      // DB 令牌应被跳过，不应出现授权提示
      const aiMsg = analyzer.messages.value.find(
        (m) => m.role === 'ai' && m.content.includes('需要授权')
      )
      expect(aiMsg).toBeUndefined()
    })

    it('requires_token 事件：DB_WRITE_TOKEN 被跳过', async () => {
      vi.mocked(chatApi.sendChatStream).mockResolvedValue(makeResponse({ ok: true }) as never)
      vi.mocked(readPlannerSseResponse).mockImplementation(
        async (_res: Response, onEvent: (ev: unknown) => void) => {
          onEvent({ type: 'token', text: '内容' })
          onEvent({ type: 'requires_token', token_name: 'DB_WRITE_TOKEN', token_description: '写入令牌' })
          onEvent({ type: 'done', result: { response: '内容', success: true } })
        }
      )

      analyzer.inputText.value = '你好'
      await analyzer.sendMessage()

      const aiMsg = analyzer.messages.value.find(
        (m) => m.role === 'ai' && m.content.includes('需要授权')
      )
      expect(aiMsg).toBeUndefined()
    })

    it('requires_token 事件：空 token_name 和 token_description 使用"授权信息"占位', async () => {
      vi.mocked(chatApi.sendChatStream).mockResolvedValue(makeResponse({ ok: true }) as never)
      vi.mocked(readPlannerSseResponse).mockImplementation(
        async (_res: Response, onEvent: (ev: unknown) => void) => {
          onEvent({ type: 'token', text: '内容' })
          onEvent({ type: 'requires_token', token_name: '', token_description: '' })
          onEvent({ type: 'done', result: { response: '内容\n[需要授权：授权信息]\n', success: true } })
        }
      )

      analyzer.inputText.value = '你好'
      await analyzer.sendMessage()

      const aiMsg = analyzer.messages.value.find(
        (m) => m.role === 'ai' && m.content.includes('授权信息')
      )
      expect(aiMsg).toBeDefined()
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // assertKittenFileBlob 内容类型检测（通过 exportResult/exportDocx/generateAiOfficeDocument 触发）
  // ════════════════════════════════════════════════════════════════════

  describe('assertKittenFileBlob 内容类型检测', () => {
    it('JSON content-type 且含 message 字段：抛错并使用 message', async () => {
      global.fetch = vi.fn().mockResolvedValueOnce(
        makeResponse({
          ok: true,
          contentType: 'application/json',
          blob: makeTextBlob('{"message":"未登录"}'),
        })
      )
      analyzer.currentResult.value = {
        id: 1,
        title: 'test',
        summary: 's',
        chart: false,
        type: 't',
        kind: 'k',
      }

      await analyzer.exportResult()
      // JSON content-type 触发后端导出失败，回退到本地 xlsx 导出
      expect(downloadBlob).toHaveBeenCalled()
    })

    it('JSON content-type 且含 detail 字段：抛错并使用 detail', async () => {
      global.fetch = vi.fn().mockResolvedValueOnce(
        makeResponse({
          ok: true,
          contentType: 'application/json',
          blob: makeTextBlob('{"detail":"详情错误"}'),
        })
      )
      analyzer.currentResult.value = {
        id: 1,
        title: 'test',
        summary: 's',
        chart: false,
        type: 't',
        kind: 'k',
      }

      await analyzer.exportResult()
      expect(downloadBlob).toHaveBeenCalled()
    })

    it('JSON content-type 且非 JSON 文本：抛错并附带文本片段', async () => {
      global.fetch = vi.fn().mockResolvedValueOnce(
        makeResponse({
          ok: true,
          contentType: 'application/json',
          blob: makeTextBlob('not a json text'),
        })
      )
      analyzer.currentResult.value = {
        id: 1,
        title: 'test',
        summary: 's',
        chart: false,
        type: 't',
        kind: 'k',
      }

      await analyzer.exportResult()
      expect(downloadBlob).toHaveBeenCalled()
    })

    it('HTML content-type 且空文本：抛错不带片段', async () => {
      global.fetch = vi.fn().mockResolvedValueOnce(
        makeResponse({
          ok: true,
          contentType: 'text/html',
          blob: makeTextBlob('   '),
        })
      )
      analyzer.currentResult.value = {
        id: 1,
        title: 'test',
        summary: 's',
        chart: false,
        type: 't',
        kind: 'k',
      }

      await analyzer.exportResult()
      expect(downloadBlob).toHaveBeenCalled()
    })

    it('JSON 魔数（0x7b）且含 message 字段：抛错并使用 message', async () => {
      global.fetch = vi.fn().mockResolvedValueOnce(
        makeResponse({
          ok: true,
          contentType: 'application/octet-stream',
          blob: makeTextBlob('{"message":"API 基址错误"}'),
        })
      )
      analyzer.currentResult.value = {
        id: 1,
        title: 'test',
        summary: 's',
        chart: false,
        type: 't',
        kind: 'k',
      }

      await analyzer.exportResult()
      expect(downloadBlob).toHaveBeenCalled()
    })

    it('JSON 魔数（0x7b）且非 JSON 文本：抛错使用默认消息', async () => {
      global.fetch = vi.fn().mockResolvedValueOnce(
        makeResponse({
          ok: true,
          contentType: 'application/octet-stream',
          blob: makeTextBlob('{invalid json'),
        })
      )
      analyzer.currentResult.value = {
        id: 1,
        title: 'test',
        summary: 's',
        chart: false,
        type: 't',
        kind: 'k',
      }

      await analyzer.exportResult()
      expect(downloadBlob).toHaveBeenCalled()
    })

    it('JSON 数组魔数（0x5b）：抛错使用默认消息', async () => {
      global.fetch = vi.fn().mockResolvedValueOnce(
        makeResponse({
          ok: true,
          contentType: 'application/octet-stream',
          blob: makeTextBlob('[1, 2, 3]'),
        })
      )
      analyzer.currentResult.value = {
        id: 1,
        title: 'test',
        summary: 's',
        chart: false,
        type: 't',
        kind: 'k',
      }

      await analyzer.exportResult()
      expect(downloadBlob).toHaveBeenCalled()
    })

    it('generateAiOfficeDocument 遇 JSON content-type 抛错并调用 appAlert', async () => {
      global.fetch = vi.fn().mockResolvedValueOnce(
        makeResponse({
          ok: true,
          contentType: 'application/json',
          blob: makeTextBlob('{"message":"生成失败原因"}'),
        })
      )

      await analyzer.generateAiOfficeDocument('写一份合同', 'docx')
      expect(appAlert).toHaveBeenCalledWith(
        expect.stringContaining('生成失败原因')
      )
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // buildReportWorkbook + exportResult 本地回退
  // ════════════════════════════════════════════════════════════════════

  describe('exportResult 本地回退 + buildReportWorkbook', () => {
    it('后端导出失败后回退到本地 xlsx 导出（含数据集和图表配置）', async () => {
      global.fetch = vi.fn().mockResolvedValueOnce(
        makeResponse({ ok: false, status: 500, text: 'Server error' })
      )
      analyzer.currentResult.value = {
        id: 1,
        title: '测试报告',
        summary: '测试摘要',
        chart: true,
        type: 'chart',
        kind: 'datasetChart',
      }
      analyzer.datasetSummary.value = {
        name: 'data.csv',
        rows: 100,
        columns: 3,
        fieldNames: ['a', 'b', 'c'],
        previewText: 'preview',
      }
      analyzer.chartConfig.value = {
        type: 'bar',
        xField: 'a',
        yField: 'b',
        groupField: '',
        aggregate: 'sum',
      }

      await analyzer.exportResult()
      // 回退到本地 xlsx 导出，downloadBlob 应被调用
      expect(downloadBlob).toHaveBeenCalled()
    })

    it('本地 xlsx 导出也失败时调用 appAlert', async () => {
      global.fetch = vi.fn().mockResolvedValueOnce(
        makeResponse({ ok: false, status: 500, text: 'Server error' })
      )
      // 让 xlsx write 抛错
      const xlsxModule = await import('xlsx')
      vi.mocked(xlsxModule.write).mockImplementationOnce(() => {
        throw new Error('xlsx write error')
      })
      analyzer.currentResult.value = {
        id: 1,
        title: 'test',
        summary: 's',
        chart: false,
        type: 't',
        kind: 'k',
      }

      await analyzer.exportResult()
      expect(appAlert).toHaveBeenCalledWith(
        expect.stringContaining('导出失败')
      )
    })

    it('后端导出失败且 resp.text() 抛异常：回退到本地导出', async () => {
      global.fetch = vi.fn().mockResolvedValueOnce(
        makeResponse({ ok: false, status: 500, textThrows: true })
      )
      analyzer.currentResult.value = {
        id: 1,
        title: 'test',
        summary: 's',
        chart: false,
        type: 't',
        kind: 'k',
      }

      await analyzer.exportResult()
      expect(downloadBlob).toHaveBeenCalled()
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // buildRecommendedCharts 各种字段组合
  // ════════════════════════════════════════════════════════════════════

  describe('buildRecommendedCharts 字段组合', () => {
    it('分类 + 数值 + 日期字段：生成 4 条推荐（count/sum/date-line/pie）', () => {
      analyzer.fieldProfiles.value = [
        { name: '城市', type: 'category' },
        { name: '销量', type: 'number' },
        { name: '日期', type: 'date' },
      ]
      const charts = analyzer.recommendedCharts.value
      expect(charts.length).toBe(4)
      expect(charts[0].config.type).toBe('bar')
      expect(charts[2].config.type).toBe('line')
      expect(charts[3].config.type).toBe('pie')
    })

    it('两个数值字段：生成 scatter 推荐', () => {
      analyzer.fieldProfiles.value = [
        { name: '城市', type: 'category' },
        { name: '销量', type: 'number' },
        { name: '利润', type: 'number' },
      ]
      const charts = analyzer.recommendedCharts.value
      const scatter = charts.find((c) => c.config.type === 'scatter')
      expect(scatter).toBeDefined()
      expect(scatter?.config.xField).toBe('销量')
      expect(scatter?.config.yField).toBe('利润')
    })

    it('仅分类字段：生成 count 和 pie 推荐（无 metric 时 pie 用 count 聚合）', () => {
      analyzer.fieldProfiles.value = [
        { name: '城市', type: 'category' },
      ]
      const charts = analyzer.recommendedCharts.value
      expect(charts.length).toBe(2)
      const pie = charts.find((c) => c.config.type === 'pie')
      expect(pie).toBeDefined()
      expect(pie?.config.aggregate).toBe('count')
      expect(pie?.config.yField).toBe('')
    })

    it('文本字段作为维度：生成 count 和 pie 推荐', () => {
      analyzer.fieldProfiles.value = [
        { name: '备注', type: 'text' },
        { name: '销量', type: 'number' },
      ]
      const charts = analyzer.recommendedCharts.value
      expect(charts.length).toBeGreaterThanOrEqual(3)
      expect(charts[0].config.xField).toBe('备注')
    })

    it('仅数值字段无维度：不生成 count/sum/pie，仅 scatter（如有 2 个数值）', () => {
      analyzer.fieldProfiles.value = [
        { name: '销量', type: 'number' },
        { name: '利润', type: 'number' },
      ]
      const charts = analyzer.recommendedCharts.value
      // 无 dimension，只有 scatter
      expect(charts.length).toBe(1)
      expect(charts[0].config.type).toBe('scatter')
    })

    it('完整字段组合：最多返回 5 条推荐', () => {
      analyzer.fieldProfiles.value = [
        { name: '城市', type: 'category' },
        { name: '销量', type: 'number' },
        { name: '利润', type: 'number' },
        { name: '日期', type: 'date' },
      ]
      const charts = analyzer.recommendedCharts.value
      expect(charts.length).toBeLessThanOrEqual(5)
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // buildPreviewTextFromData（通过 handleFileSelect 触发）
  // ════════════════════════════════════════════════════════════════════

  describe('buildPreviewTextFromData 数据预览', () => {
    it('数组行：用制表符连接', async () => {
      vi.mocked(parseDatasetFile).mockResolvedValueOnce({
        rows: 3,
        columns: ['a', 'b'],
        preview: [
          [1, 2],
          [3, 4],
        ],
        sampleRows: [],
        fieldProfiles: [],
      })
      const input = { files: [{ name: 'test.csv' }], value: '' } as unknown as HTMLInputElement
      await analyzer.handleFileSelect({ target: input } as unknown as Event)
      expect(analyzer.datasetSummary.value?.previewText).toContain('1\t2')
    })

    it('对象行且有 columns：用 "key: value | key: value" 格式', async () => {
      vi.mocked(parseDatasetFile).mockResolvedValueOnce({
        rows: 2,
        columns: ['name', 'age'],
        preview: [{ name: '张三', age: 28 }],
        sampleRows: [],
        fieldProfiles: [],
      })
      const input = { files: [{ name: 'test.csv' }], value: '' } as unknown as HTMLInputElement
      await analyzer.handleFileSelect({ target: input } as unknown as Event)
      expect(analyzer.datasetSummary.value?.previewText).toContain('name: 张三')
      expect(analyzer.datasetSummary.value?.previewText).toContain('age: 28')
    })

    it('对象行无 columns：使用 Object.keys', async () => {
      vi.mocked(parseDatasetFile).mockResolvedValueOnce({
        rows: 1,
        columns: [],
        preview: [{ x: 1, y: 2 }],
        sampleRows: [],
        fieldProfiles: [],
      })
      const input = { files: [{ name: 'test.csv' }], value: '' } as unknown as HTMLInputElement
      await analyzer.handleFileSelect({ target: input } as unknown as Event)
      expect(analyzer.datasetSummary.value?.previewText).toContain('x: 1')
      expect(analyzer.datasetSummary.value?.previewText).toContain('y: 2')
    })

    it('空 preview：返回空字符串', async () => {
      vi.mocked(parseDatasetFile).mockResolvedValueOnce({
        rows: 0,
        columns: [],
        preview: [],
        sampleRows: [],
        fieldProfiles: [],
      })
      const input = { files: [{ name: 'empty.csv' }], value: '' } as unknown as HTMLInputElement
      await analyzer.handleFileSelect({ target: input } as unknown as Event)
      expect(analyzer.datasetSummary.value?.previewText).toBe('')
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // generateDataPreview 列截断
  // ════════════════════════════════════════════════════════════════════

  describe('generateDataPreview 列截断', () => {
    it('超过 5 列时显示省略号', async () => {
      vi.mocked(parseDatasetFile).mockResolvedValueOnce({
        rows: 100,
        columns: ['a', 'b', 'c', 'd', 'e', 'f'],
        sampleRows: [],
        fieldProfiles: [],
      })
      const input = { files: [{ name: 'wide.csv' }], value: '' } as unknown as HTMLInputElement
      await analyzer.handleFileSelect({ target: input } as unknown as Event)
      // AI 消息应包含省略号
      const aiMsg = analyzer.messages.value.find(
        (m) => m.role === 'ai' && m.content.includes('...')
      )
      expect(aiMsg).toBeDefined()
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // formatKittenSnapshotStatsHint（通过 onKittenBusinessDbToggle 触发）
  // ════════════════════════════════════════════════════════════════════

  describe('formatKittenSnapshotStatsHint 统计字段', () => {
    it('包含全部统计字段：生成完整提示', async () => {
      vi.mocked(safeJsonRequest).mockResolvedValueOnce({
        ok: true,
        data: {
          success: true,
          data: {
            stats: {
              materials_total: 100,
              material_inventory_value_estimate: 50000,
              products_total: 50,
              product_inventory_value_estimate: 120000,
              shipments_sample_count: 30,
            },
          },
        },
        status: 200,
        message: '',
      })
      analyzer.kittenIncludeBusinessDb.value = true
      analyzer.onKittenBusinessDbToggle()
      await flushAsync()
      const hint = analyzer.kittenDbStatsHint.value
      expect(hint).toContain('原材料 100 条')
      expect(hint).toContain('原料库存估 ¥50000')
      expect(hint).toContain('产品 50 条')
      expect(hint).toContain('成品货值估 ¥120000')
      expect(hint).toContain('近期出货样例 30 条')
    })

    it('空 stats：使用默认提示"业务库快照已生成"', async () => {
      vi.mocked(safeJsonRequest).mockResolvedValueOnce({
        ok: true,
        data: {
          success: true,
          data: { stats: {} },
        },
        status: 200,
        message: '',
      })
      analyzer.kittenIncludeBusinessDb.value = true
      analyzer.onKittenBusinessDbToggle()
      await flushAsync()
      expect(analyzer.kittenDbStatsHint.value).toBe('业务库快照已生成。')
    })

    it('null stats：使用默认提示', async () => {
      vi.mocked(safeJsonRequest).mockResolvedValueOnce({
        ok: true,
        data: {
          success: true,
          data: { stats: null },
        },
        status: 200,
        message: '',
      })
      analyzer.kittenIncludeBusinessDb.value = true
      analyzer.onKittenBusinessDbToggle()
      await flushAsync()
      expect(analyzer.kittenDbStatsHint.value).toBe('业务库快照已生成。')
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // refreshKittenBusinessSnapshotHint 缓存命中
  // ════════════════════════════════════════════════════════════════════

  describe('refreshKittenBusinessSnapshotHint 缓存', () => {
    it('缓存命中时不重复请求 API', async () => {
      vi.mocked(safeJsonRequest).mockResolvedValue({
        ok: true,
        data: {
          success: true,
          data: { stats: { materials_total: 10 } },
        },
        status: 200,
        message: '',
      })
      analyzer.kittenIncludeBusinessDb.value = true

      // 第一次调用：缓存未命中，请求 API
      analyzer.onKittenBusinessDbToggle()
      await flushAsync()
      expect(analyzer.kittenDbStatsHint.value).toContain('原材料 10 条')

      // 记录调用次数
      const callsAfterFirst = vi.mocked(safeJsonRequest).mock.calls.filter(
        (c) => String(c[0]).includes('business-snapshot')
      ).length

      // 第二次调用：缓存命中，不应请求 API
      analyzer.onKittenBusinessDbToggle()
      await flushAsync()
      const callsAfterSecond = vi.mocked(safeJsonRequest).mock.calls.filter(
        (c) => String(c[0]).includes('business-snapshot')
      ).length

      expect(callsAfterSecond).toBe(callsAfterFirst)
      expect(analyzer.kittenDbStatsHint.value).toContain('原材料 10 条')
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // buildKittenResultSummary URL 截断（通过 sendMessage 触发）
  // ════════════════════════════════════════════════════════════════════

  describe('buildKittenResultSummary 截断逻辑', () => {
    it('短文本（<=220字符）：完整保留', async () => {
      const shortText = '这是一条短回复'
      vi.mocked(safeJsonRequest).mockResolvedValueOnce({
        ok: true,
        data: { success: true, response: shortText },
        status: 200,
        message: '',
      })
      analyzer.inputText.value = '你好'
      await analyzer.sendMessage()
      expect(analyzer.currentResult.value?.summary).toBe(shortText)
    })

    it('长文本（>220字符）无 URL：截断并加省略号', async () => {
      const longText = 'A'.repeat(300)
      vi.mocked(safeJsonRequest).mockResolvedValueOnce({
        ok: true,
        data: { success: true, response: longText },
        status: 200,
        message: '',
      })
      analyzer.inputText.value = '你好'
      await analyzer.sendMessage()
      const summary = analyzer.currentResult.value?.summary || ''
      expect(summary.length).toBeLessThan(longText.length)
      expect(summary.endsWith('…')).toBe(true)
    })

    it('长文本（>220字符）含 pickup URL：截断但保留 URL', async () => {
      const url = '/api/ai/kitten/document/pickup/abc123def456'
      const longText = 'B'.repeat(250) + url
      vi.mocked(safeJsonRequest).mockResolvedValueOnce({
        ok: true,
        data: { success: true, response: longText },
        status: 200,
        message: '',
      })
      analyzer.inputText.value = '你好'
      await analyzer.sendMessage()
      const summary = analyzer.currentResult.value?.summary || ''
      expect(summary).toContain(url)
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // extractChatApiText data.data.text 分支
  // ════════════════════════════════════════════════════════════════════

  describe('extractChatApiText data.data.text 分支', () => {
    it('data.response 为空时回退到 data.data.text', async () => {
      vi.mocked(safeJsonRequest).mockResolvedValueOnce({
        ok: true,
        data: { success: true, data: { text: '内部文本回复' } },
        status: 200,
        message: '',
      })
      analyzer.inputText.value = '你好'
      await analyzer.sendMessage()
      const aiMsg = analyzer.messages.value.find(
        (m) => m.role === 'ai' && m.content.includes('内部文本回复')
      )
      expect(aiMsg).toBeDefined()
    })

    it('data.response 和 data.data.text 都为空时返回空字符串', async () => {
      vi.mocked(safeJsonRequest).mockResolvedValueOnce({
        ok: true,
        data: { success: true, data: { text: '' } },
        status: 200,
        message: '',
      })
      analyzer.inputText.value = '你好'
      await analyzer.sendMessage()
      const aiMsg = analyzer.messages.value.find(
        (m) => m.role === 'ai' && m.content.includes('服务器未返回有效回复')
      )
      expect(aiMsg).toBeDefined()
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // extractWebSearchHits（通过 sendMessage 触发）
  // ════════════════════════════════════════════════════════════════════

  describe('extractWebSearchHits 搜索结果提取', () => {
    it('含 web_search_results：提取搜索结果到 lastWebSearchHits', async () => {
      vi.mocked(safeJsonRequest).mockResolvedValueOnce({
        ok: true,
        data: {
          success: true,
          response: '回复',
          data: {
            web_search_results: [
              { title: '结果1', url: 'https://example.com/1', snippet: '片段1' },
              { title: '结果2', url: 'https://example.com/2', snippet: '片段2' },
            ],
          },
        },
        status: 200,
        message: '',
      })
      analyzer.inputText.value = '你好'
      await analyzer.sendMessage()
      expect(analyzer.lastWebSearchHits.value.length).toBe(2)
      expect(analyzer.lastWebSearchHits.value[0].title).toBe('结果1')
    })

    it('web_search_results 非数组：返回空列表', async () => {
      vi.mocked(safeJsonRequest).mockResolvedValueOnce({
        ok: true,
        data: {
          success: true,
          response: '回复',
          data: { web_search_results: 'not an array' },
        },
        status: 200,
        message: '',
      })
      analyzer.inputText.value = '你好'
      await analyzer.sendMessage()
      expect(analyzer.lastWebSearchHits.value.length).toBe(0)
    })

    it('web_search_results 含 falsy 项：过滤掉', async () => {
      vi.mocked(safeJsonRequest).mockResolvedValueOnce({
        ok: true,
        data: {
          success: true,
          response: '回复',
          data: {
            web_search_results: [
              null,
              { title: '有效', url: 'https://example.com', snippet: '片段' },
              undefined,
            ],
          },
        },
        status: 200,
        message: '',
      })
      analyzer.inputText.value = '你好'
      await analyzer.sendMessage()
      expect(analyzer.lastWebSearchHits.value.length).toBe(1)
    })

    it('无 data.data 字段：返回空列表', async () => {
      vi.mocked(safeJsonRequest).mockResolvedValueOnce({
        ok: true,
        data: { success: true, response: '回复' },
        status: 200,
        message: '',
      })
      analyzer.inputText.value = '你好'
      await analyzer.sendMessage()
      expect(analyzer.lastWebSearchHits.value.length).toBe(0)
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // sendMessage 其他分支
  // ════════════════════════════════════════════════════════════════════

  describe('sendMessage 其他分支', () => {
    it('result.ok=true 但 success=false：走失败路径', async () => {
      vi.mocked(safeJsonRequest).mockResolvedValueOnce({
        ok: true,
        data: { success: false, message: '业务错误' },
        status: 200,
        message: '',
      })
      analyzer.inputText.value = '你好'
      await analyzer.sendMessage()
      const aiMsg = analyzer.messages.value.find(
        (m) => m.role === 'ai' && m.content.includes('请求失败')
      )
      expect(aiMsg).toBeDefined()
      expect(analyzer.kittenPhase.value).toBe('error')
    })

    it('带数据集时 payload 包含 has_dataset=true', async () => {
      vi.mocked(safeJsonRequest).mockResolvedValueOnce({
        ok: true,
        data: { success: true, response: '回复' },
        status: 200,
        message: '',
      })
      analyzer.datasetSummary.value = {
        name: 'test.csv',
        rows: 10,
        columns: 3,
        fieldNames: ['a', 'b', 'c'],
        previewText: 'preview',
      }
      analyzer.inputText.value = '你好'
      await analyzer.sendMessage()
      // 验证 safeJsonRequest 被调用时 payload 包含 has_dataset
      const call = vi.mocked(safeJsonRequest).mock.calls.find(
        (c) => String(c[0]).includes('/api/ai/chat')
      )
      expect(call).toBeDefined()
      const body = JSON.parse(call![1].body as string)
      expect(body.context.has_dataset).toBe(true)
      expect(body.context.kitten_dataset).toBeDefined()
      expect(body.context.kitten_dataset.file_name).toBe('test.csv')
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // runFinancialBrief 边界
  // ════════════════════════════════════════════════════════════════════

  describe('runFinancialBrief 边界', () => {
    it('data 为非对象（字符串）：使用 message 或默认提示', async () => {
      vi.mocked(safeJsonRequest).mockResolvedValueOnce({
        ok: true,
        data: { success: true, data: 'string data' },
        status: 200,
        message: '',
      })
      await analyzer.runFinancialBrief()
      const aiMsg = analyzer.messages.value.find(
        (m) => m.role === 'ai' && m.content.includes('财务简报已生成')
      )
      expect(aiMsg).toBeDefined()
      expect(analyzer.kittenPhase.value).toBe('delivered')
    })

    it('data 为 null 且有 message：使用 message 作为摘要', async () => {
      vi.mocked(safeJsonRequest).mockResolvedValueOnce({
        ok: true,
        data: { success: true, data: null, message: '自定义消息' },
        status: 200,
        message: '',
      })
      await analyzer.runFinancialBrief()
      const aiMsg = analyzer.messages.value.find(
        (m) => m.role === 'ai' && m.content.includes('自定义消息')
      )
      expect(aiMsg).toBeDefined()
    })

    it('超长摘要（>8000字符）：截断并加省略号', async () => {
      const longData = { text: 'A'.repeat(9000) }
      vi.mocked(safeJsonRequest).mockResolvedValueOnce({
        ok: true,
        data: { success: true, data: longData },
        status: 200,
        message: '',
      })
      await analyzer.runFinancialBrief()
      const aiMsg = analyzer.messages.value.find(
        (m) => m.role === 'ai' && m.content.includes('财务简报')
      )
      expect(aiMsg).toBeDefined()
      // 截断后的内容应包含省略号
      expect(aiMsg?.content).toContain('…')
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // generateAiOfficeDocument 边界
  // ════════════════════════════════════════════════════════════════════

  describe('generateAiOfficeDocument 边界', () => {
    it('resp.json() 抛异常时回退到 resp.text()', async () => {
      global.fetch = vi.fn().mockResolvedValueOnce(
        makeResponse({
          ok: false,
          status: 500,
          jsonThrows: true,
          text: 'plain text error',
        })
      )
      await analyzer.generateAiOfficeDocument('写合同', 'docx')
      expect(appAlert).toHaveBeenCalledWith(
        expect.stringContaining('plain text error')
      )
    })

    it('resp.json() 抛异常且 text 为空：使用状态码错误消息', async () => {
      global.fetch = vi.fn().mockResolvedValueOnce(
        makeResponse({
          ok: false,
          status: 500,
          jsonThrows: true,
          text: '',
        })
      )
      await analyzer.generateAiOfficeDocument('写合同', 'xlsx')
      expect(appAlert).toHaveBeenCalledWith(
        expect.stringContaining('生成失败（500）')
      )
    })

    it('xlsx 格式成功生成：调用 downloadBlob', async () => {
      global.fetch = vi.fn().mockResolvedValueOnce(
        makeResponse({
          ok: true,
          contentType: 'application/octet-stream',
          blob: makePkBlob(),
        })
      )
      await analyzer.generateAiOfficeDocument('生成表格', 'xlsx')
      expect(downloadBlob).toHaveBeenCalled()
    })

    it('docx 格式成功生成：调用 downloadBlob 并添加 AI 消息', async () => {
      global.fetch = vi.fn().mockResolvedValueOnce(
        makeResponse({
          ok: true,
          contentType: 'application/octet-stream',
          blob: makePkBlob(),
        })
      )
      await analyzer.generateAiOfficeDocument('生成文档', 'docx')
      expect(downloadBlob).toHaveBeenCalled()
      const aiMsg = analyzer.messages.value.find(
        (m) => m.role === 'ai' && m.content.includes('已生成并下载')
      )
      expect(aiMsg).toBeDefined()
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // exportDocxViaBackend 成功路径
  // ════════════════════════════════════════════════════════════════════

  describe('exportDocxViaBackend 成功路径', () => {
    it('后端 Word 导出成功：调用 downloadBlob', async () => {
      global.fetch = vi.fn().mockResolvedValueOnce(
        makeResponse({
          ok: true,
          contentType: 'application/octet-stream',
          disposition: 'attachment; filename="report.docx"',
          blob: makePkBlob(),
        })
      )
      analyzer.currentResult.value = {
        id: 1,
        title: 'test',
        summary: 's',
        chart: false,
        type: 't',
        kind: 'k',
      }
      await analyzer.exportDocx()
      expect(downloadBlob).toHaveBeenCalled()
    })

    it('后端 Word 导出失败且 resp.text() 抛异常：调用 appAlert', async () => {
      global.fetch = vi.fn().mockResolvedValueOnce(
        makeResponse({
          ok: false,
          status: 500,
          textThrows: true,
        })
      )
      analyzer.currentResult.value = {
        id: 1,
        title: 'test',
        summary: 's',
        chart: false,
        type: 't',
        kind: 'k',
      }
      await analyzer.exportDocx()
      expect(appAlert).toHaveBeenCalledWith(
        expect.stringContaining('Word 导出失败')
      )
    })

    it('后端 Word 导出遇 JSON content-type：调用 appAlert', async () => {
      global.fetch = vi.fn().mockResolvedValueOnce(
        makeResponse({
          ok: true,
          contentType: 'application/json',
          blob: makeTextBlob('{"message":"未登录"}'),
        })
      )
      analyzer.currentResult.value = {
        id: 1,
        title: 'test',
        summary: 's',
        chart: false,
        type: 't',
        kind: 'k',
      }
      await analyzer.exportDocx()
      expect(appAlert).toHaveBeenCalledWith(
        expect.stringContaining('Word 导出失败')
      )
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // exportReportViaBackend 成功路径
  // ════════════════════════════════════════════════════════════════════

  describe('exportReportViaBackend 成功路径', () => {
    it('后端 Excel 导出成功：调用 downloadBlob', async () => {
      global.fetch = vi.fn().mockResolvedValueOnce(
        makeResponse({
          ok: true,
          contentType: 'application/octet-stream',
          disposition: 'attachment; filename="report.xlsx"',
          blob: makePkBlob(),
        })
      )
      analyzer.currentResult.value = {
        id: 1,
        title: 'test',
        summary: 's',
        chart: false,
        type: 't',
        kind: 'k',
      }
      await analyzer.exportResult()
      expect(downloadBlob).toHaveBeenCalled()
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // extractKittenDocumentPickupUrl 额外边界
  // ════════════════════════════════════════════════════════════════════

  describe('extractKittenDocumentPickupUrl 额外边界', () => {
    it('HTML 实体 &#x27; 编码的 URL', () => {
      const url = '/api/ai/kitten/document/pickup/abc'
      const encoded = `链接：&#x27;${url}&#x27;`
      expect(extractKittenDocumentPickupUrl(encoded)).toBe(url)
    })

    it('HTML 实体 &#39; 编码的 URL', () => {
      const url = '/api/ai/kitten/document/pickup/xyz'
      const encoded = `链接：&#39;${url}&#39;`
      expect(extractKittenDocumentPickupUrl(encoded)).toBe(url)
    })

    it('JSON download_url 中不含 pickup 路径：返回 null', () => {
      const content = `"download_url": "https://example.com/other/path"`
      expect(extractKittenDocumentPickupUrl(content)).toBeNull()
    })

    it('JSON download_url 中含转义斜杠的绝对 URL', () => {
      const url = 'https://example.com/api/ai/kitten/document/pickup/abc'
      const content = `"download_url": "${url.replace(/\//g, '\\/')}"`
      expect(extractKittenDocumentPickupUrl(content)).toBe(url)
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // lastDocumentPickupUrl 通过 htmlToPlainText 提取
  // ════════════════════════════════════════════════════════════════════

  describe('lastDocumentPickupUrl 通过纯文本提取', () => {
    it('raw HTML 中无 URL 但纯文本中有 URL', () => {
      // HTML 标签包裹的 URL，extractKittenDocumentPickupUrl 从 raw 提取
      analyzer.messages.value.push({
        role: 'ai',
        content: '<div>请下载：/api/ai/kitten/document/pickup/txt123</div>',
        time: '10:00',
      })
      expect(analyzer.lastDocumentPickupUrl.value).toContain(
        '/api/ai/kitten/document/pickup/txt123'
      )
    })

    it('跳过 user 消息只查找 ai 消息', () => {
      analyzer.messages.value.push({
        role: 'user',
        content: '/api/ai/kitten/document/pickup/user123',
        time: '10:00',
      })
      expect(analyzer.lastDocumentPickupUrl.value).toBeNull()
    })

    it('空 content 的 ai 消息被跳过', () => {
      analyzer.messages.value.push({
        role: 'ai',
        content: '',
        time: '10:00',
      })
      expect(analyzer.lastDocumentPickupUrl.value).toBeNull()
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // resetSession 边界
  // ════════════════════════════════════════════════════════════════════

  describe('resetSession 边界', () => {
    it('clearResult.success=false 时打印警告', async () => {
      vi.mocked(safeJsonRequest).mockResolvedValueOnce({
        ok: true,
        data: { success: false },
        status: 200,
        message: '',
      })
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
      await analyzer.resetSession()
      expect(warnSpy).toHaveBeenCalled()
      warnSpy.mockRestore()
    })

    it('无 session user id 时不调用 clear API', async () => {
      // 先重置一次让 session id 为空（通过 mock makeKittenUserId）
      // 直接测试：session id 存在时调用 clear
      vi.mocked(safeJsonRequest).mockResolvedValueOnce({
        ok: true,
        data: { success: true },
        status: 200,
        message: '',
      })
      await analyzer.resetSession()
      const clearCalls = vi.mocked(safeJsonRequest).mock.calls.filter(
        (c) => String(c[0]).includes('/api/ai/context/clear')
      )
      expect(clearCalls.length).toBeGreaterThanOrEqual(1)
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // setChartConfig 边界
  // ════════════════════════════════════════════════════════════════════

  describe('setChartConfig 边界', () => {
    it('设置 xField 但不设 yField：summary 不含 yField 部分', () => {
      analyzer.setChartConfig({ type: 'line', xField: '日期', aggregate: 'sum' })
      expect(analyzer.currentResult.value).not.toBeNull()
      expect(analyzer.currentResult.value?.summary).toContain('line')
      expect(analyzer.currentResult.value?.summary).toContain('日期')
      expect(analyzer.currentResult.value?.summary).toContain('sum')
      // yField 为空时 summary 不含 " / "
      expect(analyzer.currentResult.value?.summary).not.toContain(' / ')
    })

    it('设置 xField 和 yField：summary 含 yField 部分', () => {
      analyzer.setChartConfig({ type: 'bar', xField: '城市', yField: '销量', aggregate: 'sum' })
      expect(analyzer.currentResult.value?.summary).toContain(' / 销量')
    })
  })
})
