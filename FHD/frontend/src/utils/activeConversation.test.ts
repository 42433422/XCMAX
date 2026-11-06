import { describe, expect, it } from 'vitest'
import { chooseActiveConversationId } from './activeConversation'

describe('chooseActiveConversationId', () => {
  it('reopens the conversation the server last finished', () => {
    expect(chooseActiveConversationId('welcome', 'conv-kept')).toBe('conv-kept')
  })

  it('keeps the local session when the server has no finished conversation', () => {
    expect(chooseActiveConversationId('setup', '')).toBe('setup')
    expect(chooseActiveConversationId('setup', '  ')).toBe('setup')
  })
})
