import { describe, expect, it } from 'vitest'
import {
  createStreamSplitter,
  extractCompleteSentences,
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
})
