import { describe, expect, it } from 'vitest'
import { droppedRoundPresentation } from './droppedRoundPresentation'

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
})
