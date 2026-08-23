import { describe, expect, it } from 'vitest'
import { buildApprovalCardTrace } from './chatOrchestrationTrace'

describe('buildApprovalCardTrace', () => {
  it('infers a business database tool from a legacy workflow approval', () => {
    const trace = buildApprovalCardTrace({
      plan_id: 'plan_1',
      intent: 'business_db_write',
      status: 'pending',
      blocking_nodes: ['write_business_customer'],
      todo: ['识别客户字段', '写入数据库', '回读验证'],
    })

    expect(trace).toEqual(
      expect.objectContaining({
        run_id: 'plan_1',
        intent: 'business_db_write',
        status: 'waiting',
      }),
    )
    expect(trace?.phases).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          kind: 'tool',
          node_id: 'write_business_customer',
          tool_id: 'business_db',
          action: 'write',
          waiting_approval: true,
        }),
      ]),
    )
  })

  it('prefers explicit approval node tool metadata', () => {
    const trace = buildApprovalCardTrace({
      status: 'pending',
      approval_nodes: [{ node_id: 'search_docs', tool_id: 'web_search', action: 'search' }],
    })

    expect(trace?.phases[1]).toEqual(expect.objectContaining({ tool_id: 'web_search', action: 'search' }))
  })

  it('does not create a pending trace for a settled card', () => {
    expect(buildApprovalCardTrace({ status: 'confirmed' })).toBeNull()
  })
})
