import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { useCsInboxBridge } from '@/composables/messenger/useCsInboxBridge'
import type { ImConversationSummary, ImMessage } from '@/api/im'

const imMocks = vi.hoisted(() => ({
  fetchCsInbox: vi.fn(),
  fetchCsInboxMessages: vi.fn(),
}))

vi.mock('@/api/im', () => imMocks)

const regularConversation: ImConversationSummary = {
  id: 7,
  title: '普通会话',
  is_direct: true,
  last_message_at: null,
  last_message_preview: '',
  unread_count: 0,
}

const csConversation: ImConversationSummary = {
  id: 21,
  title: '企业客户',
  is_direct: true,
  last_message_at: '2026-09-01T01:00:00Z',
  last_message_preview: '',
  unread_count: 1,
  is_cs_inbox: true,
  customer_user_id: 42,
  cs_mode: 'human',
  cs_status: 'human_pending',
  cs_transfer_reason: '客户主动要求转人工',
}

const oldMessage: ImMessage = {
  id: 100,
  conversation_id: 21,
  sender_user_id: 42,
  body: '旧消息',
  origin: 'customer',
  is_self: false,
  created_at: '2026-09-01T01:00:00Z',
}

const newMessage: ImMessage = {
  id: 101,
  conversation_id: 21,
  sender_user_id: 42,
  body: '请转人工客服',
  origin: 'customer',
  is_self: false,
  created_at: '2026-09-01T01:00:02Z',
}

describe('useCsInboxBridge', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    imMocks.fetchCsInbox.mockReset()
    imMocks.fetchCsInbox.mockResolvedValue([{ ...csConversation }])
    imMocks.fetchCsInboxMessages.mockReset()
    imMocks.fetchCsInboxMessages.mockResolvedValue([oldMessage, newMessage])
  })

  it('polls the selected admin thread and refreshes messages plus automation state', async () => {
    const enabled = ref(true)
    const conversations = ref<ImConversationSummary[]>([{ ...csConversation, cs_mode: 'ai', cs_status: 'ai_active' }, regularConversation])
    const activeConversationId = ref<number | null>(21)
    const messages = ref<ImMessage[]>([oldMessage])
    const playIncoming = vi.fn()
    const scrollToBottom = vi.fn()
    const bridge = useCsInboxBridge({
      enabled,
      conversations,
      activeConversationId,
      messages,
      playIncoming,
      scrollToBottom,
    })

    bridge.startCsInboxPolling()
    await vi.advanceTimersByTimeAsync(2500)

    expect(imMocks.fetchCsInbox).toHaveBeenCalledTimes(1)
    expect(imMocks.fetchCsInboxMessages).toHaveBeenCalledWith(21)
    expect(messages.value).toEqual([oldMessage, newMessage])
    expect(conversations.value.map((item) => item.id)).toEqual([21, 7])
    expect(conversations.value[0]).toMatchObject({
      cs_mode: 'human',
      cs_status: 'human_pending',
      cs_transfer_reason: '客户主动要求转人工',
      unread_count: 0,
      last_message_preview: '请转人工客服',
    })
    expect(playIncoming).toHaveBeenCalledWith('请转人工客服')
    expect(scrollToBottom).toHaveBeenCalledTimes(1)

    bridge.stopCsInboxPolling()
    await vi.advanceTimersByTimeAsync(5000)
    expect(imMocks.fetchCsInbox).toHaveBeenCalledTimes(1)
    vi.useRealTimers()
  })

  it('does not poll regular conversations or a disabled admin bridge', async () => {
    const enabled = ref(false)
    const conversations = ref<ImConversationSummary[]>([regularConversation])
    const activeConversationId = ref<number | null>(7)
    const bridge = useCsInboxBridge({
      enabled,
      conversations,
      activeConversationId,
      messages: ref<ImMessage[]>([]),
      playIncoming: vi.fn(),
      scrollToBottom: vi.fn(),
    })

    bridge.startCsInboxPolling()
    await vi.advanceTimersByTimeAsync(5000)
    expect(imMocks.fetchCsInbox).not.toHaveBeenCalled()
    expect(imMocks.fetchCsInboxMessages).not.toHaveBeenCalled()
    vi.useRealTimers()
  })
})
