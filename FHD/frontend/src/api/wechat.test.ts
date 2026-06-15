import { describe, it, expect, vi, beforeEach } from 'vitest'

const { apiMock, ApiError } = vi.hoisted(() => {
  class ApiError extends Error {
    status: number
    data: unknown
    constructor(message: string, status: number, data?: unknown) {
      super(message)
      this.status = status
      this.data = data
    }
  }
  return {
    apiMock: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
    ApiError,
  }
})

vi.mock('./core', () => ({
  api: apiMock,
  default: apiMock,
  ApiError,
  buildFullApiUrl: (u: string) => u,
}))

import wechatApi from './wechat'

beforeEach(() => {
  apiMock.get.mockReset().mockResolvedValue({ success: true })
  apiMock.post.mockReset().mockResolvedValue({ success: true })
  apiMock.put.mockReset().mockResolvedValue({ success: true })
  apiMock.delete.mockReset().mockResolvedValue({ success: true })
})

describe('wechatApi thin wrappers', () => {
  it('delegates GET/POST/PUT/DELETE endpoints', async () => {
    await wechatApi.getTasks({ q: '1' })
    await wechatApi.confirmTask(1)
    await wechatApi.ignoreTask(2)
    await wechatApi.getContacts()
    await wechatApi.addContact({ name: 'a' } as never)
    await wechatApi.getContact(3)
    await wechatApi.updateContact(3, { name: 'b' } as never)
    await wechatApi.deleteContact(3)
    await wechatApi.scanMessages()
    await wechatApi.getContactContext(3)
    await wechatApi.getStarredContacts()
    await wechatApi.searchContacts('foo')
    await wechatApi.addStarredContact({ name: 'c' } as never)
    await wechatApi.updateStarredContact(4, { name: 'd' } as never)
    await wechatApi.deleteStarredContact(4)
    await wechatApi.unstarAllContacts()
    await wechatApi.getStarredContactContext(4)
    await wechatApi.refreshContactMessages(4)
    await wechatApi.refreshMessagesCache()
    await wechatApi.refreshContactCache()
    await wechatApi.openChat('张三')
    await wechatApi.sendMessage('张三', 'hi')
    expect(apiMock.get).toHaveBeenCalled()
    expect(apiMock.post).toHaveBeenCalled()
    expect(apiMock.put).toHaveBeenCalled()
    expect(apiMock.delete).toHaveBeenCalled()
  })

  it('searchContacts coerces empty query', async () => {
    await wechatApi.searchContacts('')
    expect(apiMock.get).toHaveBeenLastCalledWith(expect.stringContaining('/search'), { q: '' })
  })
})

describe('wechatApi.ensureContactCache fallback chain', () => {
  it('returns get result on success', async () => {
    apiMock.get.mockResolvedValueOnce({ success: true, data: { ok: 1 } })
    const r = await wechatApi.ensureContactCache()
    expect(r.success).toBe(true)
  })

  it('treats no-source 404 as skipped success', async () => {
    apiMock.get.mockRejectedValueOnce(new ApiError('未找到可导入的联系人源', 404))
    const r = await wechatApi.ensureContactCache()
    expect(r.data).toEqual({ skipped: true })
  })

  it('falls back to POST when GET 404 without no-source message', async () => {
    apiMock.get.mockRejectedValueOnce(new ApiError('not found', 404))
    apiMock.post.mockResolvedValueOnce({ success: true, data: { via: 'post' } })
    const r = await wechatApi.ensureContactCache()
    expect(r.data).toEqual({ via: 'post' })
  })

  it('POST 405 fallback hits refresh endpoint', async () => {
    apiMock.get.mockRejectedValueOnce(new ApiError('gone', 404))
    apiMock.post
      .mockRejectedValueOnce(new ApiError('method', 405))
      .mockResolvedValueOnce({ success: true, data: { via: 'refresh' } })
    const r = await wechatApi.ensureContactCache()
    expect(r.data).toEqual({ via: 'refresh' })
  })

  it('rethrows non-ApiError from GET', async () => {
    apiMock.get.mockRejectedValueOnce(new Error('boom'))
    await expect(wechatApi.ensureContactCache()).rejects.toThrow('boom')
  })
})
