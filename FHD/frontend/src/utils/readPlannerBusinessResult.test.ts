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

  it('hides casual completed aliases whose only artifact signal is an empty collection', () => {
    expect(
      readPlannerBusinessResult({
        success: true,
        response: '你好，需要我做什么？',
        business_result: { status: 'completed', summary: '你好，需要我做什么？', facts: {}, artifacts: [] },
      }),
    ).toBeUndefined()
    expect(
      readPlannerBusinessResult({
        success: true,
        business_result: {
          status: 'completed',
          summary: '你好，需要我做什么？',
          facts: {},
          artifacts: {},
          evidence: { artifact_ids: [] },
        },
      }),
    ).toBeUndefined()
  })

  it('keeps results with real artifact lists or evidence.artifact_ids', () => {
    const artifacts = [
      {
        artifact_id: 'xlsx-1',
        artifact_type: 'file',
        name: '销售报表.xlsx',
        uri: '/api/agent/runs/run-1/artifacts/xlsx-1',
      },
    ]
    expect(
      readPlannerBusinessResult({
        success: true,
        businessResult: { status: 'completed', summary: '已导出', facts: {}, artifacts },
      }),
    ).toEqual({ status: 'completed', summary: '已导出', facts: {}, artifacts })
    expect(
      readPlannerBusinessResult({
        success: true,
        businessResult: { status: 'completed', summary: '已导出', facts: {}, evidence: { artifact_ids: ['xlsx-1'] } },
      }),
    ).toEqual({ status: 'completed', summary: '已导出', facts: {}, evidence: { artifact_ids: ['xlsx-1'] } })
    expect(
      isVisibleChatBusinessResult({
        status: 'completed',
        summary: '已删除',
        facts: {},
        artifacts: [],
        evidence: { completed_tool_count: 1 },
      }),
    ).toBe(true)
  })
})
