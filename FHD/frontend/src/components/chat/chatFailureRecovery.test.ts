import { describe, expect, it } from 'vitest'
import { chatFailureRecoveryText, readChatExecution } from './chatFailureRecovery'

describe('chat failure recovery', () => {
  it('does not claim a write was kept unless the execution record committed', () => {
    expect(chatFailureRecoveryText(undefined)).toContain('状态未确认')
    expect(chatFailureRecoveryText({ effect: 'unknown', committed: false })).toContain('不要重复提交')
    expect(chatFailureRecoveryText({ effect: 'preview', committed: false })).toContain('尚未提交写入')
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
})
