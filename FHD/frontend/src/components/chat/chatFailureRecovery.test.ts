import { describe, expect, it } from 'vitest'
import { chatFailureRecoveryText, readChatExecution } from './chatFailureRecovery'

describe('chat failure recovery', () => {
  it('separates not-executed, unknown and partial outcomes without claiming a kept write', () => {
    expect(chatFailureRecoveryText(undefined)).toContain('结果未知')
    expect(chatFailureRecoveryText({ effect: 'unknown', committed: false })).toContain('本轮未提交写入')
    expect(chatFailureRecoveryText({ effect: 'preview', committed: false })).toContain('本轮未提交写入')
    expect(chatFailureRecoveryText({ effect: 'partial', committed: true })).toContain('部分步骤已写入')
    expect(chatFailureRecoveryText({ outcome: 'not_executed', committed: false })).toContain('本轮未提交写入')
    expect(chatFailureRecoveryText({ committed: false })).not.toContain('不会撤销')
    expect(chatFailureRecoveryText({ committed: true })).toContain('不会再次执行')
    expect(chatFailureRecoveryText({ committed: true })).toContain('也不会撤销')
  })

  it('reads the server execution record', () => {
    const record = readChatExecution({
      execution: {
        idempotency_key: 'turn-1',
        intent: 'bulk_destructive',
        committed: false,
        effect: 'preview',
        tenant_id: 'demo',
        customer_count: 2,
        product_count: 5,
      },
    })
    expect(record).toMatchObject({ idempotencyKey: 'turn-1', committed: false, effect: 'preview', tenantId: 'demo', customerCount: 2, productCount: 5 })
  })

  it('treats a turn that never started executing as having no business write', () => {
    const record = readChatExecution({
      success: false,
      execution_state: 'failed',
      data: { action: 'workflow_planning_failed', execution_started: false },
    })
    expect(record).toMatchObject({ committed: false, effect: 'none', outcome: 'not_executed' })
    expect(chatFailureRecoveryText(record)).toContain('本轮未提交写入')
  })

  it('keeps an unknown outcome when the server never marked execution as started', () => {
    expect(readChatExecution({ success: false, data: { action: 'workflow_planning_failed' } })).toBeUndefined()
    expect(chatFailureRecoveryText(undefined)).toContain('结果未知')
  })
})
