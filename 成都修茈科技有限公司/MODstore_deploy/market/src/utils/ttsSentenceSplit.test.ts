import { describe, expect, it } from 'vitest'
import {
  createStreamSplitter,
  extractCompleteSentences,
  splitSentences,
  subtractEmittedSegments,
} from './ttsSentenceSplit'

describe('ttsSentenceSplit earlyClause', () => {
  it('emits clause before sentence end when earlyClause enabled', () => {
    const parts = extractCompleteSentences('这是一段比较长的前缀，后面还有内容', {
      minLen: 4,
      earlyClause: true,
      earlyClauseMinLen: 8,
    })
    expect(parts.some((p) => p.includes('前缀'))).toBe(true)
  })

  it('finish emits remainder after firstChunk prefix', () => {
    const splitter = createStreamSplitter({ minLen: 2, firstChunkLen: 8 })
    const first = splitter.feed('这是一段足够长的流式前缀内容')
    expect(first).toEqual(['这是一段足够长的'])
    const rest = splitter.finish('这是一段足够长的流式前缀内容。')
    expect(rest.length).toBeGreaterThan(0)
    expect(rest.join('')).toContain('流式前缀内容')
  })

  it('finish emits remainder after early clause', () => {
    const splitter = createStreamSplitter({ minLen: 4, earlyClause: true, earlyClauseMinLen: 8 })
    splitter.feed('这是一段足够长的问候前缀，后面的内容继续')
    const rest = splitter.finish('这是一段足够长的问候前缀，后面的内容继续。')
    expect(rest.some((p) => p.includes('后面'))).toBe(true)
  })

  it('stream splitter emits early clause once', () => {
    const splitter = createStreamSplitter({ minLen: 4, earlyClause: true, earlyClauseMinLen: 8 })
    const first = splitter.feed('这是一段足够长的问候前缀，后面的内容继续')
    expect(first.length).toBeGreaterThanOrEqual(1)
    const second = splitter.feed('这是一段足够长的问候前缀，后面的内容还在继续增加')
    expect(second.length).toBe(0)
  })
})

describe('subtractEmittedSegments', () => {
  it('strips emitted prefix from longer segment', () => {
    const fresh = subtractEmittedSegments(
      ['这是一段足够长的流式前缀内容。'],
      ['这是一段足够长的'],
    )
    expect(fresh.join('')).toBe('流式前缀内容。')
  })

  it('drops empty, duplicate, and fully emitted segments', () => {
    expect(subtractEmittedSegments(['', '  ', '已经播过', '新内容', '新内容'], ['已经播过'])).toEqual(['新内容'])
    expect(subtractEmittedSegments(['完全相同'], ['完全相同'])).toEqual([])
  })
})

describe('ttsSentenceSplit long and empty cases', () => {
  it('splits long Chinese and English segments near commas or spaces', () => {
    expect(splitSentences('前半段内容很长很长，后半段也很长很长。', { minLen: 2, maxLen: 8 }).length).toBeGreaterThan(1)
    expect(splitSentences('alpha beta gamma delta epsilon.', { minLen: 2, maxLen: 12 })).toContain('alpha beta')
  })

  it('handles empty inputs, no terminator, first chunk reset, and short merge', () => {
    expect(extractCompleteSentences('', { earlyClause: true })).toEqual([])
    expect(extractCompleteSentences('只有一个短句没有结束', { earlyClause: true })).toEqual([])
    expect(splitSentences('', { minLen: 2 })).toEqual([])

    const splitter = createStreamSplitter({ minLen: 2, firstChunkLen: 4 })
    expect(splitter.feed('短')).toEqual([])
    expect(splitter.feed('这是第一段还没完')).toEqual(['这是第一'])
    expect(splitter.feed('这是第一段继续')).toEqual([])
    splitter.reset()
    expect(splitter.feed('重置后再次触发')).toEqual(['重置后再'])

    expect(splitSentences('短。句。足够长的一句。', { minLen: 4 })).toEqual(['短句足够长的一句'])
  })
})
