import { describe, expect, it } from 'vitest'
import { parseApprovalCardFromPayload, reconcileApprovalCards, restoreApprovalCard } from '@/utils/chatApprovalCard'
import type { ChatMessage } from '@/composables/useChatMessages'

describe('parseApprovalCardFromPayload', () => {
  it('parses nested approval_card from payload', () => {
    const card = parseApprovalCardFromPayload({
      success: true,
      data: {
        action: 'workflow_confirmation_required',
        data: {
          approval_card: {
            version: 1,
            kind: 'workflow_confirmation_required',
            blocking_nodes: ['write'],
            approval_required: false,
            approval_request_ids: ['req-1'],
            approval_path: '/approval?request_no=req-1',
            reason: 'test',
          },
        },
      },
    })
    expect(card?.blocking_nodes).toEqual(['write'])
    expect(card?.reason).toBe('test')
    expect(card?.approval_request_ids).toEqual(['req-1'])
    expect(card?.approval_path).toBe('/approval?request_no=req-1')
    expect(card?.status).toBe('pending')
  })

  it('builds fallback card when approval_card missing', () => {
    const card = parseApprovalCardFromPayload({
      success: true,
      data: {
        action: 'workflow_confirmation_required',
        data: {
          plan_id: 'p1',
          blocking_nodes: ['n1'],
          approval_required: true,
        },
      },
    })
    expect(card?.plan_id).toBe('p1')
    expect(card?.confirm_mode).toBe('approval')
  })

  it('retains an envelope run ID and restores a stable card ID without a stuck submitting state', () => {
    const card = parseApprovalCardFromPayload({
      run_id: 'run-envelope',
      data: { action: 'workflow_confirmation_required', data: { approval_card: { plan_id: 'plan-A' } } },
    })!
    expect(card.run_id).toBe('run-envelope')
    expect(card.id).toBeTruthy()
    expect(restoreApprovalCard({ ...card, submitting: true })).toEqual(card)
  })

  it('restores the newest snapshot without status as pending so the confirm button renders', () => {
    const messages = [
      { role: 'ai', time: '12:20', content: 'old plan', approvalCard: { plan_id: 'plan-old', approval_required: true } },
      { role: 'user', time: '12:40', content: '导入' },
      { role: 'ai', time: '12:41', content: 'new plan', approvalCard: { plan_id: 'plan-new', approval_required: true } },
      // 服务端旧消息可能排在本地新消息之后，不能按数组下标取「最新」。
      { role: 'ai', time: '12:25', content: 'stale receipt', approvalCard: { plan_id: 'plan-stale' } },
    ] as unknown as ChatMessage[]
    reconcileApprovalCards(messages)
    expect(messages[0].approvalCard?.status).toBe('confirmed')
    expect(messages[2].approvalCard?.status).toBe('pending')
    expect(messages[3].approvalCard?.status).toBe('confirmed')
  })

  it('treats a restored card with persisted approval receipts as already submitted', () => {
    const messages = [
      {
        role: 'ai',
        content: 'submitted',
        approvalCard: { plan_id: 'plan-A', approval_request_ids: ['81'], approval_path: '/approvals' },
      },
    ] as unknown as ChatMessage[]
    reconcileApprovalCards(messages)
    expect(messages[0].approvalCard.status).toBe('confirmed')
  })
})
