import { describe, it, expect, beforeEach, vi } from 'vitest'

const apiFetchMock = vi.fn()
vi.mock('@/utils/apiBase', () => ({
  apiFetch: (...args: unknown[]) => apiFetchMock(...args),
}))

import {
  fetchAiGroups,
  createAiGroup,
  fetchAiGroupMessages,
  postAiGroupMessage,
  addAiGroupMember,
  removeAiGroupMember,
} from './aiGroups'

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: new Headers({ 'content-type': 'application/json' }),
    json: async () => body,
  } as Response
}

describe('aiGroups API', () => {
  beforeEach(() => {
    apiFetchMock.mockReset()
  })

  describe('fetchAiGroups', () => {
    it('fetches groups from admin scope by default', async () => {
      apiFetchMock.mockResolvedValue(jsonResponse({ groups: [{ id: 'g1' }] }))
      const result = await fetchAiGroups()
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/admin/ai-groups',
        expect.objectContaining({ headers: { 'Content-Type': 'application/json' } }),
      )
      expect(result).toEqual([{ id: 'g1' }])
    })

    it('fetches groups from mobile scope when specified', async () => {
      apiFetchMock.mockResolvedValue(jsonResponse({ groups: [] }))
      await fetchAiGroups('mobile')
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/mobile/v1/ai-groups',
        expect.any(Object),
      )
    })

    it('unwraps data.groups when nested', async () => {
      apiFetchMock.mockResolvedValue(
        jsonResponse({ data: { groups: [{ id: 'nested' }] } }),
      )
      const result = await fetchAiGroups()
      expect(result).toEqual([{ id: 'nested' }])
    })

    it('returns empty array when no groups field', async () => {
      apiFetchMock.mockResolvedValue(jsonResponse({}))
      const result = await fetchAiGroups()
      expect(result).toEqual([])
    })

    it('throws on non-JSON response', async () => {
      apiFetchMock.mockResolvedValue({
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'text/plain' }),
        json: async () => ({}),
      } as Response)
      await expect(fetchAiGroups()).rejects.toThrow('请求失败（HTTP 200）')
    })

    it('throws 未登录 on 401 non-JSON', async () => {
      apiFetchMock.mockResolvedValue({
        ok: false,
        status: 401,
        headers: new Headers({ 'content-type': 'text/plain' }),
        json: async () => ({}),
      } as Response)
      await expect(fetchAiGroups()).rejects.toThrow('未登录')
    })

    it('throws when success is false', async () => {
      apiFetchMock.mockResolvedValue(
        jsonResponse({ success: false, message: '加载失败' }),
      )
      await expect(fetchAiGroups()).rejects.toThrow('加载失败')
    })

    it('throws default message when success is false and no message', async () => {
      apiFetchMock.mockResolvedValue(jsonResponse({ success: false }))
      await expect(fetchAiGroups()).rejects.toThrow('加载群聊失败')
    })
  })

  describe('createAiGroup', () => {
    it('creates group via POST', async () => {
      apiFetchMock.mockResolvedValue(jsonResponse({ group: { id: 'new' } }))
      const result = await createAiGroup('test-group')
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/admin/ai-groups',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ name: 'test-group' }),
        }),
      )
      expect(result).toEqual({ id: 'new' })
    })

    it('returns null when no group field', async () => {
      apiFetchMock.mockResolvedValue(jsonResponse({}))
      const result = await createAiGroup('test')
      expect(result).toBeNull()
    })

    it('unwraps data.group when nested', async () => {
      apiFetchMock.mockResolvedValue(
        jsonResponse({ data: { group: { id: 'nested' } } }),
      )
      const result = await createAiGroup('test')
      expect(result).toEqual({ id: 'nested' })
    })

    it('throws on success false', async () => {
      apiFetchMock.mockResolvedValue(
        jsonResponse({ success: false, message: '建群失败原因' }),
      )
      await expect(createAiGroup('test')).rejects.toThrow('建群失败原因')
    })

    it('throws default message on success false without message', async () => {
      apiFetchMock.mockResolvedValue(jsonResponse({ success: false }))
      await expect(createAiGroup('test')).rejects.toThrow('建群失败')
    })

    it('uses mobile scope', async () => {
      apiFetchMock.mockResolvedValue(jsonResponse({ group: { id: 'g' } }))
      await createAiGroup('test', 'mobile')
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/mobile/v1/ai-groups',
        expect.any(Object),
      )
    })
  })

  describe('fetchAiGroupMessages', () => {
    it('fetches messages for a group', async () => {
      apiFetchMock.mockResolvedValue(
        jsonResponse({ messages: [{ id: 'm1' }] }),
      )
      const result = await fetchAiGroupMessages('group-1')
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/admin/ai-groups/group-1/messages',
        expect.any(Object),
      )
      expect(result).toEqual([{ id: 'm1' }])
    })

    it('encodes groupId in URL', async () => {
      apiFetchMock.mockResolvedValue(jsonResponse({ messages: [] }))
      await fetchAiGroupMessages('group with spaces')
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/admin/ai-groups/group%20with%20spaces/messages',
        expect.any(Object),
      )
    })

    it('returns empty array when no messages field', async () => {
      apiFetchMock.mockResolvedValue(jsonResponse({}))
      const result = await fetchAiGroupMessages('g1')
      expect(result).toEqual([])
    })

    it('unwraps data.messages when nested', async () => {
      apiFetchMock.mockResolvedValue(
        jsonResponse({ data: { messages: [{ id: 'nested' }] } }),
      )
      const result = await fetchAiGroupMessages('g1')
      expect(result).toEqual([{ id: 'nested' }])
    })

    it('throws on success false', async () => {
      apiFetchMock.mockResolvedValue(
        jsonResponse({ success: false, message: '加载消息失败' }),
      )
      await expect(fetchAiGroupMessages('g1')).rejects.toThrow('加载消息失败')
    })

    it('throws default message on success false', async () => {
      apiFetchMock.mockResolvedValue(jsonResponse({ success: false }))
      await expect(fetchAiGroupMessages('g1')).rejects.toThrow('加载群消息失败')
    })
  })

  describe('postAiGroupMessage', () => {
    it('posts message and returns group + messages', async () => {
      apiFetchMock.mockResolvedValue(
        jsonResponse({
          group: { id: 'g1' },
          messages: [{ id: 'm1' }],
        }),
      )
      const result = await postAiGroupMessage('g1', 'hello')
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/admin/ai-groups/g1/messages',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ message: 'hello', mentions: [], sender_name: '我' }),
        }),
      )
      expect(result.group).toEqual({ id: 'g1' })
      expect(result.messages).toEqual([{ id: 'm1' }])
    })

    it('passes mentions in body', async () => {
      apiFetchMock.mockResolvedValue(jsonResponse({ messages: [] }))
      await postAiGroupMessage('g1', 'hi', ['user1', 'user2'])
      expect(apiFetchMock).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({
          body: JSON.stringify({
            message: 'hi',
            mentions: ['user1', 'user2'],
            sender_name: '我',
          }),
        }),
      )
    })

    it('returns empty messages when no messages field', async () => {
      apiFetchMock.mockResolvedValue(jsonResponse({}))
      const result = await postAiGroupMessage('g1', 'hi')
      expect(result.messages).toEqual([])
      expect(result.group).toBeUndefined()
    })

    it('unwraps nested data', async () => {
      apiFetchMock.mockResolvedValue(
        jsonResponse({
          data: { group: { id: 'nested' }, messages: [{ id: 'm' }] },
        }),
      )
      const result = await postAiGroupMessage('g1', 'hi')
      expect(result.group).toEqual({ id: 'nested' })
      expect(result.messages).toEqual([{ id: 'm' }])
    })

    it('throws on success false', async () => {
      apiFetchMock.mockResolvedValue(
        jsonResponse({ success: false, message: '发送失败原因' }),
      )
      await expect(postAiGroupMessage('g1', 'hi')).rejects.toThrow('发送失败原因')
    })

    it('throws default message on success false', async () => {
      apiFetchMock.mockResolvedValue(jsonResponse({ success: false }))
      await expect(postAiGroupMessage('g1', 'hi')).rejects.toThrow('发送失败')
    })
  })

  describe('addAiGroupMember', () => {
    it('adds member via POST', async () => {
      apiFetchMock.mockResolvedValue(jsonResponse({ group: { id: 'g1' } }))
      const result = await addAiGroupMember('g1', { employee_id: 'emp-1' })
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/admin/ai-groups/g1/members',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ employee_id: 'emp-1' }),
        }),
      )
      expect(result).toEqual({ id: 'g1' })
    })

    it('returns null when no group field', async () => {
      apiFetchMock.mockResolvedValue(jsonResponse({}))
      const result = await addAiGroupMember('g1', { employee_id: 'emp-1' })
      expect(result).toBeNull()
    })

    it('throws on success false', async () => {
      apiFetchMock.mockResolvedValue(
        jsonResponse({ success: false, message: '添加失败' }),
      )
      await expect(
        addAiGroupMember('g1', { employee_id: 'emp-1' }),
      ).rejects.toThrow('添加失败')
    })

    it('throws default message on success false', async () => {
      apiFetchMock.mockResolvedValue(jsonResponse({ success: false }))
      await expect(
        addAiGroupMember('g1', { employee_id: 'emp-1' }),
      ).rejects.toThrow('添加成员失败')
    })
  })

  describe('removeAiGroupMember', () => {
    it('removes member via DELETE', async () => {
      apiFetchMock.mockResolvedValue(jsonResponse({ group: { id: 'g1' } }))
      const result = await removeAiGroupMember('g1', 'emp-1')
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/admin/ai-groups/g1/members/emp-1',
        expect.objectContaining({ method: 'DELETE' }),
      )
      expect(result).toEqual({ id: 'g1' })
    })

    it('encodes employeeId in URL', async () => {
      apiFetchMock.mockResolvedValue(jsonResponse({ group: {} }))
      await removeAiGroupMember('g1', 'emp with spaces')
      expect(apiFetchMock).toHaveBeenCalledWith(
        '/api/admin/ai-groups/g1/members/emp%20with%20spaces',
        expect.any(Object),
      )
    })

    it('returns null when no group field', async () => {
      apiFetchMock.mockResolvedValue(jsonResponse({}))
      const result = await removeAiGroupMember('g1', 'emp-1')
      expect(result).toBeNull()
    })

    it('throws on success false', async () => {
      apiFetchMock.mockResolvedValue(
        jsonResponse({ success: false, message: '移除失败' }),
      )
      await expect(removeAiGroupMember('g1', 'emp-1')).rejects.toThrow('移除失败')
    })

    it('throws default message on success false', async () => {
      apiFetchMock.mockResolvedValue(jsonResponse({ success: false }))
      await expect(removeAiGroupMember('g1', 'emp-1')).rejects.toThrow('移除成员失败')
    })
  })
})
