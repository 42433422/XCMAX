import { afterEach, describe, expect, it, vi } from 'vitest'
import { waitForCriticalFonts } from './useStartupSplash'

const originalFonts = Object.getOwnPropertyDescriptor(document, 'fonts')
function installFonts(value: unknown) {
  Object.defineProperty(document, 'fonts', { configurable: true, value })
}
afterEach(() => {
  if (originalFonts) Object.defineProperty(document, 'fonts', originalFonts)
  else Reflect.deleteProperty(document, 'fonts')
})

describe('critical startup font readiness', () => {
  it('waits for the local icon font rather than all document fonts', async () => {
    let finish!: (faces: unknown[]) => void
    const load = vi.fn(() => new Promise<unknown[]>((resolve) => { finish = resolve }))
    installFonts({ load, ready: new Promise(() => {}) })
    let done = false
    const pending = waitForCriticalFonts().then(() => { done = true })
    await Promise.resolve()
    expect(done).toBe(false)
    expect(load).toHaveBeenCalledWith(expect.stringContaining('FontAwesome'), expect.any(String))
    finish([{ status: 'loaded' }])
    await pending
    expect(done).toBe(true)
  })

  it('propagates a critical font load failure to the recoverable startup error', async () => {
    installFonts({ load: vi.fn().mockRejectedValue(new Error('font unavailable')) })
    await expect(waitForCriticalFonts()).rejects.toThrow('font unavailable')
  })

  it('does not treat a missing font face as loaded', async () => {
    installFonts({ load: vi.fn().mockResolvedValue([]) })
    await expect(waitForCriticalFonts()).rejects.toThrow()
  })
})
