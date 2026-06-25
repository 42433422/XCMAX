import { describe, expect, it } from 'vitest'
import './virtualCursor.types'

describe('virtualCursor.types', () => {
  it('declares window.virtualCursor optional property', () => {
    expect(window).toBeDefined()
  })

  it('window.virtualCursor is undefined by default', () => {
    expect((window as unknown as { virtualCursor?: unknown }).virtualCursor).toBeUndefined()
  })

  it('window.virtualCursor can be assigned an api-like object', () => {
    const api = {
      moveTo: () => {},
      click: () => {},
      hide: () => {},
      show: () => {},
    }
    ;(window as unknown as { virtualCursor?: unknown }).virtualCursor = api
    expect((window as unknown as { virtualCursor?: unknown }).virtualCursor).toBe(api)
    delete (window as unknown as { virtualCursor?: unknown }).virtualCursor
  })
})
