import { describe, expect, it, vi } from 'vitest'
import { createScreenCommandQueue } from './aiopenCommandQueue'

describe('screen command ordering', () => {
  it('serializes mutations and deduplicates pending and completed request IDs', async () => {
    const enqueue = createScreenCommandQueue()
    let release!: () => void
    const gate = new Promise<void>((resolve) => { release = resolve })
    const events: string[] = []
    const first = vi.fn(async () => { events.push('first'); await gate; return { success: true } })
    const second = vi.fn(async () => { events.push('second'); return { success: true } })
    const p1 = enqueue('1', first)
    const retry = enqueue('1', first)
    const p2 = enqueue('2', second)
    await Promise.resolve()
    expect(events).toEqual(['first'])
    expect(retry).toBe(p1)
    release()
    await Promise.all([p1, retry, p2])
    await enqueue('1', first)
    expect(first).toHaveBeenCalledTimes(1)
    expect(events).toEqual(['first', 'second'])
  })

  it('returns errors without blocking the next command', async () => {
    const enqueue = createScreenCommandQueue()
    expect(await enqueue('bad', async () => { throw new Error('failed') })).toEqual({ success: false, message: 'failed' })
    expect(await enqueue('next', async () => ({ success: true }))).toEqual({ success: true })
    const run = vi.fn()
    expect(await enqueue('', run)).toEqual({ success: false, code: 'COMMAND_ID_REQUIRED' })
    expect(run).not.toHaveBeenCalled()
  })
})
