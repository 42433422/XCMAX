import { describe, it, expect, beforeEach, vi } from 'vitest'

const apiFetchMock = vi.fn()
vi.mock('@/utils/apiBase', () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
}))

import {
  fetchClaudeSuperEmployeeMessages,
  sendClaudeSuperEmployeeMessage,
} from './claudeSuperEmployee'

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: new Headers({ 'content-type': 'application/json' }),
    json: async () => body,
  } as Response
}

describe('claudeSuperEmployee API', () => {
  beforeEach(() => {
    apiFetchMock.mockReset()
  })

  describe('fetchClaudeSuperEmployeeMessages', () => {
    it('fetches messages from admin scope by default', async () => {
      apiFetchMock.mockResolvedValue(
        jsonResponse({ messages: [{ id: 'm1' }] }),
      )
      const result = await fetchClaudeSuperEmployeeMessages()
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/admin/claude-super-employee/messages',
        expect.objectContaining({ headers: { 'Content-Type': 'application/json' } }),
      )
      expect(result).toEqual([{ id: 'm1' }])
    })

    it('fetches messages from mobile scope', async () => {
      apiFetchMock.mockResolvedValue(jsonResponse({ messages: [] }))
      await fetchClaudeSuperEmployeeMessages({ scope: 'mobile' })
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/mobile/v1/admin/claude-super-employee/messages',
        expect.any(Object),
      )
    })

    it('unwraps data.messages when nested', async () => {
      apiFetchMock.mockResolvedValue(
        jsonResponse({ data: { messages: [{ id: 'nested' }] } }),
      )
      const result = await fetchClaudeSuperEmployeeMessages()
      expect(result).toEqual([{ id: 'nested' }])
    })

    it('returns empty array when no messages field', async () => {
      apiFetchMock.mockResolvedValue(jsonResponse({}))
      const result = await fetchClaudeSuperEmployeeMessages()
      expect(result).toEqual([])
    })

    it('throws on non-JSON response', async () => {
      apiFetchMock.mockResolvedValue({
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'text/plain' }),
        json: async () => ({}),
      } as Response)
      await expect(fetchClaudeSuperEmployeeMessages()).rejects.toThrow(
        '请求失败（HTTP 200）',
      )
    })

    it('throws 未登录 on 401 non-JSON', async () => {
      apiFetchMock.mockResolvedValue({
        ok: false,
        status: 401,
        headers: new Headers({ 'content-type': 'text/plain' }),
        json: async () => ({}),
      } as Response)
      await expect(fetchClaudeSuperEmployeeMessages()).rejects.toThrow('未登录')
    })

    it('throws on success false', async () => {
      apiFetchMock.mockResolvedValue(
        jsonResponse({ success: false, message: '加载失败' }),
      )
      await expect(fetchClaudeSuperEmployeeMessages()).rejects.toThrow('加载失败')
    })

    it('throws default message on success false without message', async () => {
      apiFetchMock.mockResolvedValue(jsonResponse({ success: false }))
      await expect(fetchClaudeSuperEmployeeMessages()).rejects.toThrow(
        '加载 Claude 对话失败',
      )
    })

    it('throws on nested data success false', async () => {
      apiFetchMock.mockResolvedValue(
        jsonResponse({
          data: { success: false, message: 'nested fail' },
        }),
      )
      await expect(fetchClaudeSuperEmployeeMessages()).rejects.toThrow('nested fail')
    })

    it('throws default message on nested data success false without message', async () => {
      apiFetchMock.mockResolvedValue(
        jsonResponse({ data: { success: false } }),
      )
      await expect(fetchClaudeSuperEmployeeMessages()).rejects.toThrow(
        '加载 Claude 对话失败',
      )
    })
  })

  describe('sendClaudeSuperEmployeeMessage', () => {
    it('posts message and returns response', async () => {
      apiFetchMock.mockResolvedValue(
        jsonResponse({
          dispatch: { request_id: 'r1', status: 'queued' },
          message: { id: 'm1', body: 'hello' },
          messages: [{ id: 'm1' }],
        }),
      )
      const result = await sendClaudeSuperEmployeeMessage('hello')
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/admin/claude-super-employee/messages',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ message: 'hello', context: {} }),
        }),
      )
      expect(result.dispatch).toEqual({ request_id: 'r1', status: 'queued' })
      expect(result.message).toEqual({ id: 'm1', body: 'hello' })
      expect(result.messages).toEqual([{ id: 'm1' }])
    })

    it('passes context in body', async () => {
      apiFetchMock.mockResolvedValue(jsonResponse({ messages: [] }))
      const ctx = { user_id: 5, session: 'abc' }
      await sendClaudeSuperEmployeeMessage('hi', ctx)
      expect(apiFetchMock).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({
          body: JSON.stringify({ message: 'hi', context: ctx }),
        }),
      )
    })

    it('uses mobile scope', async () => {
      apiFetchMock.mockResolvedValue(jsonResponse({ messages: [] }))
      await sendClaudeSuperEmployeeMessage('hi', undefined, { scope: 'mobile' })
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/mobile/v1/admin/claude-super-employee/messages',
        expect.any(Object),
      )
    })

    it('returns empty messages when no messages field', async () => {
      apiFetchMock.mockResolvedValue(jsonResponse({}))
      const result = await sendClaudeSuperEmployeeMessage('hi')
      expect(result.messages).toEqual([])
      expect(result.dispatch).toBeUndefined()
      expect(result.message).toBeUndefined()
    })

    it('handles string message field (not object)', async () => {
      apiFetchMock.mockResolvedValue(
        jsonResponse({ message: 'string message' }),
      )
      const result = await sendClaudeSuperEmployeeMessage('hi')
      // message is string, not object → should be undefined
      expect(result.message).toBeUndefined()
    })

    it('unwraps nested data', async () => {
      apiFetchMock.mockResolvedValue(
        jsonResponse({
          data: {
            dispatch: { request_id: 'nested' },
            message: { id: 'nested-msg' },
            messages: [{ id: 'm' }],
          },
        }),
      )
      const result = await sendClaudeSuperEmployeeMessage('hi')
      expect(result.dispatch).toEqual({ request_id: 'nested' })
      expect(result.message).toEqual({ id: 'nested-msg' })
      expect(result.messages).toEqual([{ id: 'm' }])
    })

    it('throws on success false', async () => {
      apiFetchMock.mockResolvedValue(
        jsonResponse({ success: false, message: '调用失败' }),
      )
      await expect(sendClaudeSuperEmployeeMessage('hi')).rejects.toThrow('调用失败')
    })

    it('throws default message on success false', async () => {
      apiFetchMock.mockResolvedValue(jsonResponse({ success: false }))
      await expect(sendClaudeSuperEmployeeMessage('hi')).rejects.toThrow(
        'Claude 调用失败',
      )
    })

    it('throws on nested data success false', async () => {
      apiFetchMock.mockResolvedValue(
        jsonResponse({
          data: { success: false, message: 'nested error' },
        }),
      )
      await expect(sendClaudeSuperEmployeeMessage('hi')).rejects.toThrow('nested error')
    })

    it('throws default message on nested data success false without message', async () => {
      apiFetchMock.mockResolvedValue(
        jsonResponse({ data: { success: false } }),
      )
      await expect(sendClaudeSuperEmployeeMessage('hi')).rejects.toThrow(
        'Claude 调用失败',
      )
    })

    it('returns assistant_message when present', async () => {
      apiFetchMock.mockResolvedValue(
        jsonResponse({
          assistant_message: { id: 'a1', body: 'response' },
          messages: [],
        }),
      )
      const result = await sendClaudeSuperEmployeeMessage('hi')
      expect(result.assistant_message).toEqual({ id: 'a1', body: 'response' })
    })
  })
})
