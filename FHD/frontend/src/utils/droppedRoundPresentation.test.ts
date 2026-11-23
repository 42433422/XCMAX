import { describe, expect, it } from 'vitest'
import { droppedRoundFromHistory, droppedRoundPresentation } from './droppedRoundPresentation'

describe('droppedRoundPresentation', () => {
  it('accepts an exact durable text turn and rejects an unproven missing run', () => {
    const turn_receipt = { turn_id: 'turn-text', status: 'completed', message: '持久文本回复' }
    expect(droppedRoundFromHistory({ turn_receipt }, 'turn-text').status).toBe('unknown')
    expect(droppedRoundFromHistory({ turn_receipt: { ...turn_receipt, receipt_kind: 'turn', durable: true } }, 'turn-text'))
      .toMatchObject({ status: 'completed', text: '持久文本回复' })
  })
  it('uses the original task receipt before a saved queued acknowledgement', () => {
    const conversation = { success: true, turn_receipt: {
      turn_id: 'turn-1', run_id: 'run-1', status: 'failed', message: '原导入任务未完成。',
    }, messages: [{ role: 'assistant', content: '已排队', metadata: {
      summary: { turn_id: 'turn-1', success: true, status: 'queued' },
    } }] }
    expect(droppedRoundFromHistory(conversation, 'turn-1')).toMatchObject({ status: 'failed' })
    expect(droppedRoundFromHistory(conversation, 'turn-2').status).toBe('unknown')
  })
  it('does not turn a contradictory persisted completion into success', () => {
    expect(droppedRoundFromHistory({ turn_receipt: {
      turn_id: 'turn-1', run_id: 'run-1', status: 'completed', message: '成功', requires_reconciliation: true,
    } }, 'turn-1').status).toBe('unknown')
  })
  it('shows a completed server reply and nothing else as success', () => {
    expect(droppedRoundPresentation({ reachable: true, serverStatus: 'completed', serverText: '已经写入。' })).toMatchObject({
      status: 'completed', text: '已经写入。',
    })
    expect(droppedRoundPresentation({ reachable: true, serverStatus: 'completed', serverText: '' }).status).toBe('unknown')
  })

  it('keeps a dropped connection unknown until the server answers', () => {
    const unknown = droppedRoundPresentation({ reachable: false })
    expect(unknown.status).toBe('unknown')
    expect(unknown.text).toContain('未标记为成功')
  })

  it.each(['running', 'queued', 'waiting_approval', 'interrupted', 'failed'] as const)('keeps %s distinct from completed', (status) => {
    const shown = droppedRoundPresentation({ reachable: true, serverStatus: status, serverText: '半句' })
    expect(shown.status).toBe(status)
    expect(shown.workflowAction).not.toBe('completed')
  })

  it.each(['object', 'json'])('reads the matching turn from persisted %s metadata', encoding => {
    const metadata = { summary: { turn_id: 'turn-1', success: true } }
    const conversation = { success: true, messages: [
      { role: 'assistant', content: 'other turn', metadata: { summary: { turn_id: 'turn-2', success: true } } },
      { role: 'assistant', content: '已写入', metadata: encoding === 'json' ? JSON.stringify(metadata) : metadata },
    ] }
    expect(droppedRoundFromHistory(conversation, 'turn-1')).toMatchObject({ status: 'completed', text: '已写入' })
    expect(droppedRoundFromHistory(conversation, '').status).toBe('unknown')
    expect(droppedRoundFromHistory(conversation, 'missing-turn').status).toBe('unknown')
  })

  it.each([
    [{ summary: { success: false, status: 'completed' } }, 'failed'],
    [{ summary: { success: true, status: 'running' } }, 'running'],
    [{ summary: { success: true, status: 'unknown' } }, 'unknown'],
    [{ summary: { success: false, status: 'unknown' } }, 'unknown'],
    [{ ui: { workflowAction: 'completed' } }, 'unknown'],
    [{}, 'unknown'],
  ])('requires a server outcome rather than text or a client completion label', (metadata, status) => {
    const row = { role: 'assistant', content: '一段回复', metadata: {
      ...metadata, business_harness: { turn_id: 'turn-1' },
    } }
    expect(droppedRoundFromHistory({ data: { messages: [row] } }, 'turn-1').status).toBe(status)
    expect(droppedRoundFromHistory({ messages: [{ ...row, role: 'user' }] }, 'turn-1').status).toBe('unknown')
  })
})
