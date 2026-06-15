import { describe, it, expect, vi, beforeEach } from 'vitest'

const { apiMock, ApiError } = vi.hoisted(() => {
  class ApiError extends Error {
    status: number
    constructor(message: string, status: number) {
      super(message)
      this.status = status
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

import lanGateApi from './lanGate'

beforeEach(() => {
  apiMock.get.mockReset().mockResolvedValue({ success: true })
  apiMock.post.mockReset().mockResolvedValue({ success: true })
  apiMock.put.mockReset().mockResolvedValue({ success: true })
  apiMock.delete.mockReset().mockResolvedValue({ success: true })
})

describe('lanGateApi wrappers', () => {
  it('covers every endpoint', async () => {
    await lanGateApi.hostInfo()
    await lanGateApi.status()
    await lanGateApi.activate('K', 'lbl')
    await lanGateApi.requestAccess({ device_label: 'd' })
    await lanGateApi.myAccessRequest()
    await lanGateApi.logout()
    await lanGateApi.whoami()
    await lanGateApi.listKeys()
    await lanGateApi.listKeys(false)
    await lanGateApi.issueKey({ label: 'k' })
    await lanGateApi.revokeKey(1)
    await lanGateApi.listSessions()
    await lanGateApi.kickSession('jti 1')
    await lanGateApi.audit()
    await lanGateApi.listAccessRequests()
    await lanGateApi.approveAccessRequest(1, 'n')
    await lanGateApi.rejectAccessRequest(1)
    await lanGateApi.listAllowlist()
    await lanGateApi.revokeAllowlist(2)
    await lanGateApi.getSettings()
    expect(apiMock.get).toHaveBeenCalled()
    expect(apiMock.post).toHaveBeenCalled()
    expect(apiMock.delete).toHaveBeenCalled()
  })

  it('encodes jti in kickSession path', async () => {
    await lanGateApi.kickSession('a b')
    expect(apiMock.delete).toHaveBeenCalledWith(expect.stringContaining('a%20b'))
  })
})

describe('lanGateApi.updateSettings', () => {
  it('returns POST result when allowed', async () => {
    apiMock.post.mockResolvedValueOnce({ enabled: true } as never)
    const r = await lanGateApi.updateSettings({ enabled: true })
    expect((r as { enabled: boolean }).enabled).toBe(true)
    expect(apiMock.put).not.toHaveBeenCalled()
  })

  it('falls back to PUT on 405', async () => {
    apiMock.post.mockRejectedValueOnce(new ApiError('method', 405))
    apiMock.put.mockResolvedValueOnce({ enabled: false } as never)
    const r = await lanGateApi.updateSettings({ enabled: false })
    expect((r as { enabled: boolean }).enabled).toBe(false)
    expect(apiMock.put).toHaveBeenCalled()
  })

  it('rethrows non-405 error', async () => {
    apiMock.post.mockRejectedValueOnce(new ApiError('boom', 500))
    await expect(lanGateApi.updateSettings({ enabled: false })).rejects.toThrow('boom')
    expect(apiMock.put).not.toHaveBeenCalled()
  })
})
