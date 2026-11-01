import { beforeEach, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import type { UiChatMessage } from '@/types/chat-ui'
import { localMessagePersistence, samePersistedMessage, useChatMessagePersistence } from './useChatMessagePersistence'
const { save } = vi.hoisted(() => ({ save: vi.fn() }))
vi.mock('@/api/chat', () => ({ default: { saveMessage: save } }))
beforeEach(() => save.mockReset())

function setup() {
  const messages = ref<UiChatMessage[]>([{ role: 'user', content: '订单 A', time: '12:00', persistence: localMessagePersistence() }])
  let identity = 'owner-a'
  const persist = vi.fn()
  const api = useChatMessagePersistence({
    messages, sessionId: ref('session-a'), scope: () => identity, read: () => messages.value, persist,
    plainText: text => text, html: text => text,
  })
  return { messages, persist, api, changeOwner: () => { identity = 'owner-b'; messages.value = [] } }
}

it('retries only the original persistence envelope with a stable ID after a lost acknowledgement', async () => {
  const state = setup()
  const committed = new Map<string, unknown>()
  save.mockImplementationOnce(async payload => { committed.set(payload.client_message_id, payload); throw new Error('ack lost') })
  await state.api.saveMessage('user', '订单 A')
  const id = state.messages.value[0].persistence!.id
  expect(state.messages.value[0].persistence!.status).toBe('failed')
  let release!: () => void
  save.mockImplementationOnce(payload => new Promise(resolve => {
    committed.set(payload.client_message_id, payload)
    release = () => resolve({ success: true, saved: true, durable: true })
  }))
  const first = state.api.retryMessageSave(id)
  const second = state.api.retryMessageSave(id)
  expect(save).toHaveBeenCalledTimes(2)
  expect(save.mock.calls[1][0]).toEqual(save.mock.calls[0][0])
  expect(state.messages.value[0].persistence!.status).toBe('saving')
  release()
  await Promise.all([first, second])
  expect(committed.size).toBe(1)
  expect(state.messages.value[0].persistence!.status).toBe('saved')
  await state.api.retryMessageSave(id)
  expect(save).toHaveBeenCalledTimes(2)
})

it('does not claim durable saving from an empty, negative or temporary acknowledgement', async () => {
  const state = setup()
  save.mockResolvedValueOnce({ success: false }).mockResolvedValueOnce({ success: true, saved: true, durable: false })
  await state.api.saveMessage('user', '订单 A')
  expect(state.messages.value[0].persistence!.status).toBe('failed')
  await state.api.retryMessageSave(state.messages.value[0].persistence!.id)
  expect(state.messages.value[0].persistence).toMatchObject({ status: 'local', error: expect.stringContaining('未确认持久保存') })
})

it('discards an old owner acknowledgement and cannot retry that message under the new owner', async () => {
  const state = setup()
  let resolve!: (value: unknown) => void
  save.mockReturnValueOnce(new Promise(r => { resolve = r }))
  const pending = state.api.saveMessage('user', '订单 A')
  const id = state.messages.value[0].persistence!.id
  state.changeOwner()
  resolve({ success: true, saved: true, durable: true })
  await pending
  await state.api.retryMessageSave(id)
  expect(state.messages.value).toEqual([])
  expect(state.persist).toHaveBeenCalledTimes(1)
  expect(save).toHaveBeenCalledTimes(1)
})

it.each(['success', 'failure'] as const)('does not restore a deleted session when its pending save settles with %s', async outcome => {
  const state = setup()
  let resolve!: (value: unknown) => void
  let reject!: (reason: Error) => void
  save.mockReturnValueOnce(new Promise((yes, no) => { resolve = yes; reject = no }))
  const pending = state.api.saveMessage('user', '订单 A')
  state.messages.value = []
  if (outcome === 'success') resolve({ success: true, saved: true, durable: true })
  else reject(new Error('ack lost'))
  await pending
  expect(state.messages.value).toEqual([])
  expect(state.persist).toHaveBeenCalledTimes(1)
})

it('updates the surviving original session after switching to another session', async () => {
  const original: UiChatMessage[] = [{ role: 'user', content: '订单 A', time: '12:00', persistence: localMessagePersistence() }]
  const messages = ref(original)
  const sessionId = ref('session-a')
  const cache = new Map<string, UiChatMessage[]>([['session-a', messages.value]])
  const persist = vi.fn((list: UiChatMessage[], sid: string) => { cache.set(sid, list) })
  const api = useChatMessagePersistence({
    messages, sessionId, scope: () => 'owner-a', read: sid => cache.get(sid) || [], persist,
    plainText: text => text, html: text => text,
  })
  let resolve!: (value: unknown) => void
  save.mockReturnValueOnce(new Promise(yes => { resolve = yes }))
  const pending = api.saveMessage('user', '订单 A')
  sessionId.value = 'session-b'
  messages.value = []
  resolve({ success: true, saved: true, durable: true })
  await pending
  expect(messages.value).toEqual([])
  expect(cache.get('session-a')?.[0].persistence?.status).toBe('saved')
  expect(persist).toHaveBeenCalledTimes(2)
  expect(persist).toHaveBeenLastCalledWith(cache.get('session-a'), 'session-a')
})


it('reconciles failed stream replies by turn while keeping other turns and client IDs distinct', () => {
  const local: UiChatMessage = { role: 'ai', content: '处理失败：模型未返回可显示的正文，已停止重复请求。请检查模型服务后重试。', time: '12:00', turnId: 'turn-a', persistence: { id: 'local-a', status: 'local' } }
  const server: UiChatMessage = { role: 'ai', content: '模型未返回可显示的正文，已停止重复请求。请检查模型服务后重试。', time: '12:01', turnId: 'turn-a', persistence: { id: 'server:1', status: 'saved' } }
  expect(samePersistedMessage(local, server, text => text)).toBe(true)
  expect(samePersistedMessage(local, { ...server, turnId: 'turn-b', time: '12:00' }, text => text)).toBe(false)
  expect(samePersistedMessage(local, { ...server, persistence: { id: 'other-client', status: 'saved' } }, text => text)).toBe(false)
  expect(samePersistedMessage({ ...local, turnId: undefined }, { ...server, turnId: undefined }, text => text)).toBe(false)
  expect(samePersistedMessage({ ...local, turnId: undefined }, { ...server, turnId: undefined, time: '12:00' }, text => text)).toBe(true)
})


it('does not normalize failure prefixes in user text or discard unacknowledged legacy saves', () => {
  const local: UiChatMessage = { role: 'user', content: '处理失败：原始输入', time: '12:00', persistence: { id: 'local-user', status: 'local' } }
  const server: UiChatMessage = { role: 'user', content: '原始输入', time: '12:00', persistence: { id: 'server:3', status: 'saved' } }
  expect(samePersistedMessage(local, server, text => text)).toBe(false)
  local.content = server.content
  local.persistence!.request = { role: 'user', content: local.content }
  expect(samePersistedMessage(local, server, text => text)).toBe(false)
  expect(samePersistedMessage({ ...local, turnId: 'turn-a' }, { ...server, turnId: 'turn-a' }, text => text)).toBe(true)
})

it('does not merge a legacy failed reply with an unrelated same-minute successful reply', () => {
  const local: UiChatMessage = { role: 'ai', content: '处理失败：订单 A', time: '12:00', persistence: { id: 'local-b', status: 'local' } }
  const server: UiChatMessage = { role: 'ai', content: '订单 A', time: '12:00', persistence: { id: 'server:1', status: 'saved' } }
  expect(samePersistedMessage(local, server, text => text)).toBe(false)
  expect(samePersistedMessage({ ...local, workflowAction: 'failed' }, server, text => text)).toBe(false)
  expect(samePersistedMessage({ ...local, workflowAction: 'failed' }, { ...server, workflowAction: 'failed' }, text => text)).toBe(true)
  expect(samePersistedMessage({ ...local, content: '订单 B' }, server, text => text)).toBe(false)
})
