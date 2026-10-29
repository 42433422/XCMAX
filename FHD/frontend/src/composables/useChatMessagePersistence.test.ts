import { beforeEach, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import type { UiChatMessage } from '@/types/chat-ui'
import { localMessagePersistence, useChatMessagePersistence } from './useChatMessagePersistence'
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
