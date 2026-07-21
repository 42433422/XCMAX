import { describe, expect, it } from 'vitest'
import { isDesktopShell } from './desktopShell'

describe('desktopShell', () => {
  it('false without xcagiDesktop (Cursor/Electron UA alone is not desktop shell)', () => {
    const prev = (window as Window & { xcagiDesktop?: unknown }).xcagiDesktop
    delete (window as Window & { xcagiDesktop?: unknown }).xcagiDesktop
    expect(isDesktopShell()).toBe(false)
    if (prev !== undefined) (window as Window & { xcagiDesktop?: unknown }).xcagiDesktop = prev
  })

  it('true when xcagiDesktop injected', () => {
    const prev = (window as Window & { xcagiDesktop?: unknown }).xcagiDesktop
    ;(window as Window & { xcagiDesktop?: unknown }).xcagiDesktop = {}
    expect(isDesktopShell()).toBe(true)
    if (prev === undefined) delete (window as Window & { xcagiDesktop?: unknown }).xcagiDesktop
    else (window as Window & { xcagiDesktop?: unknown }).xcagiDesktop = prev
  })
})
