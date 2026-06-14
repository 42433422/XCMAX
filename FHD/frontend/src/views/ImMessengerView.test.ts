import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import ImMessengerView from './ImMessengerView.vue'

vi.mock('@/api/im', () => ({
  fetchImConversations: vi.fn().mockResolvedValue([]),
  fetchImMessages: vi.fn().mockResolvedValue({ messages: [], has_more: false }),
  sendImMessage: vi.fn().mockResolvedValue({ success: true }),
  createDirectConversation: vi.fn().mockResolvedValue({ id: 1 }),
  fetchImContacts: vi.fn().mockResolvedValue([]),
  imWebSocketUrl: vi.fn(() => 'ws://localhost/ws'),
  markImRead: vi.fn().mockResolvedValue({}),
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

  it('renders empty conversation list', async () => {
    const wrapper = mount(ImMessengerView, {
      global: { stubs: { RouterLink: true } },
    })
    await flushPromises()
    expect(wrapper.find('.im-messenger').exists()).toBe(true)
    expect(wrapper.text()).toContain('还没有会话')
  })
})
