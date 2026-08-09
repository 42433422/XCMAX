import { describe, expect, it } from 'vitest'
import { parseApprovalCardFromPayload } from '@/utils/chatApprovalCard'

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
})
