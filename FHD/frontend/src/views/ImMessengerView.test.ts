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
vi.mock('@/api/codexSuperEmployee', () => ({
  fetchCodexSuperEmployeeMessages: vi.fn().mockResolvedValue([]),
  sendCodexSuperEmployeeMessage: vi.fn().mockResolvedValue({
    dispatch: { request_id: 'req-1', status: 'queued', queued: true },
    messages: [
      {
        id: 'm-user',
        role: 'user',
        body: '修复登录问题',
        created_at: '2026-06-19T00:00:00Z',
        status: 'sent',
        dispatch_request_id: 'req-1',
      },
      {
        id: 'm-codex',
        role: 'system',
        body: '已进入软件内 Codex 调用队列，等待跨设备调度器接走。',
        created_at: '2026-06-19T00:00:01Z',
        status: 'queued',
        kind: 'dispatcher',
        dispatch_request_id: 'req-1',
      },
    ],
  }),
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
    vi.clearAllMocks()
    vi.stubGlobal('WebSocket', MockWebSocket as unknown as typeof WebSocket)
    MockWebSocket.instances = []
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.unstubAllEnvs()
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

  it('shows Codex super employee in admin information console without xiao c or enterprise cs', async () => {
    const { authApi } = await import('@/api/auth')
    const { createDirectConversation } = await import('@/api/im')
    const {
      fetchCodexSuperEmployeeMessages,
      sendCodexSuperEmployeeMessage,
    } = await import('@/api/codexSuperEmployee')
    vi.stubEnv('VITE_XCMAX_ADMIN_CONSOLE', '1')
    vi.mocked(authApi.getCurrentUser).mockResolvedValueOnce({
      data: {
        user: { id: 1 },
        account_kind: 'admin',
        market_is_admin: true,
      },
    } as Awaited<ReturnType<typeof authApi.getCurrentUser>>)

    const wrapper = mount(ImMessengerView, {
      global: { stubs: { RouterLink: true } },
    })
    await flushPromises()

    expect(wrapper.text()).not.toContain('企业专属客服')
    expect(wrapper.text()).not.toContain('小C助理')
    expect(wrapper.text()).toContain('固定员工')
    expect(wrapper.text()).toContain('超级员工-Codex')
    expect(wrapper.text()).toContain('全设备协同调度')
    expect(wrapper.text()).toContain('Codex')
    expect(wrapper.find('.im-conv-item--pinned').exists()).toBe(true)
    expect(fetchCodexSuperEmployeeMessages).toHaveBeenCalledWith({ scope: 'admin' })

    await wrapper.find('.im-conv-item--pinned').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('跨设备协作开发员工')
    expect(wrapper.text()).toContain('全设备 Codex')
    expect(createDirectConversation).not.toHaveBeenCalled()

    const input = wrapper.find('.im-compose--codex input')
    await input.setValue('修复登录问题')
    await wrapper.find('.im-compose--codex button').trigger('click')
    await flushPromises()

    expect(sendCodexSuperEmployeeMessage).toHaveBeenCalledWith(
      '修复登录问题',
      {
        source: 'admin_im',
        client_surface: 'admin_console',
        target_devices: ['all'],
      },
      { scope: 'admin' },
    )
    expect(wrapper.text()).toContain('已进入软件内 Codex 调用队列')
    expect(wrapper.text()).toContain('调度器')

    await input.setValue('继续验证回车调用')
    await input.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(sendCodexSuperEmployeeMessage).toHaveBeenCalledWith(
      '继续验证回车调用',
      {
        source: 'admin_im',
        client_surface: 'admin_console',
        target_devices: ['all'],
      },
      { scope: 'admin' },
    )
  })

  it('shows Codex super employee for mobile admin information and uses mobile API scope', async () => {
    const { authApi } = await import('@/api/auth')
    const {
      fetchCodexSuperEmployeeMessages,
      sendCodexSuperEmployeeMessage,
    } = await import('@/api/codexSuperEmployee')
    vi.mocked(authApi.getCurrentUser).mockResolvedValueOnce({
      data: {
        user: { id: 1 },
        account_kind: 'admin',
        market_is_admin: true,
      },
    } as Awaited<ReturnType<typeof authApi.getCurrentUser>>)

    const wrapper = mount(ImMessengerView, {
      global: { stubs: { RouterLink: true } },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('固定员工')
    expect(wrapper.text()).toContain('超级员工-Codex')
    expect(fetchCodexSuperEmployeeMessages).toHaveBeenCalledWith({ scope: 'mobile' })

    const input = wrapper.find('.im-compose--codex input')
    await input.setValue('手机上调用 Codex')
    await wrapper.find('.im-compose--codex button').trigger('click')
    await flushPromises()

    expect(sendCodexSuperEmployeeMessage).toHaveBeenCalledWith(
      '手机上调用 Codex',
      {
        source: 'mobile_im',
        client_surface: 'mobile',
        target_devices: ['all'],
      },
      { scope: 'mobile' },
    )
  })
})
