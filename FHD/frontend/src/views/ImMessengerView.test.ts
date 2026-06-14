import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { ref } from 'vue'
import { mount, flushPromises } from '@vue/test-utils'
import ImMessengerView from './ImMessengerView.vue'

const enterpriseCsContact = vi.hoisted(() => ({
  id: 99,
  display_name: '企业专属客服',
  username: 'enterprise-cs',
  is_enterprise_dedicated_cs: true,
}))

vi.mock('@/api/im', () => ({
  fetchImConversations: vi.fn().mockResolvedValue([
    {
      id: 1,
      title: '企业专属客服',
      is_direct: true,
      last_message_at: null,
      last_message_preview: '',
      unread_count: 0,
      is_enterprise_dedicated_cs: true,
    },
  ]),
  fetchImMessages: vi.fn().mockResolvedValue([]),
  sendImMessage: vi.fn().mockResolvedValue({ success: true }),
  createDirectConversation: vi.fn().mockResolvedValue({ id: 1 }),
  fetchImContacts: vi.fn().mockResolvedValue([enterpriseCsContact]),
  imWebSocketUrl: vi.fn(() => 'ws://localhost/ws'),
  markImRead: vi.fn().mockResolvedValue({}),
}))
vi.mock('vue-router', () => ({
  useRoute: () => ({ query: {} }),
}))
vi.mock('pinia', async (importOriginal) => {
  const actual = await importOriginal<typeof import('pinia')>()
  return {
    ...actual,
    storeToRefs: () => ({ isAdminAccount: ref(false) }),
  }
})
vi.mock('@/stores/accountProfile', () => ({
  useAccountProfileStore: () => ({}),
}))
vi.mock('@/api/auth', () => ({
  authApi: {
    getCurrentUser: vi.fn().mockResolvedValue({ data: { user: { id: 1 } } }),
  },
}))
vi.mock('@/composables/useImSounds', () => ({
  useImSounds: () => ({ playIncoming: vi.fn(), playOutgoing: vi.fn() }),
}))
vi.mock('@/composables/useAppToast', () => ({
  showAppToast: vi.fn(),
}))
vi.mock('@/composables/useXcmaxSync', () => ({
  useXcmaxSync: () => ({
    onImMessage: vi.fn(() => () => {}),
    onImReadState: vi.fn(() => () => {}),
  }),
}))

class MockWebSocket {
  static instances: MockWebSocket[] = []
  onopen: (() => void) | null = null
  onclose: (() => void) | null = null
  onmessage: ((ev: { data: string }) => void) | null = null
  constructor(_url: string) {
    MockWebSocket.instances.push(this)
    queueMicrotask(() => this.onopen?.())
  }
  close() {
    this.onclose?.()
  }
  send() {}
}

describe('ImMessengerView.vue', () => {
  beforeEach(() => {
    vi.stubGlobal('WebSocket', MockWebSocket as unknown as typeof WebSocket)
    MockWebSocket.instances = []
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows enterprise dedicated cs as pinned fixed contact', async () => {
    const wrapper = mount(ImMessengerView, {
      global: { stubs: { RouterLink: true } },
    })
    await flushPromises()
    expect(wrapper.find('.im-messenger').exists()).toBe(true)
    expect(wrapper.text()).toContain('固定联系人')
    expect(wrapper.text()).toContain('企业专属客服')
    expect(wrapper.text()).not.toContain('还没有会话')
    expect(wrapper.find('.im-conv-item--pinned').exists()).toBe(true)
  })

  it('shows pinned contact when conversations list is empty', async () => {
    const { fetchImConversations } = await import('@/api/im')
    vi.mocked(fetchImConversations).mockResolvedValueOnce([])
    const wrapper = mount(ImMessengerView, {
      global: { stubs: { RouterLink: true } },
    })
    await flushPromises()
    expect(wrapper.text()).toContain('企业专属客服')
    expect(wrapper.text()).not.toContain('还没有会话')
  })
})
