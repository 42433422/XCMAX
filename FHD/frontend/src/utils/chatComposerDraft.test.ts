import { beforeEach, describe, expect, it } from 'vitest'
import { readChatComposerDraft, writeChatComposerDraft } from './chatComposerDraft'

describe('chat composer recovery', () => {
  beforeEach(() => localStorage.clear())

  it('restores only the same scoped session draft', () => {
    writeChatComposerDraft('scope:a:conversation-1', '核对出库结果', 100)
    expect(readChatComposerDraft('scope:a:conversation-1', 101)).toBe('核对出库结果')
    expect(readChatComposerDraft('scope:b:conversation-1', 101)).toBe('')
    expect(readChatComposerDraft('scope:a:conversation-2', 101)).toBe('')
  })

  it('expires drafts, discards malformed entries, and never persists blank draft', () => {
    writeChatComposerDraft('a', 'old', 0)
    expect(readChatComposerDraft('a', 7 * 24 * 60 * 60 * 1000)).toBe('')
    expect(localStorage.getItem('a')).toBeNull()
    localStorage.setItem('a', '{invalid')
    expect(readChatComposerDraft('a')).toBe('')
    writeChatComposerDraft('a', 'temporary')
    writeChatComposerDraft('a', ' ')
    expect(localStorage.getItem('a')).toBeNull()
  })

  it('bounds draft size and stores no file or authorization objects', () => {
    writeChatComposerDraft('a', 'A'.repeat(16020), 123)
    expect(readChatComposerDraft('a', 124)).toHaveLength(16000)
    const record = JSON.parse(localStorage.getItem('a') || '{}')
    expect(Object.keys(record).sort()).toEqual(['expiresAt', 'text'])
  })
})
