import { describe, expect, it } from 'vitest'
import type { ChatMessage } from '@/composables/useChatMessages'
import {
  hasAiMessageSidecar,
  isAiTypingOnly,
  shouldRenderChatMessageRow,
} from './chatMessageRender'

function aiMsg(partial: Partial<ChatMessage> = {}): ChatMessage {
  return { role: 'ai', content: '', time: '12:00', ...partial }
}

describe('chatMessageRender', () => {
  it('detects tool sidecar content', () => {
    expect(hasAiMessageSidecar(aiMsg({ toolProgressLabel: '读取 Excel…' }))).toBe(true)
    expect(hasAiMessageSidecar(aiMsg({ content: '你好' }))).toBe(false)
  })

  it('typing-only while streaming without body', () => {
    const messages = [aiMsg()]
    expect(isAiTypingOnly(messages[0], 0, messages, true)).toBe(true)
    expect(shouldRenderChatMessageRow(messages[0], 0, messages, true)).toBe(true)
  })

  it('hides empty placeholder shells after stream ends', () => {
    const messages = [aiMsg({ content: '...' })]
    expect(shouldRenderChatMessageRow(messages[0], 0, messages, false)).toBe(false)
  })

  it('renders user messages always', () => {
    const messages: ChatMessage[] = [{ role: 'user', content: 'hi', time: '12:00' }]
    expect(shouldRenderChatMessageRow(messages[0], 0, messages, false)).toBe(true)
  })
})
