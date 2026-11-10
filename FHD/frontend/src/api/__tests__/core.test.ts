import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, api } from '@/api/core'
import type { ApiResponse } from '@/types/api'
import { authApi } from '@/api/auth'

describe('api core types', () => {
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('ApiResponse uses success boolean', () => {
    const sample: ApiResponse<{ id: number }> = { success: true, data: { id: 1 } }
    expect(sample.success).toBe(true)
  })

  it('ApiError carries unknown data payload', () => {
    const err = new ApiError('bad', 400, { detail: 'x' })
    expect(err.status).toBe(400)
    expect(err.data).toEqual({ detail: 'x' })
  })

  it('aborts a stalled request at its explicit timeout', async () => {
    vi.useFakeTimers()
    vi.stubGlobal(
      'fetch',
      vi.fn(
        (_url: string, init?: RequestInit) =>
          new Promise((_resolve, reject) => {
            init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
          }),
      ),
    )

    const pending = api.get('/api/stalled', {}, { timeoutMs: 250 })
    const rejection = expect(pending).rejects.toMatchObject({
      name: 'ApiError',
      message: expect.stringContaining('请求超时'),
    })
    // 读请求超时后会自动重试一次，总时长 = 首次超时 + 退避 + 二次超时。
    await vi.advanceTimersByTimeAsync(900)
    await rejection
  })

  it('waits for a long request when no client timeout is configured', async () => {
    vi.useFakeTimers()
    let finish!: (value: Response) => void
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(resolve => { finish = resolve })))
    let settled = false
    const pending = api.post('/api/templates/reviewed-excel/preview', new FormData())
      .finally(() => { settled = true })
    await vi.advanceTimersByTimeAsync(181_000)
    expect(settled).toBe(false)
    finish({ ok: true, headers: { get: () => 'application/json' }, json: async () => ({ success: true }) } as unknown as Response)
    await expect(pending).resolves.toEqual({ success: true })
  })
})

describe('auth api module', () => {
  it('exports authApi.login', () => {
    expect(typeof authApi.login).toBe('function')
  })
})
