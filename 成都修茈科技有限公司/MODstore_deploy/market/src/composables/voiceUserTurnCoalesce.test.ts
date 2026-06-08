import { describe, expect, it } from 'vitest'
import {
  appendCoalescedVoiceUserTurn,
  foldDisplayVoiceMessages,
  shouldCoalesceVoiceUserTurn,
  trimTrailingEmptyVoiceAssistants,
} from './voiceUserTurnCoalesce'

describe('voiceUserTurnCoalesce', () => {
  it('merges short continuation fragments', () => {
    expect(shouldCoalesceVoiceUserTurn('个流市对', '现在这个流式对话有很多问题')).toBe(true)
    const out = appendCoalescedVoiceUserTurn(
      [{ role: 'user', content: '个流市对' }],
      '现在这个流式对话有很多问题',
    )
    expect(out).toHaveLength(1)
    expect(out[0].content).toContain('流')
  })

  it('does not merge after assistant replied', () => {
    const msgs = [
      { role: 'user' as const, content: '你好' },
      { role: 'assistant' as const, content: '你好，有什么可以帮你？' },
    ]
    const out = appendCoalescedVoiceUserTurn(msgs, '再问一句')
    expect(out).toHaveLength(3)
    expect(out[2]).toEqual({ role: 'user', content: '再问一句' })
  })

  it('strips trailing empty assistant before coalesce', () => {
    const out = appendCoalescedVoiceUserTurn(
      [
        { role: 'user', content: '半句' },
        { role: 'assistant', content: '' },
      ],
      '后半句',
    )
    expect(out).toHaveLength(1)
    expect(out[0].content.length).toBeGreaterThan(2)
  })

  it('foldDisplayVoiceMessages merges consecutive user rows', () => {
    const out = foldDisplayVoiceMessages([
      { role: 'user', content: '个流市对' },
      { role: 'user', content: '现在这个流式对话' },
      { role: 'assistant', content: '好的' },
    ])
    expect(out.filter((m) => m.role === 'user')).toHaveLength(1)
  })

  it('trimTrailingEmptyVoiceAssistants', () => {
    expect(
      trimTrailingEmptyVoiceAssistants([
        { role: 'user', content: 'a' },
        { role: 'assistant', content: '' },
      ]),
    ).toEqual([{ role: 'user', content: 'a' }])
  })
})
