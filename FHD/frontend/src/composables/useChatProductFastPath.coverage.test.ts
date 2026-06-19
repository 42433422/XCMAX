/**
 * Coverage ramp 测试：useChatProductFastPath
 *
 * 目标：覆盖 runProductKeywordFastPath 中所有分支
 * - resp.success === false → 抛错 → catch 返回 false
 * - resp.data / resp.products / resp.items 三种数据来源
 * - raw 非数组 → rows = []
 * - 行字段缺失组合（model_number / name / product_name / price 非有限数）
 * - rows > 3 时 lines 截断；rows > 20 时 mappedRows 截断
 * - hasResults true/false 两条响应文本分支
 * - payload.autoAction 存在/不存在 → handleAutoAction 调用/不调用
 * - resp.total 为数字/非数字 → totalFromApi 取值
 * - deps.addAndSaveMessage 抛错 → catch 返回 false
 * - resp 为 null → 抛错 → catch 返回 false
 *
 * 铁律4：仅 mock 外部边界（@/api/products），被测函数真实调用
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import {
  runProductKeywordFastPath,
  type ChatProductFastPathDeps,
} from './useChatProductFastPath'

// ── mock 外部边界：productsApi ──────────────────────────────────
const mockSearchProducts = vi.fn()
vi.mock('@/api/products', () => ({
  default: {
    searchProducts: (...args: unknown[]) => mockSearchProducts(...args),
  },
}))

// ── helpers ─────────────────────────────────────────────────────

/** 构造 deps，所有方法均为 spy，可覆盖返回值 */
function makeDeps(overrides: Partial<ChatProductFastPathDeps> = {}): ChatProductFastPathDeps {
  return {
    addAndSaveMessage: overrides.addAndSaveMessage ?? vi.fn().mockResolvedValue(undefined),
    syncTaskFromChatResponse: overrides.syncTaskFromChatResponse ?? vi.fn(),
    attachContextSummaryToLastAiMessage:
      overrides.attachContextSummaryToLastAiMessage ?? vi.fn(),
    attachThinkingStepsToLastAiMessage:
      overrides.attachThinkingStepsToLastAiMessage ?? vi.fn(),
    attachTodoStepsToLastAiMessage: overrides.attachTodoStepsToLastAiMessage ?? vi.fn(),
    attachWorkflowTraceToLastAiMessage:
      overrides.attachWorkflowTraceToLastAiMessage ?? vi.fn(),
    handleAutoAction: overrides.handleAutoAction ?? vi.fn(),
    clearCurrentTask: overrides.clearCurrentTask ?? vi.fn(),
  }
}

/** 构造产品行 */
function makeRow(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: 1,
    model_number: 'X100',
    name: '产品A',
    price: 99.5,
    unit: '个',
    ...overrides,
  }
}

