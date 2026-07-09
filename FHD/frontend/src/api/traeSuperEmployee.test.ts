import { describe, it, expect, beforeEach, vi } from 'vitest'

const apiFetchMock = vi.fn()
vi.mock('@/utils/apiBase', () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
}))

import {
  fetchTraeSuperEmployeeMessages,
  sendTraeSuperEmployeeMessage,
} from './traeSuperEmployee'

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: new Headers({ 'content-type': 'application/json' }),
    json: async () => body,
  } as Response
}

describe('traeSuperEmployee API', () => {
  beforeEach(() => {
    apiFetchMock.mockReset()
  })

  it('fetches messages from admin scope by default', async () => {
    apiFetchMock.mockResolvedValue(jsonResponse({ messages: [{ id: 'm1' }] }))
    const result = await fetchTraeSuperEmployeeMessages()
    expect(apiFetchMock).toHaveBeenCalledWith(
      '/api/admin/trae-super-employee/messages',
      expect.objectContaining({ headers: { 'Content-Type': 'application/json' } }),
    )
    expect(result).toEqual([{ id: 'm1' }])
  })

  it('fetches messages from mobile scope', async () => {
    apiFetchMock.mockResolvedValue(jsonResponse({ messages: [] }))
    await fetchTraeSuperEmployeeMessages({ scope: 'mobile' })
    expect(apiFetchMock).toHaveBeenCalledWith(
      '/api/mobile/v1/admin/trae-super-employee/messages',
      expect.any(Object),
    )
  })

  it('sends message with context', async () => {
    apiFetchMock.mockResolvedValue(
      jsonResponse({
        messages: [{ id: 'a1', role: 'assistant', body: 'ok', created_at: '2026-07-09T00:00:00Z' }],
      }),
    )
    const result = await sendTraeSuperEmployeeMessage('ping', { source: 'admin_im' })
    expect(apiFetchMock).toHaveBeenCalledWith(
      '/api/admin/trae-super-employee/messages',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          message: 'ping',
          workspace_id: 'xcmax',
          context: { source: 'admin_im', workspace_id: 'xcmax' },
        }),
      }),
    )
    expect(result.messages).toHaveLength(1)
  })

  it('unwraps nested data.messages and throws on success false', async () => {
    apiFetchMock.mockResolvedValue(
      jsonResponse({ data: { messages: [{ id: 'nested' }] } }),
    )
    await expect(fetchTraeSuperEmployeeMessages()).resolves.toEqual([{ id: 'nested' }])

    apiFetchMock.mockResolvedValue(jsonResponse({ success: false, message: '加载失败' }))
    await expect(fetchTraeSuperEmployeeMessages()).rejects.toThrow('加载失败')

    apiFetchMock.mockResolvedValue(
      jsonResponse({ data: { success: false, message: 'nested fail' } }),
    )
    await expect(fetchTraeSuperEmployeeMessages()).rejects.toThrow('nested fail')
  })

  it('throws on non-JSON and maps 401 to 未登录', async () => {
    apiFetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'text/plain' }),
      json: async () => ({}),
    } as Response)
    await expect(fetchTraeSuperEmployeeMessages()).rejects.toThrow('请求失败（HTTP 200）')

    apiFetchMock.mockResolvedValue({
      ok: false,
      status: 401,
      headers: new Headers({ 'content-type': 'text/plain' }),
      json: async () => ({}),
    } as Response)
    await expect(fetchTraeSuperEmployeeMessages()).rejects.toThrow('未登录')
  })

  it('send ignores string message field and uses mobile scope', async () => {
    apiFetchMock.mockResolvedValue(
      jsonResponse({
        message: 'plain',
        assistant_message: { id: 'a2' },
        dispatch: { request_id: 'r1' },
      }),
    )
    const result = await sendTraeSuperEmployeeMessage('hi', undefined, { scope: 'mobile' })
    expect(apiFetchMock).toHaveBeenCalledWith(
      '/api/mobile/v1/admin/trae-super-employee/messages',
      expect.any(Object),
    )
    expect(result.message).toBeUndefined()
    expect(result.assistant_message).toEqual({ id: 'a2' })
    expect(result.dispatch).toEqual({ request_id: 'r1' })
    expect(result.messages).toEqual([])
  })
})
