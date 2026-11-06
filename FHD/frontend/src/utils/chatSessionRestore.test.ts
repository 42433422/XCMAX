import { describe, expect, it } from 'vitest'
import { isDurableChatScope, sessionIdForScope } from './chatSessionRestore'

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
})