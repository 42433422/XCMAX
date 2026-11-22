import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiBaseMocks = vi.hoisted(() => ({
  apiFetch: vi.fn(),
}))

vi.mock('@/utils/apiBase', () => ({
  apiFetch: apiBaseMocks.apiFetch,
}))

import { kellaiBindingApi } from './kellaiBinding'

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('kellaiBindingApi', () => {
  beforeEach(() => {
    apiBaseMocks.apiFetch.mockReset()
  })

  it('loads binding status through the local pairing API', async () => {
    apiBaseMocks.apiFetch.mockResolvedValueOnce(
      jsonResponse({
        success: true,
        data: { state: 'connected', connection: { authorized_scopes: ['messages.read'] } },
      }),
    )

    await expect(kellaiBindingApi.status()).resolves.toMatchObject({ state: 'connected' })
    expect(apiBaseMocks.apiFetch).toHaveBeenCalledWith(
      '/api/kellai/binding/status',
      expect.objectContaining({
        headers: expect.objectContaining({
          'X-Kellai-Local-Pairing': '1',
          'X-XCMAX-Client-Shell': 'enterprise',
        }),
      }),
    )
  })

  it('normalizes customer and conversation limits', async () => {
    apiBaseMocks.apiFetch
      .mockResolvedValueOnce(
        jsonResponse({
          success: true,
          data: { contacts: [{ customer_id: 7, display_name: '测试客户' }] },
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          success: true,
          data: { messages: [{ id: 'm1', customer_id: 7, direction: 'inbound', content: '你好' }] },
        }),
      )

    await expect(kellaiBindingApi.contacts(999)).resolves.toHaveLength(1)
    await expect(kellaiBindingApi.messages(7, 'account-a', 999)).resolves.toHaveLength(1)

    expect(apiBaseMocks.apiFetch).toHaveBeenNthCalledWith(1, '/api/kellai/binding/contacts?limit=100', expect.any(Object))
    expect(apiBaseMocks.apiFetch).toHaveBeenNthCalledWith(2, '/api/kellai/binding/contacts/7/messages?connection_id=account-a&limit=100', expect.any(Object))
  })

  it('keeps the default grant read-only and passes explicit scopes and original send ids', async () => {
    apiBaseMocks.apiFetch.mockImplementation(async () => jsonResponse({ success: true, data: {} }))
    await kellaiBindingApi.start()
    expect(apiBaseMocks.apiFetch).toHaveBeenLastCalledWith('/api/kellai/binding/start', expect.objectContaining({ body: '{}' }))
    const scopes = ['channels.read', 'messages.read', 'messages.send']
    await kellaiBindingApi.start(scopes)
    expect(apiBaseMocks.apiFetch).toHaveBeenLastCalledWith('/api/kellai/binding/start', expect.objectContaining({ body: JSON.stringify({ requested_scopes: scopes }) }))
    const input = { client_request_id: 'request-original-123', customer_id: 7, connection_id: 'account-a', channel_type: 'chatwoot', contact_id: '9', content: '确认后的回复' }
    apiBaseMocks.apiFetch.mockImplementation(async () => jsonResponse({ success: true, data: { request_id: input.client_request_id, status: 'accepted' } }))
    await kellaiBindingApi.sendMessage(input)
    expect(apiBaseMocks.apiFetch).toHaveBeenLastCalledWith('/api/kellai/binding/messages/send', expect.objectContaining({ method: 'POST', body: JSON.stringify(input) }))
    await kellaiBindingApi.sendReceipt(input.client_request_id)
    expect(apiBaseMocks.apiFetch).toHaveBeenLastCalledWith('/api/kellai/binding/messages/requests/request-original-123', expect.any(Object))
  })

  it.each(['failed', 'unknown', 'requires_desktop_execution'])('preserves a real %s send receipt with success=false', async (status) => {
    const input = { client_request_id: 'request-outcome-123', customer_id: 7, connection_id: 'account-a', channel_type: 'chatwoot', contact_id: '9', content: '确认后的回复' }
    const receipt = { request_id: input.client_request_id, status, persisted: false }
    apiBaseMocks.apiFetch.mockResolvedValueOnce(jsonResponse({ success: false, data: receipt }))
    await expect(kellaiBindingApi.sendMessage(input)).resolves.toEqual(receipt)
    expect(apiBaseMocks.apiFetch).toHaveBeenCalledTimes(1)
  })

  it.each([
    [{ request_id: 'wrong-request-123', status: 'accepted' }, 200],
    [{ request_id: 'request-outcome-123', status: 'invented-success' }, 200],
    [{ request_id: 'request-outcome-123', status: 'accepted' }, 403],
  ])('rejects mismatched, malformed or unauthorized receipts', async (receipt, httpStatus) => {
    apiBaseMocks.apiFetch.mockResolvedValueOnce(jsonResponse({ success: true, data: receipt }, httpStatus as number))
    await expect(kellaiBindingApi.sendReceipt('request-outcome-123')).rejects.toThrow()
    expect(apiBaseMocks.apiFetch).toHaveBeenCalledTimes(1)
  })

  it('does not accept an unsuccessful ordinary read as a receipt', async () => {
    apiBaseMocks.apiFetch.mockResolvedValueOnce(jsonResponse({ success: false, data: { request_id: 'request-outcome-123', status: 'failed' } }))
    await expect(kellaiBindingApi.contacts()).rejects.toThrow()
  })

  it('rejects invalid customer ids before making a request', async () => {
    await expect(kellaiBindingApi.messages(0, 'account-a')).rejects.toThrow('请选择有效的账号连接和联系人')
    expect(apiBaseMocks.apiFetch).not.toHaveBeenCalled()
  })

  it('accepts the success-only disconnect response', async () => {
    apiBaseMocks.apiFetch.mockResolvedValueOnce(jsonResponse({ success: true }))
    await expect(kellaiBindingApi.disconnect()).resolves.toBeUndefined()
    expect(apiBaseMocks.apiFetch).toHaveBeenCalledWith('/api/kellai/binding/disconnect', expect.objectContaining({ method: 'POST' }))
  })

  it('surfaces backend errors without treating HTML or empty payloads as success', async () => {
    apiBaseMocks.apiFetch.mockResolvedValueOnce(
      jsonResponse(
        {
          success: false,
          detail: '客来来尚未连接',
        },
        409,
      ),
    )

    await expect(kellaiBindingApi.contacts()).rejects.toThrow('客来来尚未连接')
  })
  it('preserves explicit grant error codes for revocation handling', async () => {
    apiBaseMocks.apiFetch.mockResolvedValueOnce(jsonResponse({ detail: { code: 'xcmax_grant_revoked', message: '授权已撤销' } }, 401))
    await expect(kellaiBindingApi.contacts()).rejects.toMatchObject({ code: 'xcmax_grant_revoked', message: '授权已撤销' })
  })

  it.each([
    [403, { message: '此操作未授权', request_not_dispatched: true }, true],
    [422, [{ loc: ['body', 'content'], type: 'string_too_long', msg: 'too long' }], true],
    [422, [{ loc: ['unknown'], type: 'untrusted' }], false],
    [422, [null], false],
    [409, '请求号冲突', false],
    [404, '请求不存在', false],
    [503, '暂不可达', false],
    [401, '未认证', false],
  ])('classifies only an explicit current-send rejection for HTTP %s', async (status, detail, rejected) => {
    const input = { client_request_id: 'request-original-123', customer_id: 7, connection_id: 'account-a', channel_type: 'chatwoot', contact_id: '9', content: '确认后的回复' }
    apiBaseMocks.apiFetch.mockResolvedValueOnce(jsonResponse({ detail }, status as number))
    await expect(kellaiBindingApi.sendMessage(input)).rejects.toMatchObject({ requestNotDispatched: rejected })
    apiBaseMocks.apiFetch.mockResolvedValueOnce(jsonResponse({ detail }, status as number))
    await expect(kellaiBindingApi.sendReceipt(input.client_request_id)).rejects.toMatchObject({ requestNotDispatched: false })
    expect(apiBaseMocks.apiFetch).toHaveBeenCalledTimes(2)
  })

})
