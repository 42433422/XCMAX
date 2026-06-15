import { describe, expect, it, beforeEach } from 'vitest'
import {
  armPostLoginReveal,
  consumePostLoginReveal,
  POST_LOGIN_REVEAL_KEY,
} from './postLoginReveal'

describe('postLoginReveal', () => {
  beforeEach(() => {
    sessionStorage.clear()
  })

  it('arms and consumes once', () => {
    expect(consumePostLoginReveal()).toBe(false)
    armPostLoginReveal()
    expect(sessionStorage.getItem(POST_LOGIN_REVEAL_KEY)).toBe('1')
    expect(consumePostLoginReveal()).toBe(true)
    expect(consumePostLoginReveal()).toBe(false)
  })
})
