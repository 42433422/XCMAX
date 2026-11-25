import { describe, expect, it } from 'vitest'
import { CHAT_IME_ENTER_GUARD_MS, createChatComposerImeGuard } from './chatComposerIme'

describe('chat IME candidate commit', () => {
  it('lets the IME process its candidate Enter, then blocks a late Enter once', () => {
    let now = 1000
    const guard = createChatComposerImeGuard(() => now)
    guard.compositionStart()
    const candidate = new KeyboardEvent('keydown', { key: 'Enter', cancelable: true })
    expect(guard.shouldSuppressEnter(candidate)).toBe(true)
    expect(candidate.defaultPrevented).toBe(false)
    guard.compositionEnd()
    const late = new KeyboardEvent('keydown', { key: 'Enter', cancelable: true })
    expect(guard.shouldSuppressEnter(late)).toBe(true)
    expect(late.defaultPrevented).toBe(true)
    now += CHAT_IME_ENTER_GUARD_MS + 1
    expect(guard.shouldSuppressEnter(new KeyboardEvent('keydown', { key: 'Enter' }))).toBe(false)
  })

  it('also ignores WebKit keyCode 229 even if isComposing is false', () => {
    const guard = createChatComposerImeGuard()
    const event = new KeyboardEvent('keydown', { key: 'Enter', cancelable: true })
    Object.defineProperty(event, 'keyCode', { value: 229 })
    expect(guard.shouldSuppressEnter(event)).toBe(true)
    expect(event.defaultPrevented).toBe(false)
  })
})
