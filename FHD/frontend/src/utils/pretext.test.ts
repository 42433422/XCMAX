import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('@chenglou/pretext', () => ({
  prepare: vi.fn(() => ({ prepared: true })),
  layout: vi.fn(() => ({ width: 120, height: 40, lineCount: 2 })),
  prepareWithSegments: vi.fn(() => ({ prepared: true })),
  layoutWithLines: vi.fn(() => ({
    width: 120,
    height: 40,
    lines: [{ text: 'line1' }, { text: 'line2' }],
  })),
}))

import {
  measureText,
  measureTextWithLines,
  batchMeasure,
  clearMeasureCache,
  getCacheStats,
  estimateMessageHeight,
  batchEstimateMessageHeights,
  calculateTableRowHeights,
  calculateLabelLayout,
  measureTextWithStats,
  getPerformanceStats,
} from './pretext'

describe('pretext text measurement', () => {
  beforeEach(() => {
    clearMeasureCache()
  })

  it('measures text width and height', () => {
    const result = measureText({ text: 'Hello World', width: 200, fontSize: 14 })
    expect(result.width).toBe(120)
    expect(result.height).toBe(40)
    expect(result.lineCount).toBe(2)
  })

  it('caches repeated measurements', () => {
    const opts = { text: '缓存测试', width: 150, fontSize: 16 }
    measureText(opts)
    const before = getCacheStats().size
    measureText(opts)
    expect(getCacheStats().size).toBe(before)
  })

  it('measureTextWithLines returns line content', () => {
    const result = measureTextWithLines({
      text: '第一行\n第二行',
      width: 80,
      fontSize: 14,
      whiteSpace: 'pre-wrap',
    })
    expect(result.lines).toEqual(['line1', 'line2'])
  })

  it('batchMeasure maps items', () => {
    const results = batchMeasure([
      { text: 'A', width: 100 },
      { text: 'B', width: 100 },
    ])
    expect(results).toHaveLength(2)
  })

  it('estimateMessageHeight strips HTML', () => {
    const h = estimateMessageHeight('<b>标题</b>内容', 300)
    expect(h).toBe(40)
  })

  it('batchEstimateMessageHeights', () => {
    const heights = batchEstimateMessageHeights(
      [{ content: 'msg1' }, { content: 'msg2', fontSize: 12 }],
      200,
    )
    expect(heights).toEqual([40, 40])
  })

  it('calculateTableRowHeights adds padding', () => {
    const rows = calculateTableRowHeights(['cell1', 'longer cell content'], 100)
    expect(rows[0]).toBe(56)
  })

  it('calculateLabelLayout picks fitting font size', () => {
    const layout = calculateLabelLayout('短标签', 100, 50)
    expect(layout.fontSize).toBeGreaterThanOrEqual(8)
    expect(layout.lines.length).toBeGreaterThanOrEqual(1)
  })

  it('measureTextWithStats tracks measurements', () => {
    const opts = { text: 'stats', width: 120, fontSize: 14 }
    measureTextWithStats(opts)
    measureTextWithStats(opts)
    const stats = getPerformanceStats()
    expect(stats.totalMeasurements).toBeGreaterThanOrEqual(2)
  })

  it('clearMeasureCache resets cache', () => {
    measureText({ text: 'x', width: 50 })
    clearMeasureCache()
    expect(getCacheStats().size).toBe(0)
  })
})
