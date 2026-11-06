import { describe, expect, it } from 'vitest'
import { conversationIdAfterRestart, isDurableChatScope, sessionIdForScope } from './chatSessionRestore'

describe('chatSessionRestore', () => {
  it('keeps a provisional id until the tenant scope exists', () => {
    expect(isDurableChatScope('local')).toBe(false)
    expect(isDurableChatScope('tenant:1:owner-pending')).toBe(false)
    expect(sessionIdForScope('local', 'saved', 'temp')).toEqual({ id: 'temp', persist: false })
  })

  it('restores the saved conversation for the signed-in scope', () => {
    expect(isDurableChatScope('tenant:1:owner:7')).toBe(true)
    expect(sessionIdForScope('tenant:1:owner:7', 'conv-a', 'temp')).toEqual({ id: 'conv-a', persist: false })
  })

  it('persists a new id only after the scope is durable and nothing was saved', () => {
    expect(sessionIdForScope('user:demo', '', 'temp')).toEqual({ id: 'temp', persist: true })
    expect(sessionIdForScope('user:other', 'conv-b', 'temp').id).toBe('conv-b')
  })

  it('lets the server conversation replace a stale localStorage id', () => {
    expect(conversationIdAfterRestart('tenant:1:owner:7', 'stale-local', 'current', 'server-last')).toEqual({
      id: 'server-last',
      persistLocal: true,
    })
    expect(conversationIdAfterRestart('tenant:1:owner:7', 'stale-local', 'current', '')).toEqual({
      id: 'stale-local',
      persistLocal: false,
    })
    expect(conversationIdAfterRestart('local', 'stale-local', 'temp', 'server-last')).toEqual({
      id: 'temp',
      persistLocal: false,
    })
  })
})