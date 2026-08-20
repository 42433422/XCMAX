import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
}))
const primeCsrfCookie = vi.hoisted(() => vi.fn().mockResolvedValue(undefined))

vi.mock('./core', () => ({
  api: apiMock,
  default: apiMock,
  primeCsrfCookie,
  buildFullApiUrl: (url: string) => url,
}))

import authApi from './auth'

beforeEach(() => {
  apiMock.post.mockReset().mockResolvedValue({ success: true })
  primeCsrfCookie.mockClear()
})

describe('authApi transient login retry', () => {
  it('retries a server error after the bounded delay', async () => {
    vi.useFakeTimers()
    try {
      apiMock.post.mockRejectedValueOnce({ status: 502 }).mockResolvedValueOnce({ success: true })
      const login = authApi.login('u', 'p')
      await vi.advanceTimersByTimeAsync(1_000)
      await expect(login).resolves.toEqual({ success: true })
      expect(apiMock.post).toHaveBeenCalledTimes(2)
    } finally {
      vi.useRealTimers()
    }
  })

  it('does not retry credential errors', async () => {
    const error = { status: 401 }
    apiMock.post.mockRejectedValueOnce(error)
    await expect(authApi.login('u', 'bad')).rejects.toBe(error)
    expect(apiMock.post).toHaveBeenCalledTimes(1)
  })
})