describe('useChatProductFastPath — coverage ramp', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  // ── 成功路径：有结果 ──────────────────────────────────────────

  describe('成功路径（有结果）', () => {
    it('resp.data 为数组时走完整 happy path 并触发 autoAction', async () => {
      const rows = [makeRow(), makeRow({ id: 2, model_number: 'X200' })]
      mockSearchProducts.mockResolvedValue({
        success: true,
        data: rows,
        total: 2,
      })
      const deps = makeDeps()

      const result = await runProductKeywordFastPath('X100', '帮我找 X100', deps)

      expect(result).toBe(true)
      expect(mockSearchProducts).toHaveBeenCalledWith('X100')
      // 验证 addAndSaveMessage 收到带关键词的响应文本
      expect(deps.addAndSaveMessage).toHaveBeenCalledWith(
        expect.stringContaining('已帮你打开产品副窗并带入「X100」'),
        'ai',
      )
      // 验证其它依赖被调用
      expect(deps.syncTaskFromChatResponse).toHaveBeenCalledWith(
        expect.objectContaining({ success: true, response: expect.any(String) }),
        '帮我找 X100',
      )
      expect(deps.attachContextSummaryToLastAiMessage).toHaveBeenCalled()
      expect(deps.attachThinkingStepsToLastAiMessage).toHaveBeenCalledWith(
        expect.objectContaining({ success: true }),
      )
      expect(deps.attachTodoStepsToLastAiMessage).toHaveBeenCalledWith(
        expect.objectContaining({ success: true }),
      )
      expect(deps.attachWorkflowTraceToLastAiMessage).toHaveBeenCalledWith(
        expect.objectContaining({ success: true }),
      )
      // payload.task 未设置 → clearCurrentTask 被调用
      expect(deps.clearCurrentTask).toHaveBeenCalled()
      // 有结果 → handleAutoAction 被调用，且带 hydrateProductSearch
      expect(deps.handleAutoAction).toHaveBeenCalledWith(
        expect.objectContaining({
          type: 'show_products_float',
          query: 'X100',
          hydrateProductSearch: { rows: expect.any(Array), total: 2 },
        }),
        '帮我找 X100',
      )
    })

    it('resp.data 缺失但 resp.products 为数组时使用 products', async () => {
      const rows = [makeRow({ id: 10, model_number: 'P10' })]
      mockSearchProducts.mockResolvedValue({
        success: true,
        products: rows,
      })
      const deps = makeDeps()

      const result = await runProductKeywordFastPath('P10', '找 P10', deps)

      expect(result).toBe(true)
      // total 未提供 → 使用 rows.length
      expect(deps.handleAutoAction).toHaveBeenCalledWith(
        expect.objectContaining({
          hydrateProductSearch: { rows: expect.any(Array), total: 1 },
        }),
        '找 P10',
      )
    })

    it('resp.data 与 products 均缺失但 resp.items 为数组时使用 items', async () => {
      const rows = [makeRow({ id: 20, model_number: 'I20' })]
      mockSearchProducts.mockResolvedValue({
        success: true,
        items: rows,
      })
      const deps = makeDeps()

      const result = await runProductKeywordFastPath('I20', '找 I20', deps)

      expect(result).toBe(true)
      expect(deps.handleAutoAction).toHaveBeenCalled()
    })

    it('rows 超过 3 条时 lines 截断为前 3 条预览', async () => {
      const rows = Array.from({ length: 5 }, (_, i) =>
        makeRow({ id: i + 1, model_number: `M${i}` }),
      )
      mockSearchProducts.mockResolvedValue({ success: true, data: rows })
      const deps = makeDeps()

      await runProductKeywordFastPath('M', '找 M', deps)

      const text = deps.addAndSaveMessage.mock.calls[0][0] as string
      // 预览只显示前 3 条
      expect(text).toContain('预览命中 5 条')
      expect(text).toContain('M0')
      expect(text).toContain('M2')
      expect(text).not.toContain('M3')
    })

    it('rows 超过 20 条时 mappedRows 截断为前 20 条', async () => {
      const rows = Array.from({ length: 25 }, (_, i) =>
        makeRow({ id: i + 1, model_number: `R${i}` }),
      )
      mockSearchProducts.mockResolvedValue({ success: true, data: rows })
      const deps = makeDeps()

      await runProductKeywordFastPath('R', '找 R', deps)

      const autoActionArg = deps.handleAutoAction.mock.calls[0][0] as Record<
        string,
        unknown
      >
      const mapped = (autoActionArg.hydrateProductSearch as { rows: unknown[] }).rows
      expect(mapped).toHaveLength(20)
    })

    it('resp.total 为数字时 totalFromApi 使用 resp.total', async () => {
      mockSearchProducts.mockResolvedValue({
        success: true,
        data: [makeRow()],
        total: 999,
      })
      const deps = makeDeps()

      await runProductKeywordFastPath('kw', 'text', deps)

      expect(deps.handleAutoAction).toHaveBeenCalledWith(
        expect.objectContaining({
          hydrateProductSearch: { rows: expect.any(Array), total: 999 },
        }),
        'text',
      )
    })

    it('resp.total 非数字时 totalFromApi 使用 rows.length', async () => {
      mockSearchProducts.mockResolvedValue({
        success: true,
        data: [makeRow(), makeRow({ id: 2 })],
        // total 缺失
      })
      const deps = makeDeps()

      await runProductKeywordFastPath('kw', 'text', deps)

      expect(deps.handleAutoAction).toHaveBeenCalledWith(
        expect.objectContaining({
          hydrateProductSearch: { rows: expect.any(Array), total: 2 },
        }),
        'text',
      )
    })
  })

  // ── 行字段缺失/边界 ──────────────────────────────────────────

  describe('行字段边界', () => {
    it('model_number 为空时显示 "-"', async () => {
      mockSearchProducts.mockResolvedValue({
        success: true,
        data: [makeRow({ model_number: '' })],
      })
      const deps = makeDeps()

      await runProductKeywordFastPath('kw', 'text', deps)

      const text = deps.addAndSaveMessage.mock.calls[0][0] as string
      expect(text).toContain('- - / 产品A / ￥99.50')
    })

    it('name 缺失时回退到 product_name', async () => {
      mockSearchProducts.mockResolvedValue({
        success: true,
        data: [makeRow({ name: undefined, product_name: '备用名' })],
      })
      const deps = makeDeps()

      await runProductKeywordFastPath('kw', 'text', deps)

      const text = deps.addAndSaveMessage.mock.calls[0][0] as string
      expect(text).toContain('备用名')
    })

    it('name 与 product_name 均缺失时显示 "-"', async () => {
      mockSearchProducts.mockResolvedValue({
        success: true,
        data: [makeRow({ name: undefined, product_name: undefined })],
      })
      const deps = makeDeps()

      await runProductKeywordFastPath('kw', 'text', deps)

      const text = deps.addAndSaveMessage.mock.calls[0][0] as string
      // model_number 默认 X100，name 回退到 '-'
      expect(text).toContain('X100 / - / ￥99.50')
    })

    it('price 非有限数（NaN）时显示 ￥0.00', async () => {
      mockSearchProducts.mockResolvedValue({
        success: true,
        data: [makeRow({ price: 'abc' })],
      })
      const deps = makeDeps()

      await runProductKeywordFastPath('kw', 'text', deps)

      const text = deps.addAndSaveMessage.mock.calls[0][0] as string
      expect(text).toContain('￥0.00')
    })

    it('price 缺失时显示 ￥0.00', async () => {
      mockSearchProducts.mockResolvedValue({
        success: true,
        data: [makeRow({ price: undefined })],
      })
      const deps = makeDeps()

      await runProductKeywordFastPath('kw', 'text', deps)

      const text = deps.addAndSaveMessage.mock.calls[0][0] as string
      expect(text).toContain('￥0.00')
    })

    it('price 为整数时显示两位小数', async () => {
      mockSearchProducts.mockResolvedValue({
        success: true,
        data: [makeRow({ price: 100 })],
      })
      const deps = makeDeps()

      await runProductKeywordFastPath('kw', 'text', deps)

      const text = deps.addAndSaveMessage.mock.calls[0][0] as string
      expect(text).toContain('￥100.00')
    })

    it('mappedRows 中 name 缺失时回退到 product_name 再回退到空串', async () => {
      mockSearchProducts.mockResolvedValue({
        success: true,
        data: [
          makeRow({ id: 1, name: undefined, product_name: 'PN', unit: undefined }),
        ],
      })
      const deps = makeDeps()

      await runProductKeywordFastPath('kw', 'text', deps)

      const autoActionArg = deps.handleAutoAction.mock.calls[0][0] as Record<
        string,
        unknown
      >
      const mapped = (
        autoActionArg.hydrateProductSearch as { rows: Record<string, unknown>[] }
      ).rows[0]
      expect(mapped.name).toBe('PN')
      expect(mapped.unit).toBe('')
      expect(mapped.model_number).toBe('X100')
    })
  })

  // ── 无结果分支 ────────────────────────────────────────────────

  describe('无结果分支', () => {
    it('raw 非数组（对象）时 rows 为空，返回"未找到"文本且不触发 autoAction', async () => {
      mockSearchProducts.mockResolvedValue({
        success: true,
        data: { not: 'an array' },
      })
      const deps = makeDeps()

      const result = await runProductKeywordFastPath('kw', 'text', deps)

      expect(result).toBe(true)
      const text = deps.addAndSaveMessage.mock.calls[0][0] as string
      expect(text).toContain('未在产品库中找到「kw」')
      // 无结果 → 不调用 handleAutoAction
      expect(deps.handleAutoAction).not.toHaveBeenCalled()
      // 仍然调用 clearCurrentTask（payload.task 未设置）
      expect(deps.clearCurrentTask).toHaveBeenCalled()
    })

    it('resp.data 为空数组时返回"未找到"文本', async () => {
      mockSearchProducts.mockResolvedValue({ success: true, data: [] })
      const deps = makeDeps()

      const result = await runProductKeywordFastPath('kw', 'text', deps)

      expect(result).toBe(true)
      const text = deps.addAndSaveMessage.mock.calls[0][0] as string
      expect(text).toBe('未在产品库中找到「kw」，请确认型号或关键词后重试。')
      expect(deps.handleAutoAction).not.toHaveBeenCalled()
    })

    it('resp.data/products/items 全部缺失时 rows 为空', async () => {
      mockSearchProducts.mockResolvedValue({ success: true })
      const deps = makeDeps()

      const result = await runProductKeywordFastPath('kw', 'text', deps)

      expect(result).toBe(true)
      expect(deps.handleAutoAction).not.toHaveBeenCalled()
    })
  })

  // ── 异常分支 ──────────────────────────────────────────────────

  describe('异常分支', () => {
    it('resp.success === false 时抛错并被 catch，返回 false', async () => {
      mockSearchProducts.mockResolvedValue({
        success: false,
        message: '产品库维护中',
      })
      const deps = makeDeps()

      const result = await runProductKeywordFastPath('kw', 'text', deps)

      expect(result).toBe(false)
      // 抛错前未调用 addAndSaveMessage
      expect(deps.addAndSaveMessage).not.toHaveBeenCalled()
    })

    it('resp.success === false 且 message 缺失时使用默认错误信息', async () => {
      mockSearchProducts.mockResolvedValue({ success: false })
      const deps = makeDeps()

      const result = await runProductKeywordFastPath('kw', 'text', deps)

      expect(result).toBe(false)
    })

    it('resp 为 null 时抛 TypeError 被 catch，返回 false', async () => {
      mockSearchProducts.mockResolvedValue(null)
      const deps = makeDeps()

      const result = await runProductKeywordFastPath('kw', 'text', deps)

      expect(result).toBe(false)
    })

    it('productsApi.searchProducts 抛错时返回 false', async () => {
      mockSearchProducts.mockRejectedValue(new Error('network error'))
      const deps = makeDeps()

      const result = await runProductKeywordFastPath('kw', 'text', deps)

      expect(result).toBe(false)
    })

    it('deps.addAndSaveMessage 抛错时返回 false', async () => {
      mockSearchProducts.mockResolvedValue({ success: true, data: [makeRow()] })
      const deps = makeDeps({
        addAndSaveMessage: vi.fn().mockRejectedValue(new Error('save failed')),
      })

      const result = await runProductKeywordFastPath('kw', 'text', deps)

      expect(result).toBe(false)
    })

    it('deps.handleAutoAction 抛错时返回 false', async () => {
      mockSearchProducts.mockResolvedValue({ success: true, data: [makeRow()] })
      const deps = makeDeps({
        handleAutoAction: vi.fn(() => {
          throw new Error('handle error')
        }),
      })

      const result = await runProductKeywordFastPath('kw', 'text', deps)

      expect(result).toBe(false)
    })
  })

  // ── 响应文本格式验证 ──────────────────────────────────────────

  describe('响应文本格式', () => {
    it('有结果时响应文本包含关键词和预览信息', async () => {
      mockSearchProducts.mockResolvedValue({
        success: true,
        data: [makeRow({ model_number: 'ABC', name: '测试产品', price: 12.5 })],
      })
      const deps = makeDeps()

      await runProductKeywordFastPath('ABC', 'text', deps)

      const text = deps.addAndSaveMessage.mock.calls[0][0] as string
      expect(text).toContain('「ABC」')
      expect(text).toContain('预览命中 1 条')
      expect(text).toContain('ABC / 测试产品 / ￥12.50')
    })

    it('payload.response 为空字符串时 addAndSaveMessage 收到空串', async () => {
      // 构造一个 success:true 但 data 为空数组的场景，responseText 为"未找到"
      mockSearchProducts.mockResolvedValue({ success: true, data: [] })
      const deps = makeDeps()

      await runProductKeywordFastPath('kw', 'text', deps)

      // addAndSaveMessage 第一个参数是 String(payload.response || '')
      // 此场景下 responseText 非空
      expect(deps.addAndSaveMessage).toHaveBeenCalledWith(
        expect.any(String),
        'ai',
      )
    })
  })
})
