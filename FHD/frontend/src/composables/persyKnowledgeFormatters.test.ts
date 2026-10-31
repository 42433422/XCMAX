import { describe, expect, it } from 'vitest'
import { normalizeAnswer, stripLegacyRetrievalPrefix } from '@/composables/persyKnowledgeFormatters'

describe('persyKnowledgeFormatters.normalizeAnswer', () => {
  it('passes through Chinese knowledge-base copy unchanged', () => {
    const answer = '根据知识库资料，关于「订单号」：客户鑫顺，订单 26-0100012A [1]'
    expect(normalizeAnswer(answer, 3)).toBe(answer)
  })

  it('rewrites legacy English retrieval prefix without dropping the excerpt', () => {
    const legacy =
      "Based on the retrieved dataset evidence for '订单号是什么？': 客户：鑫顺家私；订单号：26-0100012A [1]"
    expect(normalizeAnswer(legacy, 2)).toBe(
      '根据知识库资料：客户：鑫顺家私；订单号：26-0100012A [1]',
    )
  })

  it('falls back to evidence count when answer empty but chunks exist', () => {
    expect(normalizeAnswer('', 4)).toBe('已召回 4 条相关知识证据。')
    expect(normalizeAnswer(null, 0)).toBe('')
  })

  it('stripLegacyRetrievalPrefix removes only the English lead-in', () => {
    expect(
      stripLegacyRetrievalPrefix(
        "Based on the retrieved dataset evidence for 'q': body text [1]",
      ),
    ).toBe('body text [1]')
  })
})
