import { describe, expect, it } from 'vitest'
import type { UiChatMessage } from '@/types/chat-ui'
import { chatMessageKey } from './chatMessageIdentity'

const legacy = (): UiChatMessage => ({ role: 'ai', content: 'same', time: '12:34', turnId: 'shared-turn' })

describe('chat message rendering identity', () => {
  it('distinguishes equal-length legacy messages in the same minute and turn', () => {
    expect(chatMessageKey(legacy())).not.toBe(chatMessageKey(legacy()))
  })

  it('survives streaming content changes and later persistence assignment', () => {
    const message = legacy()
    const key = chatMessageKey(message)
    message.content += ' streamed tokens'
    message.persistence = { id: 'server:42', status: 'saved' }
    expect(chatMessageKey(message)).toBe(key)
  })

  it('retains a local identity across server reconciliation and cache round trips', () => {
    const message = { ...legacy(), persistence: { id: 'local-42', status: 'local' as const } }
    const key = chatMessageKey(message)
    const reconciled = { ...message, persistence: { id: 'server:42', status: 'saved' as const }, uiKey: key }
    expect(chatMessageKey(JSON.parse(JSON.stringify(reconciled)))).toBe(key)
  })

  it('keeps keys for replacement server objects with a durable message identity', () => {
    const message = { ...legacy(), persistence: { id: 'server:42', status: 'saved' as const } }
    expect(chatMessageKey({ ...message })).toBe(chatMessageKey(message))
  })
})
