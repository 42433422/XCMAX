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
    await vi.advanceTimersByTimeAsync(251)
    await rejection
  })
})

describe('auth api module', () => {
  it('exports authApi.login', () => {
    expect(typeof authApi.login).toBe('function')
  })
})
