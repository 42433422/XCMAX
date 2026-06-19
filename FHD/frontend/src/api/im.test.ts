import { describe, it, expect, vi, beforeEach } from 'vitest'

const apiFetch = vi.hoisted(() => vi.fn())
const getApiBase = vi.hoisted(() => vi.fn(() => ''))
vi.mock('@/utils/apiBase', () => ({ apiFetch, getApiBase }))

import {
  fetchImContacts,
  fetchImConversations,
  fetchImUnreadTotal,
  createDirectConversation,
  fetchImMessages,
  sendImMessage,
  markImRead,
  imWebSocketUrl,
} from './im'

function jsonRes(body: unknown, { ok = true, status = 200, ct = 'application/json' } = {}) {
  return {
    ok,
    status,
    headers: { get: () => ct },
    json: async () => body,
  } as unknown as Response
}

beforeEach(() => {
  apiFetch.mockReset()
  getApiBase.mockReset()
  getApiBase.mockReturnValue('')
})

describe('im api success paths', () => {
  it('fetchImContacts returns contacts with keyword', async () => {
    apiFetch.mockResolvedValueOnce(jsonRes({ success: true, contacts: [{ id: 1 }] }))
    const r = await fetchImContacts('  tom  ')
    expect(r).toHaveLength(1)
    expect(apiFetch).toHaveBeenCalledWith(expect.stringContaining('q=tom'), expect.anything())
  })

  it('fetchImConversations returns list', async () => {
    apiFetch.mockResolvedValueOnce(jsonRes({ success: true, conversations: [{ id: 1 }] }))
    expect(await fetchImConversations()).toHaveLength(1)
  })

  it('fetchImUnreadTotal returns number', async () => {
    apiFetch.mockResolvedValueOnce(jsonRes({ success: true, unread_total: 5 }))
    expect(await fetchImUnreadTotal()).toBe(5)
  })

  it('createDirectConversation returns conversation', async () => {
    apiFetch.mockResolvedValueOnce(jsonRes({ success: true, conversation: { id: 2, title: null, created: true } }))
    expect((await createDirectConversation(9)).id).toBe(2)
  })

  it('fetchImMessages builds query and returns', async () => {
    apiFetch.mockResolvedValueOnce(jsonRes({ success: true, messages: [{ id: 1 }] }))
    const r = await fetchImMessages(3, { limit: 10, beforeId: 100 })
    expect(r).toHaveLength(1)
    expect(apiFetch).toHaveBeenCalledWith(expect.stringContaining('limit=10'), expect.anything())
  })

  it('sendImMessage returns message', async () => {
    apiFetch.mockResolvedValueOnce(jsonRes({ success: true, message: { id: 7 } }))
    expect((await sendImMessage(3, 'hi')).id).toBe(7)
  })

  it('markImRead posts without throwing', async () => {
    apiFetch.mockResolvedValueOnce(jsonRes({ success: true }))
    await expect(markImRead(3, 99)).resolves.toBeUndefined()
  })
})

describe('im api error paths', () => {
  it('readJson throws on non-json', async () => {
    apiFetch.mockResolvedValueOnce(jsonRes('<html>', { ct: 'text/html', status: 401 }))
    await expect(fetchImContacts()).rejects.toThrow('未登录')
  })

  it('fetchImContacts throws when success false', async () => {
    apiFetch.mockResolvedValueOnce(jsonRes({ success: false }))
    await expect(fetchImContacts()).rejects.toThrow('加载联系人失败')
  })

  it('fetchImUnreadTotal returns 0 on non-ok', async () => {
    apiFetch.mockResolvedValueOnce(jsonRes({}, { ok: false, status: 500 }))
    expect(await fetchImUnreadTotal()).toBe(0)
  })

  it('fetchImUnreadTotal returns 0 on thrown error', async () => {
    apiFetch.mockRejectedValueOnce(new Error('net'))
    expect(await fetchImUnreadTotal()).toBe(0)
  })

  it('createDirectConversation throws with server message', async () => {
    apiFetch.mockResolvedValueOnce(jsonRes({ success: false, message: '没权限' }))
    await expect(createDirectConversation(1)).rejects.toThrow('没权限')
  })

  it('sendImMessage throws when missing message', async () => {
    apiFetch.mockResolvedValueOnce(jsonRes({ success: true }))
    await expect(sendImMessage(1, 'x')).rejects.toThrow('发送失败')
  })
})

describe('imWebSocketUrl', () => {
  it('derives ws url from location', () => {
    expect(imWebSocketUrl()).toMatch(/\/ws\/im$/)
  })

  it('uses configured absolute API base', () => {
    getApiBase.mockReturnValue('https://xiu-ci.com/fhd-api')
    expect(imWebSocketUrl()).toBe('wss://xiu-ci.com/fhd-api/ws/im')
  })

  it('keeps relative API prefixes on current origin', () => {
    getApiBase.mockReturnValue('/fhd-api')
    expect(imWebSocketUrl()).toMatch(/^ws:\/\/.*\/fhd-api\/ws\/im$/)
  })
})
