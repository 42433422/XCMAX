import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { ref } from 'vue'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'
import AiGroupChatView from './AiGroupChatView.vue'
const mocks = vi.hoisted(() => ({ start: vi.fn(), messages: vi.fn(), send: vi.fn(), groups: vi.fn(), active: true }))
vi.mock('@/components/im/MatureChat.vue', async () => ({ default: (await import('@/test-stubs/MatureChatStub.vue')).default }))
vi.mock('@/composables/messenger/useOpenIMGroup', () => ({ useOpenIMGroup: () => ({
  start: mocks.start, history: vi.fn(), active: ref(mocks.active), connected: ref(mocks.active), error: ref(''), hasOlder: ref(false),
}) }))
vi.mock('@/api/aiGroups', () => ({ fetchAiGroupMessages: mocks.messages, fetchAiGroups: mocks.groups,
  postAiGroupMessage: mocks.send, createAiGroup: vi.fn(), addAiGroupMember: vi.fn(), removeAiGroupMember: vi.fn(),
}))
vi.mock('@/utils/apiBase', () => ({ apiFetch: vi.fn().mockResolvedValue({ json: async () => ({ items: [] }) }) }))
let wrapper: ReturnType<typeof mount>
afterEach(() => { wrapper?.unmount(); vi.useRealTimers(); vi.restoreAllMocks() })
it.each([true, false])('merges host receipts without reconnecting (SDK active=%s)', async (active) => {
  mocks.active = active; mocks.messages.mockClear(); mocks.start.mockClear()
  vi.useFakeTimers()
  vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible')
  mocks.start.mockResolvedValue(active)
  mocks.messages.mockResolvedValue([{ id: 'receipt', group_id: 'g', role: 'ai', sender_id: 'employee',
    sender_name: 'synthetic employee', body: 'synthetic Para result', created_at: '2026-01-01T00:00:00Z' }])
  wrapper = mount(AiGroupChatView, { props: { group: {
    id: 'g', name: 'synthetic group', member_count: 0, members: [], department_key: '', last_message_at: '', last_message_preview: '',
  } } })
  await flushPromises()
  await vi.advanceTimersByTimeAsync(10000)
  expect(mocks.messages).toHaveBeenCalledTimes(active ? 2 : 3)
  expect(mocks.start).toHaveBeenCalledTimes(1)
  expect(wrapper.findAll('.chat-message')).toHaveLength(1)
  expect(wrapper.get('.chat-message').text()).toContain('synthetic Para result')
})

it('does not restore old account messages after a pending send completes', async () => {
  mocks.active = true; mocks.start.mockResolvedValue(true)
  let resolve!: (value: unknown) => void
  mocks.send.mockImplementationOnce(() => new Promise(r => { resolve = r }))
  const group = { id: 'g', name: 'old account group', member_count: 0, members: [], department_key: '', last_message_at: '', last_message_preview: '' }
  wrapper = mount(AiGroupChatView, { props: { group } })
  await flushPromises()
  await wrapper.get('.chat-input').setValue('old account draft')
  await wrapper.get('.chat-send').trigger('click')
  productReadAccountEpoch.value++
  resolve({ messages: [{ id: 'old', group_id: 'g', role: 'ai', body: 'old response', created_at: '' }], group })
  await flushPromises()
  expect(wrapper.text()).not.toContain('old response')
  expect(wrapper.text()).not.toContain('old account group')
  expect(wrapper.emitted('group-updated')).toBeUndefined()
})

it.each(['transport', 'initial host read'])('keeps forbidden %s closed until reconnect succeeds', async (failure) => {
  vi.useFakeTimers()
  vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible')
  mocks.active = false; mocks.send.mockReset(); mocks.messages.mockReset(); mocks.start.mockReset()
  mocks.start.mockResolvedValue(false); mocks.messages.mockResolvedValue([])
  if (failure === 'transport') mocks.start.mockRejectedValueOnce({ status: 403 })
  else mocks.messages.mockRejectedValueOnce({ status: 403 })
  const group = { id: 'g', name: 'forbidden group', member_count: 0, members: [], department_key: '', last_message_at: '', last_message_preview: '' }
  wrapper = mount(AiGroupChatView, { props: { group } })
  await flushPromises()
  const initialReads = mocks.messages.mock.calls.length
  await vi.advanceTimersByTimeAsync(15000)
  expect(mocks.messages).toHaveBeenCalledTimes(initialReads)
  expect(wrapper.get('.chat-input').attributes('disabled')).toBeDefined()
  await wrapper.get('.chat-input').setValue('forbidden')
  await wrapper.get('.chat-send').trigger('click')
  expect(mocks.send).not.toHaveBeenCalled()
  await wrapper.get('.aigc-error button').trigger('click')
  await flushPromises()
  expect(wrapper.get('.chat-input').attributes('disabled')).toBeUndefined()
  await vi.advanceTimersByTimeAsync(5000)
  expect(mocks.messages).toHaveBeenCalledTimes(initialReads + 2)
})
it('releases old group sending state without clearing a newer send', async () => {
  mocks.active = true; mocks.start.mockResolvedValue(true); mocks.send.mockReset()
  const group = { id: 'g1', name: 'first group', member_count: 0, members: [], department_key: '', last_message_at: '', last_message_preview: '' }
  mocks.groups.mockResolvedValue([group, { ...group, id: 'g2', name: 'second group' }])
  let first!: (value: unknown) => void, second!: (value: unknown) => void
  mocks.send.mockImplementationOnce(() => new Promise(r => { first = r }))
    .mockImplementationOnce(() => new Promise(r => { second = r }))
  wrapper = mount(AiGroupChatView)
  await flushPromises()
  await wrapper.get('.chat-input').setValue('first draft')
  await wrapper.get('.chat-send').trigger('click')
  await wrapper.findAll('.aigc-group')[1].trigger('click')
  await flushPromises()
  expect(wrapper.get('.chat-input').attributes('disabled')).toBeUndefined()
  await wrapper.get('.chat-input').setValue('second draft')
  await wrapper.get('.chat-send').trigger('click')
  first({ messages: [], group })
  await flushPromises()
  expect(wrapper.get('.chat-title').text()).toBe('second group')
  expect(wrapper.get('.chat-input').attributes('disabled')).toBeDefined()
  second({ messages: [] })
  await flushPromises()
  expect(wrapper.get('.chat-input').attributes('disabled')).toBeUndefined()
  expect(mocks.send).toHaveBeenCalledTimes(2)
})
