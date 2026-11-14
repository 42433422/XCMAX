import { describe, expect, it } from 'vitest'
import { formatBusinessResultSummary } from './businessResultSummary'

describe('formatBusinessResultSummary', () => {
  it('renders summary and labeled facts', () => {
    expect(
      formatBusinessResultSummary({
        status: 'completed',
        summary: '客户创建成功',
        facts: { customer_id: 23, empty: '', skipped: null },
      }),
    ).toBe('客户创建成功；客户 ID：23')
  })

  it('returns empty for missing or casual completed results', () => {
    expect(formatBusinessResultSummary(undefined)).toBe('')
    expect(formatBusinessResultSummary({ status: 'completed', summary: '', facts: {} })).toBe('')
  })
})
