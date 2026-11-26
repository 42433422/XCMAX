import { afterEach, describe, expect, it, vi } from 'vitest'
import { applyThemeToDocument } from './personalSettings'

afterEach(() => {
  applyThemeToDocument('light')
  vi.unstubAllGlobals()
  delete document.documentElement.dataset.workbenchTheme
})

describe('workbench theme contract', () => {
  it('follows system theme only in auto mode and removes the listener on override', () => {
    const listeners = new Set<() => void>()
    const query = {
      matches: true,
      addEventListener: (_type: string, listener: () => void) => listeners.add(listener),
      removeEventListener: (_type: string, listener: () => void) => listeners.delete(listener),
    }
    vi.stubGlobal('matchMedia', () => query)
    applyThemeToDocument('auto')
    expect(document.documentElement.dataset.workbenchTheme).toBe('light')
    expect(listeners.size).toBe(1)
    query.matches = false
    listeners.forEach((listener) => listener())
    expect(document.documentElement.dataset.workbenchTheme).toBe('dark')
    applyThemeToDocument('light')
    expect(listeners.size).toBe(0)
    expect(document.documentElement.dataset.workbenchTheme).toBe('light')
  })
})
