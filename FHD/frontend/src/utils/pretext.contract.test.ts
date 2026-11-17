import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { clearCache } from '@chenglou/pretext'
import { clearMeasureCache, measureText, measureTextWithLines } from './pretext'

beforeEach(() => {
  // Only canvas glyph metrics are synthetic; use the installed SDK's real preparation/layout.
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({
    font: '',
    measureText: (text: string) => ({ width: text.length * 10 }),
  } as unknown as CanvasRenderingContext2D)
  clearCache()
  clearMeasureCache()
})
afterEach(() => vi.restoreAllMocks())

it('returns finite line widths from the real SDK across cached resize and empty text', () => {
  for (const [width, expectedWidth, expectedLines] of [[200, 100, 1], [60, 50, 2]]) {
    const options = { text: 'alpha beta', width, fontSize: 14 }
    const measured = measureText(options)
    const detailed = measureTextWithLines(options)
    expect(measured.width).toBe(expectedWidth)
    expect(measured.lineCount).toBe(expectedLines)
    expect(measured.height).toBe(expectedLines * 21)
    expect(detailed.width).toBe(measured.width)
    expect(detailed.lineCount).toBe(measured.lineCount)
    expect(detailed.lines.join('')).toBe('alpha beta')
  }
  expect(measureText({ text: '', width: 60 })).toEqual({ width: 0, height: 0, lineCount: 0, lines: [] })
})
