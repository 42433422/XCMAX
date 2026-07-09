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
        body: JSON.stringify({ message: 'ping', context: { source: 'admin_im' } }),
      }),
    )
    expect(result.messages).toHaveLength(1)
  })
})
