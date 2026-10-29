import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope, ref } from 'vue'
import { useEnterpriseCsBridge } from '@/composables/messenger/useEnterpriseCsBridge'
import { useCsInboxBridge } from '@/composables/messenger/useCsInboxBridge'
import type { ImConversationSummary, ImMessage } from '@/api/im'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'

afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers() })

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

describe.each(['admin', 'customer'] as const)('%s CS snapshot lifetime', (kind) => {
  function fixture(status: ImConversationSummary['cs_status'] = 'human_pending') {
    const scope = effectScope()
    const messages = ref<ImMessage[]>([oldMessage])
    const conversations = ref([{ ...csConversation, cs_status: status, is_cs_inbox: kind === 'admin', is_enterprise_dedicated_cs: kind === 'customer' }])
    const options = { conversations, activeConversationId: ref<number | null>(21), messages, playIncoming: vi.fn(), scrollEl: ref(null) }
    const bridge = scope.run(() => kind === 'admin'
      ? useCsInboxBridge({ ...options, enabled: ref(true) })
      : useEnterpriseCsBridge({ ...options, enabled: true }))!
    const refresh = 'refreshCsInbox' in bridge ? bridge.refreshCsInbox : bridge.refreshEnterpriseCsThread
    const start = 'startCsInboxPolling' in bridge ? bridge.startCsInboxPolling : bridge.startEnterpriseCsPolling
    const request = kind === 'admin' ? imMocks.fetchCsInboxMessages : imMocks.fetchEnterpriseCsThread
    const response = () => kind === 'admin' ? [{ ...oldMessage }] : {
      conversation: { ...csConversation, cs_status: status, is_cs_inbox: false, is_enterprise_dedicated_cs: true }, messages: [{ ...oldMessage }],
    }
    imMocks.fetchCsInbox.mockImplementation(async () => [{ ...csConversation, cs_status: status }])
    request.mockReset().mockImplementation(async () => response())
    return { scope, messages, conversations, refresh, start, request, response, options }
  }

  it('retains unchanged message identity and pauses/resumes the actual bridge', async () => {
    vi.useFakeTimers()
    const visibility = vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden')
    const f = fixture()
    await f.refresh()
    const previous = f.messages.value
    await f.refresh()
    expect(f.messages.value).toBe(previous)
    f.start()
    await vi.advanceTimersByTimeAsync(60_000)
    expect(f.request).toHaveBeenCalledTimes(2)
    visibility.mockReturnValue('visible')
    document.dispatchEvent(new Event('visibilitychange'))
    expect(f.request).toHaveBeenCalledTimes(3)
    await vi.advanceTimersByTimeAsync(0)
    expect(f.messages.value).toBe(previous)
    f.scope.stop()
  })

  it('discards an in-flight response after switching accounts', async () => {
    const f = fixture()
    let resolve!: (value: unknown) => void
    f.request.mockImplementationOnce(() => new Promise((done) => { resolve = done }))
    const pending = f.refresh()
    productReadAccountEpoch.value++
    resolve(f.response())
    await pending
    expect(f.messages.value).toEqual([])
    expect(f.options.playIncoming).not.toHaveBeenCalled()
    f.scope.stop()
  })

  it('keeps the short polling interval while an AI response is still processing', async () => {
    vi.useFakeTimers()
    vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible')
    const f = fixture('ai_processing')
    f.start()
    await vi.advanceTimersByTimeAsync(10_000)
    expect(f.request).toHaveBeenCalledTimes(4)
    f.scope.stop()
  })
})
