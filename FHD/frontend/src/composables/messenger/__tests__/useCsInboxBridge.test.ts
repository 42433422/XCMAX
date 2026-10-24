import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope, nextTick, ref } from 'vue'
import { useCsInboxBridge } from '@/composables/messenger/useCsInboxBridge'
import { useEnterpriseCsBridge } from '../useEnterpriseCsBridge'
import { useImRealtime } from '@/views/im-messenger/useImRealtime'
import type { ImConversationSummary, ImMessage } from '@/api/im'

const imMocks = vi.hoisted(() => ({
  fetchEnterpriseCsThread: vi.fn(),
  markImRead: vi.fn(async () => ({})),
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

// WO-7dc7831514ca / account 29 / CI867efb701a61983ae7ad9f1f78ed1cc838a4ec8eeb8292d1.
// Component-independent regression; the customer's reported jump to the top still needs runtime verification.
describe('passive message updates preserve reading position', () => {
  const scopes: ReturnType<typeof effectScope>[] = []
  afterEach(() => { scopes.splice(0).forEach((scope) => scope.stop()); vi.clearAllMocks() })

  function setup(enterprise: boolean, top: number) {
    const scope = effectScope()
    scopes.push(scope)
    const element = document.createElement('div')
    Object.defineProperties(element, { scrollHeight: { value: 1000 }, clientHeight: { value: 400 } })
    element.scrollTop = top
    const scrollEl = ref<HTMLElement | null>(element)
    const messages = ref<ImMessage[]>([])
    const activeConversationId = ref<number | null>(1)
    const conversations = ref<ImConversationSummary[]>([{
      id: 1, title: '客服', is_direct: true, last_message_at: null, last_message_preview: '', unread_count: 0,
      is_enterprise_dedicated_cs: enterprise,
    }])
    const message: ImMessage = { id: 2, conversation_id: 1, sender_user_id: 2, body: '新消息', created_at: null }
    imMocks.fetchEnterpriseCsThread.mockResolvedValue({ conversation: conversations.value[0], messages: [message] })
    const scrollToBottom = vi.fn(() => { element.scrollTop = element.scrollHeight })
    const common = { conversations, activeConversationId, messages, scrollEl, scrollToBottom, playIncoming: vi.fn() }
    const bridge = scope.run(() => useEnterpriseCsBridge({ ...common, enabled: enterprise }))!
    const realtime = useImRealtime({
      ...common, localUserId: ref(29), wsConnected: ref(false), wsConnecting: ref(false),
      loadConversations: vi.fn(async () => {}), isCustomerEnterpriseCs: () => enterprise,
    })
    return { element, messages, activeConversationId, scrollToBottom, update: async () => {
      if (enterprise) await bridge.refreshEnterpriseCsThread()
      else realtime.applyIncomingMessage(message, 1)
      await nextTick()
    } }
  }

  for (const enterprise of [false, true]) {
    const source = enterprise ? '客服轮询' : '实时消息'
    it(`${source}保留正在阅读的旧消息位置`, async () => {
      const state = setup(enterprise, 120)
      await state.update()
      expect(state.messages.value).toHaveLength(1)
      expect(state.element.scrollTop).toBe(120)
      expect(state.scrollToBottom).not.toHaveBeenCalled()
    })
    it(`${source}继续跟随底部的新消息`, async () => {
      const state = setup(enterprise, 600)
      await state.update()
      expect(state.scrollToBottom).toHaveBeenCalledOnce()
    })
    it(`${source}不把旧会话的延迟滚动带到新会话`, async () => {
      const state = setup(enterprise, 600)
      const pending = state.update()
      state.activeConversationId.value = 3
      await pending
      expect(state.scrollToBottom).not.toHaveBeenCalled()
    })
  }
})
