import { beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope, ref } from 'vue'
import { useEnterpriseCsBridge } from '@/composables/messenger/useEnterpriseCsBridge'
import { useCsInboxBridge } from '@/composables/messenger/useCsInboxBridge'
import type { ImConversationSummary, ImMessage } from '@/api/im'

const imMocks = vi.hoisted(() => ({
  fetchCsInbox: vi.fn(),
  fetchCsInboxMessages: vi.fn(),
  fetchEnterpriseCsThread: vi.fn(),
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

  it.each([[0, 200, 200], [120, 1000, 120]])('refreshes admin messages while preserving reading position %s', async (top, height, expected) => {
    const enabled = ref(true)
    const conversations = ref<ImConversationSummary[]>([{ ...csConversation, cs_mode: 'ai', cs_status: 'ai_active' }, regularConversation])
    const activeConversationId = ref<number | null>(21)
    const messages = ref<ImMessage[]>([oldMessage])
    const playIncoming = vi.fn()
    const el = { scrollTop: top, scrollHeight: height, clientHeight: 200 } as HTMLElement
    const bridge = useCsInboxBridge({
      enabled,
      conversations,
      activeConversationId,
      messages,
      playIncoming,
      scrollEl: ref(el),
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
    expect(el.scrollTop).toBe(expected)

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
      scrollEl: ref(null),
    })

    bridge.startCsInboxPolling()
    await vi.advanceTimersByTimeAsync(5000)
    expect(imMocks.fetchCsInbox).not.toHaveBeenCalled()
    expect(imMocks.fetchCsInboxMessages).not.toHaveBeenCalled()
    vi.useRealTimers()
  })
})


describe('customer CS reading position', () => {
  it.each([
    ['unchanged history', 120, 1000, false, 120],
    ['new message while reading history', 120, 1400, true, 120],
    ['new message at the end', 800, 1400, true, 1400],
  ] as const)('preserves %s', async (_case, top, height, incoming, expected) => {
    const scope = effectScope()
    const el = { scrollTop: top, scrollHeight: 1000, clientHeight: 200 } as HTMLElement
    const messages = ref([oldMessage])
    const notify = vi.fn()
    imMocks.fetchEnterpriseCsThread.mockImplementationOnce(async () => ({
      conversation: { ...csConversation }, messages: incoming ? [oldMessage, newMessage] : [oldMessage],
    }))
    const bridge = scope.run(() => useEnterpriseCsBridge({
      enabled: true,
      conversations: ref([{ ...csConversation, is_cs_inbox: false, is_enterprise_dedicated_cs: true }]),
      activeConversationId: ref<number | null>(21), messages, playIncoming: notify, scrollEl: ref(el),
    }))!
    const refresh = bridge.refreshEnterpriseCsThread()
    await Promise.resolve()
    el.scrollHeight = height
    await refresh
    expect(el.scrollTop).toBe(expected)
    expect(notify).toHaveBeenCalledTimes(incoming ? 1 : 0)
    scope.stop()
  })
})
