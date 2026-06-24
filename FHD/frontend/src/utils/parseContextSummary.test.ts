import { describe, it, expect } from 'vitest'
import { parseContextSummary } from './parseContextSummary'

describe('parseContextSummary', () => {
  it('returns empty chips and null total for empty string', () => {
    const result = parseContextSummary('')
    expect(result.chips).toEqual([])
    expect(result.total).toBeNull()
  })

  it('returns empty chips and null total for undefined', () => {
    const result = parseContextSummary(undefined)
    expect(result.chips).toEqual([])
    expect(result.total).toBeNull()
  })

  it('returns empty chips and null total for null', () => {
    const result = parseContextSummary(null)
    expect(result.chips).toEqual([])
    expect(result.total).toBeNull()
  })

  it('returns empty chips and null total for whitespace-only string', () => {
    const result = parseContextSummary('   ')
    expect(result.chips).toEqual([])
    expect(result.total).toBeNull()
  })

  it('parses standard format with single chip', () => {
    const result = parseContextSummary('已关联上下文：文档A（共 1）')
    expect(result.chips).toEqual(['文档A'])
    expect(result.total).toBe(1)
  })

  it('parses standard format with multiple chips', () => {
    const result = parseContextSummary('已关联上下文：文档A + 文档B + 文档C（共 3）')
    expect(result.chips).toEqual(['文档A', '文档B', '文档C'])
    expect(result.total).toBe(3)
  })

  it('parses standard format with spaces around +', () => {
    const result = parseContextSummary('已关联上下文：A + B（共 2）')
    expect(result.chips).toEqual(['A', 'B'])
    expect(result.total).toBe(2)
  })

  it('handles chips with extra spaces', () => {
    const result = parseContextSummary('已关联上下文：  A  +  B  （共 2）')
    expect(result.chips).toEqual(['A', 'B'])
  })

  it('filters empty chips from split', () => {
    const result = parseContextSummary('已关联上下文：A + + B（共 2）')
    expect(result.chips).toEqual(['A', 'B'])
  })

  it('parses large total number', () => {
    const result = parseContextSummary('已关联上下文：文档（共 999999）')
    expect(result.total).toBe(999999)
  })

  it('parses zero total', () => {
    const result = parseContextSummary('已关联上下文：文档（共 0）')
    expect(result.total).toBe(0)
  })

  it('falls back to stripped prefix when format does not match', () => {
    const result = parseContextSummary('已关联上下文：just a plain text')
    expect(result.chips).toEqual(['just a plain text'])
    expect(result.total).toBeNull()
  })

  it('falls back to raw string when no prefix', () => {
    const result = parseContextSummary('some random text')
    expect(result.chips).toEqual(['some random text'])
    expect(result.total).toBeNull()
  })

  it('falls back to raw when prefix but empty content', () => {
    const result = parseContextSummary('已关联上下文：')
    // stripped is empty, so chips = [raw]
    expect(result.chips).toEqual(['已关联上下文：'])
    expect(result.total).toBeNull()
  })

  it('handles standard format without space before count', () => {
    const result = parseContextSummary('已关联上下文：A（共3）')
    // The regex requires \s* before the number, so this should match
    expect(result.chips).toEqual(['A'])
    expect(result.total).toBe(3)
  })

  it('handles standard format with extra spaces before count', () => {
    const result = parseContextSummary('已关联上下文：A（共  3）')
    expect(result.chips).toEqual(['A'])
    expect(result.total).toBe(3)
  })

  it('falls back when extra spaces after count (regex does not match)', () => {
    // The regex （共\s*(\d+)） requires ） immediately after digits;
    // spaces after the number cause a fallback to the stripped string
    const result = parseContextSummary('已关联上下文：A（共  3  ）')
    expect(result.total).toBeNull()
    expect(result.chips).toEqual(['A（共  3  ）'])
  })

  it('handles Chinese full-width parentheses', () => {
    const result = parseContextSummary('已关联上下文：A（共 1）')
    expect(result.chips).toEqual(['A'])
    expect(result.total).toBe(1)
  })

  it('handles single chip with no count', () => {
    const result = parseContextSummary('已关联上下文：仅一项')
    expect(result.chips).toEqual(['仅一项'])
    expect(result.total).toBeNull()
  })

  it('trims input before processing', () => {
    const result = parseContextSummary('  已关联上下文：A（共 1）  ')
    expect(result.chips).toEqual(['A'])
    expect(result.total).toBe(1)
  })

  it('handles string with only prefix and whitespace', () => {
    const result = parseContextSummary('已关联上下文：   ')
    // stripped is empty after trim, so chips = [raw]
    expect(result.chips).toEqual(['已关联上下文：'])
    expect(result.total).toBeNull()
  })
})
