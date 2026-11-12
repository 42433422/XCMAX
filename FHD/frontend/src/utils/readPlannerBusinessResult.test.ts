import { describe, expect, it } from 'vitest'
import { isVisibleChatBusinessResult, readPlannerBusinessResult } from './readPlannerBusinessResult'

describe('readPlannerBusinessResult', () => {
  it('hides completed summary-only casual results left on the payload alias', () => {
    expect(
      readPlannerBusinessResult({
        success: true,
        response: '你好，需要我做什么？',
        business_result: { status: 'completed', summary: '你好，需要我做什么？', facts: {} },
      }),
    ).toBeUndefined()
  })

  it('keeps completed tool summaries, facts, and failed terminal results', () => {
    expect(
      readPlannerBusinessResult({
        success: true,
        businessResult: { status: 'completed', summary: '已删除', facts: {}, evidence: { completed_tool_count: 1 } },
      }),
    ).toEqual({ status: 'completed', summary: '已删除', facts: {}, evidence: { completed_tool_count: 1 } })
    expect(
      readPlannerBusinessResult({
        success: true,
        data: { business_result: { status: 'completed', summary: '客户创建成功', facts: { customer_id: 23 } } },
      }),
    ).toEqual({ status: 'completed', summary: '客户创建成功', facts: { customer_id: 23 } })
    expect(
      readPlannerBusinessResult({
        success: false,
        businessResult: { status: 'failed', summary: '写入失败', facts: {} },
      }),
    ).toEqual({ status: 'failed', summary: '写入失败', facts: {} })
  })

  it('keeps summary-only completions when the envelope recorded a tool call', () => {
    expect(
      isVisibleChatBusinessResult(
        { status: 'completed', summary: '已删除', facts: {} },
        { success: true, toolCall: { tool_id: 'customers', action: 'delete' } },
      ),
    ).toBe(true)
  })
})
