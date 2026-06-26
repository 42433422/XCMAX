import { describe, it, expect, vi, beforeEach } from 'vitest'

const { mockPrepare, mockLayout, mockPrepareWithSegments, mockLayoutWithLines } = vi.hoisted(() => ({
  mockPrepare: vi.fn(),
  mockLayout: vi.fn(),
  mockPrepareWithSegments: vi.fn(),
  mockLayoutWithLines: vi.fn(),
}))

vi.mock('@chenglou/pretext', () => ({
  prepare: mockPrepare,
  layout: mockLayout,
  prepareWithSegments: mockPrepareWithSegments,
  layoutWithLines: mockLayoutWithLines,
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
  getPerformanceStats,
  measureTextWithStats,
} from './pretext'

describe('pretext', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    clearMeasureCache()
    mockPrepare.mockReturnValue('prepared-data')
    mockLayout.mockReturnValue({ width: 100, height: 30, lineCount: 1 })
    mockPrepareWithSegments.mockReturnValue('prepared-segments')
    mockLayoutWithLines.mockReturnValue({
      width: 100,
      height: 30,
      lines: [{ text: 'line1' }, { text: 'line2' }],
    })
  })

  describe('measureText', () => {
    it('returns measurement result for basic text', () => {
      const result = measureText({ text: 'hello', width: 200 })
      expect(result.width).toBe(100)
      expect(result.height).toBe(30)
      expect(result.lineCount).toBe(1)
      expect(result.lines).toEqual([])
    })

    it('uses default fontSize and lineHeight when not provided', () => {
      measureText({ text: 'test', width: 100 })
      expect(mockLayout).toHaveBeenCalledWith('prepared-data', 100, 14 * 1.5)
    })

    it('uses custom fontSize and lineHeight', () => {
      measureText({ text: 'test', width: 100, fontSize: 20, lineHeight: 2 })
      expect(mockLayout).toHaveBeenCalledWith('prepared-data', 100, 40)
    })

    it('passes whiteSpace and wordBreak to prepare', () => {
      measureText({ text: 'test', width: 100, whiteSpace: 'pre-wrap', wordBreak: 'keep-all' })
      expect(mockPrepare).toHaveBeenCalledWith('test', expect.any(String), {
        whiteSpace: 'pre-wrap',
        wordBreak: 'keep-all',
        letterSpacing: undefined,
      })
    })

    it('defaults whiteSpace to normal', () => {
      measureText({ text: 'test', width: 100 })
      expect(mockPrepare).toHaveBeenCalledWith('test', expect.any(String), expect.objectContaining({ whiteSpace: 'normal' }))
    })

    it('caches prepared data for same text and options', () => {
      measureText({ text: 'cached', width: 100 })
      measureText({ text: 'cached', width: 200 })
      expect(mockPrepare).toHaveBeenCalledTimes(1)
    })

    it('does not use cache for different text', () => {
      measureText({ text: 'text1', width: 100 })
      measureText({ text: 'text2', width: 100 })
      expect(mockPrepare).toHaveBeenCalledTimes(2)
    })

    it('uses custom fontFamily and fontWeight in font string', () => {
      measureText({ text: 'test', width: 100, fontFamily: 'Arial', fontWeight: '700' })
      expect(mockPrepare).toHaveBeenCalledWith('test', '700 14px Arial', expect.any(Object))
    })
  })

  describe('measureTextWithLines', () => {
    it('returns measurement result with line contents', () => {
      const result = measureTextWithLines({ text: 'hello world', width: 200 })
      expect(result.lines).toEqual(['line1', 'line2'])
      expect(result.lineCount).toBe(2)
    })

    it('calls prepareWithSegments and layoutWithLines', () => {
      measureTextWithLines({ text: 'test', width: 100, fontSize: 16, lineHeight: 1.5 })
      expect(mockPrepareWithSegments).toHaveBeenCalled()
      expect(mockLayoutWithLines).toHaveBeenCalledWith('prepared-segments', 100, 24)
    })
  })

  describe('batchMeasure', () => {
    it('returns array of measurements for multiple items', () => {
      const results = batchMeasure([
        { text: 'a', width: 100 },
        { text: 'b', width: 100 },
      ])
      expect(results).toHaveLength(2)
      expect(results[0].width).toBe(100)
    })

    it('returns empty array for empty input', () => {
      const results = batchMeasure([])
      expect(results).toEqual([])
    })
  })

  describe('clearMeasureCache and getCacheStats', () => {
    it('clears the cache', () => {
      measureText({ text: 'test', width: 100 })
      expect(getCacheStats().size).toBe(1)
      clearMeasureCache()
      expect(getCacheStats().size).toBe(0)
    })

    it('getCacheStats returns size and maxSize', () => {
      const stats = getCacheStats()
      expect(stats).toHaveProperty('size')
      expect(stats).toHaveProperty('maxSize')
      expect(stats.maxSize).toBe(500)
    })
  })

  describe('estimateMessageHeight', () => {
    it('strips HTML tags before measuring', () => {
      estimateMessageHeight('<p>hello</p>', 200)
      expect(mockPrepare).toHaveBeenCalledWith('hello', expect.any(String), expect.any(Object))
    })

    it('returns the height from measurement', () => {
      mockLayout.mockReturnValue({ width: 200, height: 42, lineCount: 2 })
      const h = estimateMessageHeight('text', 200)
      expect(h).toBe(42)
    })

    it('uses default fontSize of 14', () => {
      estimateMessageHeight('text', 200)
      expect(mockLayout).toHaveBeenCalledWith(expect.anything(), 200, 21)
    })

    it('uses custom fontSize', () => {
      estimateMessageHeight('text', 200, 18)
      expect(mockLayout).toHaveBeenCalledWith(expect.anything(), 200, 27)
    })
  })

  describe('batchEstimateMessageHeights', () => {
    it('returns heights for multiple messages', () => {
      mockLayout.mockReturnValue({ width: 200, height: 30, lineCount: 1 })
      const heights = batchEstimateMessageHeights(
        [{ content: 'a' }, { content: 'b', fontSize: 18 }],
        200
      )
      expect(heights).toEqual([30, 30])
    })

    it('returns empty array for empty input', () => {
      expect(batchEstimateMessageHeights([], 200)).toEqual([])
    })
  })

  describe('calculateTableRowHeights', () => {
    it('returns heights with padding for each cell', () => {
      mockLayout.mockReturnValue({ width: 100, height: 20, lineCount: 1 })
      const heights = calculateTableRowHeights(['cell1', 'cell2'], 100)
      expect(heights).toEqual([36, 36])
    })

    it('uses monospace font family', () => {
      calculateTableRowHeights(['cell'], 100)
      expect(mockPrepare).toHaveBeenCalledWith('cell', expect.stringContaining('monospace'), expect.any(Object))
    })

    it('uses default fontSize of 12', () => {
      calculateTableRowHeights(['cell'], 100)
      expect(mockLayout).toHaveBeenCalledWith(expect.anything(), 100, 12 * 1.4)
    })
  })

  describe('calculateLabelLayout', () => {
    it('returns layout with fontSize and lines when text fits', () => {
      mockLayoutWithLines.mockReturnValue({ width: 100, height: 20, lines: [{ text: 'label' }] })
      const layout = calculateLabelLayout('label', 100, 30)
      expect(layout.fontSize).toBe(16)
      expect(layout.lines).toEqual(['label'])
      expect(layout.lineHeight).toBe(16 * 1.2)
    })

    it('tries smaller font sizes when text does not fit', () => {
      mockLayoutWithLines
        .mockReturnValueOnce({ width: 100, height: 50, lines: [{ text: 'label' }] })
        .mockReturnValueOnce({ width: 100, height: 40, lines: [{ text: 'label' }] })
        .mockReturnValueOnce({ width: 100, height: 20, lines: [{ text: 'label' }] })
      const layout = calculateLabelLayout('label', 100, 30)
      expect(layout.fontSize).toBe(12)
    })

    it('uses smallest font and truncates when nothing fits', () => {
      mockLayoutWithLines.mockReturnValue({ width: 100, height: 100, lines: [{ text: 'l1' }, { text: 'l2' }, { text: 'l3' }] })
      const layout = calculateLabelLayout('long label', 50, 20)
      expect(layout.fontSize).toBe(8)
      expect(layout.lineHeight).toBe(8 * 1.2)
    })
  })

  describe('getPerformanceStats', () => {
    it('returns stats with totalMeasurements, cachedMeasurements, and cacheHitRate', () => {
      const stats = getPerformanceStats()
      expect(stats).toHaveProperty('totalMeasurements')
      expect(stats).toHaveProperty('cachedMeasurements')
      expect(stats).toHaveProperty('cacheHitRate')
    })

    it('returns cacheHitRate of 0 when no measurements', () => {
      const stats = getPerformanceStats()
      expect(stats.cacheHitRate).toBe(0)
    })
  })

  describe('measureTextWithStats', () => {
    it('increments totalMeasurements on each call', () => {
      const before = getPerformanceStats().totalMeasurements
      measureTextWithStats({ text: 'stat-test', width: 100 })
      const after = getPerformanceStats().totalMeasurements
      expect(after).toBe(before + 1)
    })

    it('increments cachedMeasurements on cache hit', () => {
      measureTextWithStats({ text: 'cache-test', width: 100 })
      const before = getPerformanceStats().cachedMeasurements
      measureTextWithStats({ text: 'cache-test', width: 200 })
      const after = getPerformanceStats().cachedMeasurements
      expect(after).toBe(before + 1)
    })

    it('returns measurement result', () => {
      const result = measureTextWithStats({ text: 'test', width: 100 })
      expect(result.width).toBe(100)
      expect(result.height).toBe(30)
    })
  })
})
