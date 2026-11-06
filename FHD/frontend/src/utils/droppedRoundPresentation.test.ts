import { describe, expect, it } from 'vitest'
import { droppedRoundFromHistory, droppedRoundPresentation } from './droppedRoundPresentation'

describe('droppedRoundPresentation', () => {
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
