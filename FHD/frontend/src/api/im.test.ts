import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
const { apiFetch, getApiBase } = vi.hoisted(() => ({ apiFetch: vi.fn(), getApiBase: vi.fn(() => '') }))
vi.mock('@/utils/apiBase', () => ({ apiFetch, getApiBase }))
import * as im from './im'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'
const jsonRes = (body: unknown, { ok = true, status = 200, ct = 'application/json' } = {}) => ({ ok, status, headers: { get: () => ct }, json: async () => body })
const message = { id: 7, conversation_id: 3, sender_user_id: 9, body: 'hi', created_at: null }
const conversation = { id: 2, title: null, created: true }
beforeEach(() => { apiFetch.mockReset(); getApiBase.mockReset().mockReturnValue('') })
afterEach(() => vi.unstubAllGlobals())

describe('IM request and response contracts', () => {
  it('walks every conversation page, deduplicates moving rows, and accepts a legacy final snapshot', async () => {
    apiFetch.mockResolvedValueOnce(jsonRes({ success: true, conversations: [{ id: 1 }, { id: 2 }], next_cursor: 'next / &?' }))
      .mockResolvedValueOnce(jsonRes({ success: true, conversations: [{ id: 2 }, { id: 3 }] }))
    expect(await im.fetchImConversations()).toEqual([{ id: 1 }, { id: 2 }, { id: 3 }])
    expect(apiFetch.mock.calls.map(([url]) => url)).toEqual(['/api/im/conversations?limit=50', '/api/im/conversations?limit=50&cursor=next+%2F+%26%3F'])
  })
  it('rejects repeated cursors instead of looping or silently truncating history', async () => {
    apiFetch.mockResolvedValue(jsonRes({ success: true, conversations: [{ id: 1 }], next_cursor: 'same' }))
    await expect(im.fetchImConversations()).rejects.toThrow('游标重复')
    expect(apiFetch).toHaveBeenCalledTimes(2)
  })
  it('retires a paged read after an account switch without mixing accounts', async () => {
    apiFetch.mockImplementationOnce(async () => {
      productReadAccountEpoch.value++
      return jsonRes({ success: true, conversations: [{ id: 1 }], next_cursor: 'next' })
    })
    await expect(im.fetchImConversations()).rejects.toThrow('账号已切换')
    expect(apiFetch).toHaveBeenCalledTimes(1)
  })
  it.each([
    [() => im.fetchImContacts('  tom & jerry  '), '/api/im/contacts?q=tom%20%26%20jerry', 'contacts'],
    [() => im.fetchImContacts(), '/api/im/contacts', 'contacts'],
    [() => im.fetchImContacts('  '), '/api/im/contacts', 'contacts'],
    [im.fetchImConversations, '/api/im/conversations?limit=50', 'conversations'],
    [() => im.fetchImMessages(3, { limit: 10, beforeId: 100 }), '/api/im/conversations/3/messages?limit=10&before_id=100', 'messages'],
    [() => im.fetchImMessages(3), '/api/im/conversations/3/messages', 'messages'],
    [() => im.fetchCsInboxMessages(3), '/api/im/cs/inbox/3/messages', 'messages'],
  ] as const)('reads %s and handles absent lists', async (request, url, key) => {
    apiFetch.mockResolvedValueOnce(jsonRes({ success: true, [key]: [{ id: 1 }] })).mockResolvedValueOnce(jsonRes({ success: true }))
    expect(await request()).toEqual([{ id: 1 }])
    expect(apiFetch).toHaveBeenCalledWith(url, { headers: { 'Content-Type': 'application/json' } })
    expect(await request()).toEqual([])
  })
  it.each([
    [() => im.createDirectConversation(9), '/api/im/conversations/direct', { peer_user_id: 9 }, { conversation }, conversation],
    [() => im.sendImMessage(3, 'hi'), '/api/im/conversations/3/messages', { body: 'hi' }, { message }, message],
    [() => im.replyCsInbox(3, 'hi'), '/api/im/cs/inbox/3/reply', { body: 'hi' }, { message }, message],
    [() => im.updateCsInboxMode(3, 'human'), '/api/im/cs/inbox/3/mode', { mode: 'human' }, { state: { cs_mode: 'human' } }, { cs_mode: 'human' }],
    [() => im.markImRead(3, 99), '/api/im/conversations/3/read', { last_message_id: 99 }, {}, undefined],
  ] as const)('posts %s with the exact payload', async (request, url, body, response, expected) => {
    apiFetch.mockResolvedValue(jsonRes({ success: true, ...response }))
    expect(await request()).toEqual(expected)
    expect(apiFetch).toHaveBeenCalledWith(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  })
  it.each([
    [im.fetchImContacts, '加载联系人失败'], [im.fetchImConversations, '加载会话失败'],
    [() => im.fetchImMessages(3), '加载消息失败'], [() => im.createDirectConversation(1), '创建会话失败'],
    [() => im.sendImMessage(1, 'x'), '发送失败'], [im.fetchCsInbox, '加载客服收件箱失败'],
    [() => im.fetchCsInboxMessages(1), '加载客服消息失败'], [() => im.replyCsInbox(1, 'x'), '回复失败'],
    [() => im.updateCsInboxMode(1, 'ai'), '切换接待模式失败'],
  ] as const)('rejects unsuccessful %s', async (request, error) => {
    apiFetch.mockResolvedValue(jsonRes({ success: false }))
    await expect(request()).rejects.toThrow(error)
  })
  it.each([401, 503])('rejects HTML and missing content types at HTTP %s', async (status) => {
    for (const ct of ['text/html', '']) {
      apiFetch.mockResolvedValueOnce(jsonRes('<html>', { ct, status }))
      await expect(im.fetchImContacts()).rejects.toThrow(status === 401 ? '未登录' : `请求失败（HTTP ${status}）`)
    }
  })
  it.each([
    [{ success: true, unread_total: 5 }, {}, 5], [{ success: true }, {}, 0], [{ success: false }, {}, 0],
    [{}, { ok: false, status: 500 }, 0], [{}, { ct: 'text/html' }, 0], [{}, { ct: '' }, 0],
  ] as const)('normalizes unread response %j', async (body, options, expected) => {
    apiFetch.mockResolvedValue(jsonRes(body, options))
    expect(await im.fetchImUnreadTotal()).toBe(expected)
  })
  it('handles unread network errors and rejects missing mutation records with server messages', async () => {
    apiFetch.mockRejectedValueOnce(new Error('net'))
    expect(await im.fetchImUnreadTotal()).toBe(0)
    for (const request of [() => im.createDirectConversation(1), () => im.updateCsInboxMode(1, 'ai')]) {
      apiFetch.mockResolvedValueOnce(jsonRes({ success: true, message: '没权限' }))
      await expect(request()).rejects.toThrow('没权限')
    }
    for (const request of [() => im.sendImMessage(1, 'x'), () => im.replyCsInbox(1, 'x')]) {
      apiFetch.mockResolvedValueOnce(jsonRes({ success: true }))
      await expect(request()).rejects.toThrow(/发送失败|回复失败/)
    }
  })
  it('maps CS inbox state and fallback customer names', async () => {
    const rows = [{ id: 1, customer_user_id: 9, customer_name: '', unread_count: 2, last_message_at: null },
      { id: 2, customer_user_id: 8, customer_name: 'Acme', unread_count: 0, last_message_at: 'today', cs_mode: 'human', cs_status: 'human_active', cs_transfer_reason: 'request', cs_summary: 'summary', cs_last_operator_user_id: 7 }]
    apiFetch.mockResolvedValueOnce(jsonRes({ success: true, conversations: rows })).mockResolvedValueOnce(jsonRes({ success: true }))
    expect(await im.fetchCsInbox()).toEqual(rows.map((r, i) => ({ id: r.id, title: i ? 'Acme' : '用户9', is_direct: true, last_message_at: r.last_message_at, last_message_preview: '', unread_count: r.unread_count, is_cs_inbox: true, customer_user_id: r.customer_user_id, cs_mode: r.cs_mode ?? 'ai', cs_status: r.cs_status ?? 'ai_active', cs_transfer_reason: r.cs_transfer_reason ?? '', cs_summary: r.cs_summary ?? '', cs_last_operator_user_id: r.cs_last_operator_user_id ?? null })))
    expect(await im.fetchCsInbox()).toEqual([])
  })
  it.each([undefined, [message]])('loads enterprise CS messages %j', async (messages) => {
    apiFetch.mockResolvedValue(jsonRes({ success: true, conversation, messages }))
    expect(await im.fetchEnterpriseCsThread()).toEqual({ conversation, messages: messages ?? [] })
    expect(apiFetch).toHaveBeenCalledWith('/api/im/enterprise-cs/messages', { headers: { 'Content-Type': 'application/json' }, timeoutMs: 25_000 })
  })
  it.each([undefined, { cs_mode: 'human' }])('sends enterprise CS and defaults state %j', async (state) => {
    apiFetch.mockResolvedValue(jsonRes({ success: true, conversation_id: 3, message, state }))
    expect(await im.sendEnterpriseCsMessage('hi')).toEqual({ conversation_id: 3, message, state: state ?? {} })
    expect(apiFetch).toHaveBeenCalledWith('/api/im/enterprise-cs/messages', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{"body":"hi"}', timeoutMs: 25_000 })
  })
  it.each([
    [{ success: true, conversation }, false, '加载企业专属客服失败'], [{ success: false, message: 'denied' }, true, 'denied'],
    [{ success: true, detail: 'missing' }, true, 'missing'],
  ] as const)('rejects incomplete enterprise threads %j', async (body, ok, error) => {
    apiFetch.mockResolvedValue(jsonRes(body, { ok }))
    await expect(im.fetchEnterpriseCsThread()).rejects.toThrow(error)
  })
  it.each([
    [{ success: true, conversation_id: 3, message }, false], [{ success: false }, true],
    [{ success: true, conversation_id: 3 }, true], [{ success: true, message }, true],
  ] as const)('rejects incomplete enterprise sends %j', async (body, ok) => {
    apiFetch.mockResolvedValueOnce(jsonRes(body, { ok })).mockResolvedValueOnce(jsonRes({ ...body, detail: 'offline' }, { ok }))
    await expect(im.sendEnterpriseCsMessage('x')).rejects.toThrow('发送失败')
    await expect(im.sendEnterpriseCsMessage('x')).rejects.toThrow('offline')
  })
  it.each(['', '/fhd-api', 'fhd-api', 'https://xiu-ci.com/fhd-api/', 'http://api.example/'])('derives the websocket URL from %s', (base) => {
    getApiBase.mockReturnValue(base)
    expect(im.imWebSocketUrl()).toBe(/^http/.test(base) ? `${base.replace(/^http/, 'ws').replace(/\/$/, '')}/ws/im` : `${window.location.origin.replace(/^http/, 'ws')}${base ? '/fhd-api' : ''}/ws/im`)
  })
  it.each([im.fetchEnterpriseCsThread, () => im.sendEnterpriseCsMessage('report')])('guides CS reauthentication without sending again', async (request) => {
    apiFetch.mockResolvedValue(jsonRes({ message: '市场登录凭证无效' }, { ok: false, status: 401 }))
    await expect(request()).rejects.toThrow('重新登录企业账号')
    expect(apiFetch).toHaveBeenCalledTimes(1)
  })
  it('uses the server-safe websocket fallback without a window', () => {
    vi.stubGlobal('window', undefined)
    expect(im.imWebSocketUrl()).toBe('ws://127.0.0.1:5000/ws/im')
  })
})

describe('uncertain enterprise CS receipts', () => {
  it.each([500, 502, 503])('marks POST %s as requiring reconciliation', async (status) => {
    apiFetch.mockResolvedValue(jsonRes({ success: false, message: 'gateway failure' }, { ok: false, status }))
    await expect(im.sendEnterpriseCsMessage('synthetic report')).rejects.toMatchObject({ reconciliationRequired: true })
  })
  it.each([{}, { id: 0, conversation_id: 3, body: 'x' }, { id: 1, conversation_id: 4, body: 'x' }, { id: 1, conversation_id: 3 }])('rejects incomplete success receipt %j', async (badMessage) => {
    apiFetch.mockResolvedValue(jsonRes({ success: true, conversation_id: 3, message: badMessage }))
    await expect(im.sendEnterpriseCsMessage('synthetic report')).rejects.toMatchObject({ reconciliationRequired: true })
  })
})

it.each([null, [], {}, { success: 'true' }])('retains unknown state for malformed POST payload %j', async (payload) => {
  apiFetch.mockResolvedValue(jsonRes(payload))
  await expect(im.sendEnterpriseCsMessage('synthetic report')).rejects.toMatchObject({ reconciliationRequired: true })
})
