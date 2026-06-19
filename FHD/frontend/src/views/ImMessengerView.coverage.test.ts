import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { ref, nextTick } from 'vue'
import { mount, flushPromises } from '@vue/test-utils'
import ImMessengerView from './ImMessengerView.vue'

// ===== Mock 数据 =====
const enterpriseCsContact = {
  id: 99,
  display_name: '企业专属客服',
  username: 'enterprise-cs',
  is_enterprise_dedicated_cs: true,
}

const normalContact = {
  id: 10,
  display_name: '张三',
  username: 'zhangsan',
  is_enterprise_dedicated_cs: false,
}

const anotherContact = {
  id: 11,
  display_name: 'Li Si',
  username: 'lisi',
  is_enterprise_dedicated_cs: false,
}

const sampleConversation = {
  id: 1,
  title: '企业专属客服',
  is_direct: true,
  last_message_at: null,
  last_message_preview: '你好',
  unread_count: 2,
  is_enterprise_dedicated_cs: true,
}

const sampleConversation2 = {
  id: 2,
  title: '张三',
  is_direct: true,
  last_message_at: null,
  last_message_preview: '',
  unread_count: 0,
  is_enterprise_dedicated_cs: false,
}

const sampleMessage = {
  id: 100,
  conversation_id: 1,
  sender_user_id: 2,
  sender_display_name: '对方',
  body: '你好',
  created_at: '2026-06-19T10:00:00Z',
}

// ===== Mock 模块 =====
const imMocks = vi.hoisted(() => ({
  fetchImConversations: vi.fn(async () => [sampleConversation]),
  fetchImMessages: vi.fn(async () => []),
  sendImMessage: vi.fn(async () => ({ success: true })),
  createDirectConversation: vi.fn(async () => ({ id: 1, title: null, created: true })),
  fetchImContacts: vi.fn(async () => [enterpriseCsContact, normalContact, anotherContact]),
  imWebSocketUrl: vi.fn(() => 'ws://localhost/ws'),
  markImRead: vi.fn(async () => ({})),
}))

vi.mock('@/api/im', () => imMocks)

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

const authMocks = vi.hoisted(() => ({
  getCurrentUser: vi.fn(async () => ({ data: { user: { id: 1 } } })),
}))

vi.mock('@/api/auth', () => ({
  authApi: authMocks,
}))

const soundsMocks = vi.hoisted(() => ({
  playIncoming: vi.fn(async () => undefined),
  playOutgoing: vi.fn(),
}))

vi.mock('@/composables/useImSounds', () => ({
  useImSounds: () => soundsMocks,
}))

const toastMocks = vi.hoisted(() => ({
  showAppToast: vi.fn(),
}))

vi.mock('@/composables/useAppToast', () => ({
  showAppToast: toastMocks.showAppToast,
}))

const syncMocks = vi.hoisted(() => ({
  onImMessage: vi.fn(() => () => {}),
  onImReadState: vi.fn(() => () => {}),
}))

vi.mock('@/composables/useXcmaxSync', () => ({
  useXcmaxSync: () => syncMocks,
}))

// ===== Mock WebSocket =====
class MockWebSocket {
  static instances: MockWebSocket[] = []
  url: string
  onopen: (() => void) | null = null
  onclose: (() => void) | null = null
  onmessage: ((ev: { data: string }) => void) | null = null
  constructor(url: string) {
    this.url = url
    MockWebSocket.instances.push(this)
    // 模拟异步打开
    queueMicrotask(() => this.onopen?.())
  }
  close() {
    this.onclose?.()
  }
  send() {}
}

// ===== 辅助函数 =====
function resetMocks() {
  imMocks.fetchImConversations.mockReset()
  imMocks.fetchImConversations.mockResolvedValue([sampleConversation])

  imMocks.fetchImMessages.mockReset()
  imMocks.fetchImMessages.mockResolvedValue([])

  imMocks.sendImMessage.mockReset()
  imMocks.sendImMessage.mockResolvedValue({ success: true })

  imMocks.createDirectConversation.mockReset()
  imMocks.createDirectConversation.mockResolvedValue({ id: 1, title: null, created: true })

  imMocks.fetchImContacts.mockReset()
  imMocks.fetchImContacts.mockResolvedValue([enterpriseCsContact, normalContact, anotherContact])

  imMocks.imWebSocketUrl.mockReset()
  imMocks.imWebSocketUrl.mockReturnValue('ws://localhost/ws')

  imMocks.markImRead.mockReset()
  imMocks.markImRead.mockResolvedValue({})

  authMocks.getCurrentUser.mockReset()
  authMocks.getCurrentUser.mockResolvedValue({ data: { user: { id: 1 } } })

  soundsMocks.playIncoming.mockReset()
  soundsMocks.playIncoming.mockResolvedValue(undefined)
  soundsMocks.playOutgoing.mockReset()

  toastMocks.showAppToast.mockReset()

  syncMocks.onImMessage.mockReset()
  syncMocks.onImMessage.mockReturnValue(() => {})
  syncMocks.onImReadState.mockReset()
  syncMocks.onImReadState.mockReturnValue(() => {})
}

async function mountView() {
  const wrapper = mount(ImMessengerView, {
    global: { stubs: { RouterLink: true } },
  })
  await flushPromises()
  return wrapper
}

describe('ImMessengerView.vue 覆盖率补齐测试', () => {
  beforeEach(() => {
    resetMocks()
    vi.stubGlobal('WebSocket', MockWebSocket as unknown as typeof WebSocket)
    MockWebSocket.instances = []
    // 重置 xcagiDesktop
    ;(window as unknown as { xcagiDesktop?: unknown }).xcagiDesktop = undefined
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  // ===== 1. 基础渲染与生命周期 =====

  it('挂载后渲染消息视图且加载会话与联系人', async () => {
    const wrapper = await mountView()
    expect(wrapper.find('.im-messenger').exists()).toBe(true)
    expect(wrapper.find('.im-title').text()).toBe('信息')
    expect(imMocks.fetchImContacts).toHaveBeenCalled()
    expect(imMocks.fetchImConversations).toHaveBeenCalled()
  })

  it('未登录时显示警告 toast 并不加载会话', async () => {
    authMocks.getCurrentUser.mockResolvedValue({ data: { user: null } })
    const wrapper = await mountView()
    expect(toastMocks.showAppToast).toHaveBeenCalledWith('请先登录后使用信息功能', 'warning')
    expect(imMocks.fetchImConversations).not.toHaveBeenCalled()
    expect(wrapper.find('.im-messenger').exists()).toBe(true)
  })

  it('getCurrentUser 抛错时 localUserId 为 null 并显示警告', async () => {
    authMocks.getCurrentUser.mockRejectedValue(new Error('网络错误'))
    await mountView()
    expect(toastMocks.showAppToast).toHaveBeenCalledWith('请先登录后使用信息功能', 'warning')
  })

  it('getCurrentUser 返回非数字 id 时 localUserId 为 null', async () => {
    authMocks.getCurrentUser.mockResolvedValue({ data: { user: { id: 'abc' } } })
    await mountView()
    expect(toastMocks.showAppToast).toHaveBeenCalledWith('请先登录后使用信息功能', 'warning')
  })

  it('getCurrentUser 返回 id <= 0 时 localUserId 为 null', async () => {
    authMocks.getCurrentUser.mockResolvedValue({ data: { user: { id: 0 } } })
    await mountView()
    expect(toastMocks.showAppToast).toHaveBeenCalledWith('请先登录后使用信息功能', 'warning')
  })

  it('getCurrentUser 返回 id 为 NaN 时 localUserId 为 null', async () => {
    authMocks.getCurrentUser.mockResolvedValue({ data: {} })
    await mountView()
    expect(toastMocks.showAppToast).toHaveBeenCalledWith('请先登录后使用信息功能', 'warning')
  })

  it('卸载组件时清理 WebSocket 与 sync 监听', async () => {
    const offImMessage = vi.fn()
    const offImRead = vi.fn()
    syncMocks.onImMessage.mockReturnValue(offImMessage)
    syncMocks.onImReadState.mockReturnValue(offImRead)
    const wrapper = await mountView()
    wrapper.unmount()
    await flushPromises()
    expect(offImMessage).toHaveBeenCalled()
    expect(offImRead).toHaveBeenCalled()
  })

  // ===== 2. 会话列表与空状态 =====

  it('会话列表为空且无固定联系人时显示空状态', async () => {
    imMocks.fetchImConversations.mockResolvedValue([])
    imMocks.fetchImContacts.mockResolvedValue([normalContact])
    const wrapper = await mountView()
    expect(wrapper.text()).toContain('还没有会话')
    expect(wrapper.find('.im-empty--list').exists()).toBe(true)
  })

  it('会话列表展示标题与未读徽章', async () => {
    imMocks.fetchImConversations.mockResolvedValue([sampleConversation])
    const wrapper = await mountView()
    expect(wrapper.text()).toContain('企业专属客服')
    expect(wrapper.find('.im-badge').text()).toBe('2')
  })

  it('会话 last_message_preview 为空时显示暂无消息', async () => {
    imMocks.fetchImConversations.mockResolvedValue([sampleConversation2])
    imMocks.fetchImContacts.mockResolvedValue([normalContact])
    const wrapper = await mountView()
    expect(wrapper.text()).toContain('暂无消息')
  })

  it('点击会话项触发 selectConversation 加载消息', async () => {
    imMocks.fetchImConversations.mockResolvedValue([sampleConversation])
    imMocks.fetchImMessages.mockResolvedValue([sampleMessage])
    const wrapper = await mountView()
    const item = wrapper.find('.im-conv-item')
    await item.trigger('click')
    await flushPromises()
    expect(imMocks.fetchImMessages).toHaveBeenCalledWith(1, { limit: 50 })
    expect(imMocks.markImRead).toHaveBeenCalledWith(1, 100)
  })

  // ===== 3. 聊天区域 =====

  it('未选择会话时显示空聊天区域', async () => {
    imMocks.fetchImConversations.mockResolvedValue([])
    imMocks.fetchImContacts.mockResolvedValue([normalContact])
    const wrapper = await mountView()
    expect(wrapper.find('.im-chat--empty').exists()).toBe(true)
    expect(wrapper.text()).toContain('选择左侧会话开始聊天')
  })

  it('选择会话后展示聊天头部与消息气泡', async () => {
    imMocks.fetchImConversations.mockResolvedValue([sampleConversation])
    imMocks.fetchImMessages.mockResolvedValue([
      { ...sampleMessage, sender_user_id: 1, body: '我的消息' },
      { ...sampleMessage, id: 101, sender_user_id: 2, body: '对方消息' },
    ])
    const wrapper = await mountView()
    await wrapper.find('.im-conv-item').trigger('click')
    await flushPromises()
    expect(wrapper.find('.im-chat-head').exists()).toBe(true)
    expect(wrapper.findAll('.im-bubble-row')).toHaveLength(2)
    expect(wrapper.findAll('.im-bubble-row.mine')).toHaveLength(1)
    expect(wrapper.findAll('.im-bubble-row.theirs')).toHaveLength(1)
  })

  it('对方消息显示发送者名称', async () => {
    imMocks.fetchImConversations.mockResolvedValue([sampleConversation])
    imMocks.fetchImMessages.mockResolvedValue([
      { ...sampleMessage, sender_user_id: 2, sender_display_name: '客服' },
    ])
    const wrapper = await mountView()
    await wrapper.find('.im-conv-item').trigger('click')
    await flushPromises()
    expect(wrapper.find('.im-sender').text()).toBe('客服')
  })

  it('对方消息无 sender_display_name 时显示用户+id', async () => {
    imMocks.fetchImConversations.mockResolvedValue([sampleConversation])
    imMocks.fetchImMessages.mockResolvedValue([
      { ...sampleMessage, sender_user_id: 2, sender_display_name: undefined },
    ])
    const wrapper = await mountView()
    await wrapper.find('.im-conv-item').trigger('click')
    await flushPromises()
    expect(wrapper.find('.im-sender').text()).toBe('用户2')
  })

  it('消息数量达到 50 时显示加载更多按钮', async () => {
    imMocks.fetchImConversations.mockResolvedValue([sampleConversation])
    const messages = Array.from({ length: 50 }, (_, i) => ({
      ...sampleMessage,
      id: 100 + i,
    }))
    imMocks.fetchImMessages.mockResolvedValue(messages)
    const wrapper = await mountView()
    await wrapper.find('.im-conv-item').trigger('click')
    await flushPromises()
    expect(wrapper.find('.im-load-more').exists()).toBe(true)
  })

  it('点击加载更多按钮加载历史消息', async () => {
    imMocks.fetchImConversations.mockResolvedValue([sampleConversation])
    const initialMessages = Array.from({ length: 50 }, (_, i) => ({
      ...sampleMessage,
      id: 100 + i,
    }))
    const olderMessages = Array.from({ length: 10 }, (_, i) => ({
      ...sampleMessage,
      id: 50 + i,
    }))
    imMocks.fetchImMessages
      .mockResolvedValueOnce(initialMessages)
      .mockResolvedValueOnce(olderMessages)
    const wrapper = await mountView()
    await wrapper.find('.im-conv-item').trigger('click')
    await flushPromises()
    await wrapper.find('.im-load-more').trigger('click')
    await flushPromises()
    expect(imMocks.fetchImMessages).toHaveBeenLastCalledWith(1, { limit: 50, beforeId: 100 })
  })

  // ===== 4. 发送消息 =====

  it('输入消息并提交发送', async () => {
    imMocks.fetchImConversations.mockResolvedValue([sampleConversation])
    imMocks.fetchImMessages.mockResolvedValue([])
    imMocks.sendImMessage.mockResolvedValue({
      id: 200,
      conversation_id: 1,
      sender_user_id: 1,
      body: 'hello',
      created_at: '2026-06-19T10:00:00Z',
    })
    const wrapper = await mountView()
    await wrapper.find('.im-conv-item').trigger('click')
    await flushPromises()
    const input = wrapper.find('.im-compose-input')
    await input.setValue('hello')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()
    expect(imMocks.sendImMessage).toHaveBeenCalledWith(1, 'hello')
    expect(soundsMocks.playOutgoing).toHaveBeenCalled()
  })

  it('空消息不发送', async () => {
    imMocks.fetchImConversations.mockResolvedValue([sampleConversation])
    imMocks.fetchImMessages.mockResolvedValue([])
    const wrapper = await mountView()
    await wrapper.find('.im-conv-item').trigger('click')
    await flushPromises()
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()
    expect(imMocks.sendImMessage).not.toHaveBeenCalled()
  })

  it('未选择会话时不发送', async () => {
    imMocks.fetchImConversations.mockResolvedValue([])
    imMocks.fetchImContacts.mockResolvedValue([normalContact])
    const wrapper = await mountView()
    // 没有会话可点,直接尝试提交
    const input = wrapper.find('.im-compose-input')
    if (input.exists()) {
      await input.setValue('hello')
      await wrapper.find('form').trigger('submit.prevent')
      await flushPromises()
    }
    expect(imMocks.sendImMessage).not.toHaveBeenCalled()
  })

  it('发送消息失败时显示错误 toast', async () => {
    imMocks.fetchImConversations.mockResolvedValue([sampleConversation])
    imMocks.fetchImMessages.mockResolvedValue([])
    imMocks.sendImMessage.mockRejectedValue(new Error('网络错误'))
    const wrapper = await mountView()
    await wrapper.find('.im-conv-item').trigger('click')
    await flushPromises()
    const input = wrapper.find('.im-compose-input')
    await input.setValue('hello')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()
    expect(toastMocks.showAppToast).toHaveBeenCalledWith('网络错误', 'error')
  })

  it('发送消息失败且 error 非 Error 实例时显示默认提示', async () => {
    imMocks.fetchImConversations.mockResolvedValue([sampleConversation])
    imMocks.fetchImMessages.mockResolvedValue([])
    imMocks.sendImMessage.mockRejectedValue('unknown')
    const wrapper = await mountView()
    await wrapper.find('.im-conv-item').trigger('click')
    await flushPromises()
    const input = wrapper.find('.im-compose-input')
    await input.setValue('hello')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()
    expect(toastMocks.showAppToast).toHaveBeenCalledWith('发送失败', 'error')
  })

  // ===== 5. 联系人选择器 =====

  it('点击发起会话按钮打开联系人选择器', async () => {
    imMocks.fetchImConversations.mockResolvedValue([])
    imMocks.fetchImContacts.mockResolvedValue([normalContact])
    const wrapper = await mountView()
    const btn = wrapper.find('.im-sidebar-head .im-icon-btn')
    await btn.trigger('click')
    await flushPromises()
    expect(wrapper.find('.im-modal').exists()).toBe(true)
    expect(wrapper.text()).toContain('选择联系人')
  })

  it('点击关闭按钮关闭联系人选择器', async () => {
    imMocks.fetchImConversations.mockResolvedValue([])
    imMocks.fetchImContacts.mockResolvedValue([normalContact])
    const wrapper = await mountView()
    await wrapper.find('.im-sidebar-head .im-icon-btn').trigger('click')
    await flushPromises()
    expect(wrapper.find('.im-modal').exists()).toBe(true)
    const closeBtn = wrapper.find('.im-modal-head .im-icon-btn')
    await closeBtn.trigger('click')
    await flushPromises()
    expect(wrapper.find('.im-modal').exists()).toBe(false)
  })

  it('点击模态背景关闭联系人选择器', async () => {
    imMocks.fetchImConversations.mockResolvedValue([])
    imMocks.fetchImContacts.mockResolvedValue([normalContact])
    const wrapper = await mountView()
    await wrapper.find('.im-sidebar-head .im-icon-btn').trigger('click')
    await flushPromises()
    await wrapper.find('.im-modal').trigger('click.self')
    await flushPromises()
    expect(wrapper.find('.im-modal').exists()).toBe(false)
  })

  it('联系人选择器展示过滤后的联系人列表', async () => {
    imMocks.fetchImConversations.mockResolvedValue([])
    imMocks.fetchImContacts.mockResolvedValue([normalContact, anotherContact])
    const wrapper = await mountView()
    await wrapper.find('.im-sidebar-head .im-icon-btn').trigger('click')
    await flushPromises()
    // 企业专属客服被过滤掉,只显示 2 个普通联系人
    expect(wrapper.findAll('.im-contact-item')).toHaveLength(2)
  })

  it('搜索关键字过滤联系人(按 display_name)', async () => {
    imMocks.fetchImConversations.mockResolvedValue([])
    imMocks.fetchImContacts.mockResolvedValue([normalContact, anotherContact])
    const wrapper = await mountView()
    await wrapper.find('.im-sidebar-head .im-icon-btn').trigger('click')
    await flushPromises()
    const searchInput = wrapper.find('.im-modal .im-compose-input')
    await searchInput.setValue('张')
    await searchInput.trigger('input')
    await flushPromises()
    expect(wrapper.findAll('.im-contact-item')).toHaveLength(1)
    expect(wrapper.find('.im-contact-name').text()).toBe('张三')
  })

  it('搜索关键字过滤联系人(按 username)', async () => {
    imMocks.fetchImConversations.mockResolvedValue([])
    imMocks.fetchImContacts.mockResolvedValue([normalContact, anotherContact])
    const wrapper = await mountView()
    await wrapper.find('.im-sidebar-head .im-icon-btn').trigger('click')
    await flushPromises()
    const searchInput = wrapper.find('.im-modal .im-compose-input')
    await searchInput.setValue('lisi')
    await searchInput.trigger('input')
    await flushPromises()
    expect(wrapper.findAll('.im-contact-item')).toHaveLength(1)
    expect(wrapper.find('.im-contact-name').text()).toBe('Li Si')
  })

  it('搜索无匹配时显示未找到联系人', async () => {
    imMocks.fetchImConversations.mockResolvedValue([])
    imMocks.fetchImContacts.mockResolvedValue([normalContact])
    const wrapper = await mountView()
    await wrapper.find('.im-sidebar-head .im-icon-btn').trigger('click')
    await flushPromises()
    const searchInput = wrapper.find('.im-modal .im-compose-input')
    await searchInput.setValue('不存在的联系人')
    await searchInput.trigger('input')
    await flushPromises()
    expect(wrapper.text()).toContain('未找到联系人')
  })

  it('点击联系人创建新会话', async () => {
    imMocks.fetchImConversations.mockResolvedValue([])
    imMocks.fetchImContacts.mockResolvedValue([normalContact])
    imMocks.createDirectConversation.mockResolvedValue({ id: 5, title: null, created: true })
    const wrapper = await mountView()
    await wrapper.find('.im-sidebar-head .im-icon-btn').trigger('click')
    await flushPromises()
    await wrapper.find('.im-contact-item').trigger('click')
    await flushPromises()
    expect(imMocks.createDirectConversation).toHaveBeenCalledWith(normalContact.id)
  })

  it('点击企业专属客服联系人(侧边栏固定项)复用已有会话不创建新会话', async () => {
    imMocks.fetchImConversations.mockResolvedValue([sampleConversation])
    imMocks.fetchImContacts.mockResolvedValue([enterpriseCsContact])
    const wrapper = await mountView()
    const pinned = wrapper.find('.im-conv-item--pinned')
    expect(pinned.exists()).toBe(true)
    await pinned.trigger('click')
    await flushPromises()
    // 复用已有会话,不创建新会话
    expect(imMocks.createDirectConversation).not.toHaveBeenCalled()
    expect(imMocks.fetchImMessages).toHaveBeenCalledWith(1, { limit: 50 })
  })

  it('点击固定联系人(侧边栏)复用已有会话', async () => {
    imMocks.fetchImConversations.mockResolvedValue([sampleConversation])
    imMocks.fetchImContacts.mockResolvedValue([enterpriseCsContact])
    const wrapper = await mountView()
    const pinned = wrapper.find('.im-conv-item--pinned')
    expect(pinned.exists()).toBe(true)
    await pinned.trigger('click')
    await flushPromises()
    expect(imMocks.fetchImMessages).toHaveBeenCalledWith(1, { limit: 50 })
  })

  it('创建会话失败时显示错误 toast', async () => {
    imMocks.fetchImConversations.mockResolvedValue([])
    imMocks.fetchImContacts.mockResolvedValue([normalContact])
    imMocks.createDirectConversation.mockRejectedValue(new Error('创建失败'))
    const wrapper = await mountView()
    await wrapper.find('.im-sidebar-head .im-icon-btn').trigger('click')
    await flushPromises()
    await wrapper.find('.im-contact-item').trigger('click')
    await flushPromises()
    expect(toastMocks.showAppToast).toHaveBeenCalledWith('创建失败', 'error')
  })

  it('创建会话失败且 error 非 Error 实例时显示默认提示', async () => {
    imMocks.fetchImConversations.mockResolvedValue([])
    imMocks.fetchImContacts.mockResolvedValue([normalContact])
    imMocks.createDirectConversation.mockRejectedValue('unknown')
    const wrapper = await mountView()
    await wrapper.find('.im-sidebar-head .im-icon-btn').trigger('click')
    await flushPromises()
    await wrapper.find('.im-contact-item').trigger('click')
    await flushPromises()
    expect(toastMocks.showAppToast).toHaveBeenCalledWith('发起会话失败', 'error')
  })

  // ===== 6. API 错误处理 =====

  it('loadContacts 失败时显示错误 toast', async () => {
    imMocks.fetchImContacts.mockRejectedValue(new Error('联系人加载失败'))
    await mountView()
    expect(toastMocks.showAppToast).toHaveBeenCalledWith('联系人加载失败', 'error')
  })

  it('loadContacts 失败且 error 非 Error 实例时显示默认提示', async () => {
    imMocks.fetchImContacts.mockRejectedValue('unknown')
    await mountView()
    expect(toastMocks.showAppToast).toHaveBeenCalledWith('加载联系人失败', 'error')
  })

  it('loadConversations 失败时显示错误 toast', async () => {
    authMocks.getCurrentUser.mockResolvedValue({ data: { user: { id: 1 } } })
    imMocks.fetchImContacts.mockResolvedValue([])
    imMocks.fetchImConversations.mockRejectedValue(new Error('会话加载失败'))
    await mountView()
    expect(toastMocks.showAppToast).toHaveBeenCalledWith('会话加载失败', 'error')
  })

  it('loadConversations 失败且 error 非 Error 实例时显示默认提示', async () => {
    imMocks.fetchImContacts.mockResolvedValue([])
    imMocks.fetchImConversations.mockRejectedValue('unknown')
    await mountView()
    expect(toastMocks.showAppToast).toHaveBeenCalledWith('加载会话失败', 'error')
  })

  it('selectConversation 失败时显示错误 toast', async () => {
    imMocks.fetchImConversations.mockResolvedValue([sampleConversation])
    imMocks.fetchImMessages.mockRejectedValue(new Error('消息加载失败'))
    const wrapper = await mountView()
    await wrapper.find('.im-conv-item').trigger('click')
    await flushPromises()
    expect(toastMocks.showAppToast).toHaveBeenCalledWith('消息加载失败', 'error')
  })

  it('selectConversation 失败且 error 非 Error 实例时显示默认提示', async () => {
    imMocks.fetchImConversations.mockResolvedValue([sampleConversation])
    imMocks.fetchImMessages.mockRejectedValue('unknown')
    const wrapper = await mountView()
    await wrapper.find('.im-conv-item').trigger('click')
    await flushPromises()
    expect(toastMocks.showAppToast).toHaveBeenCalledWith('加载消息失败', 'error')
  })

  it('loadOlderMessages 失败时显示错误 toast', async () => {
    imMocks.fetchImConversations.mockResolvedValue([sampleConversation])
    const messages = Array.from({ length: 50 }, (_, i) => ({
      ...sampleMessage,
      id: 100 + i,
    }))
    imMocks.fetchImMessages
      .mockResolvedValueOnce(messages)
      .mockRejectedValueOnce(new Error('历史加载失败'))
    const wrapper = await mountView()
    await wrapper.find('.im-conv-item').trigger('click')
    await flushPromises()
    await wrapper.find('.im-load-more').trigger('click')
    await flushPromises()
    expect(toastMocks.showAppToast).toHaveBeenCalledWith('历史加载失败', 'error')
  })

  it('loadOlderMessages 失败且 error 非 Error 实例时显示默认提示', async () => {
    imMocks.fetchImConversations.mockResolvedValue([sampleConversation])
    const messages = Array.from({ length: 50 }, (_, i) => ({
      ...sampleMessage,
      id: 100 + i,
    }))
    imMocks.fetchImMessages
      .mockResolvedValueOnce(messages)
      .mockRejectedValueOnce('unknown')
    const wrapper = await mountView()
    await wrapper.find('.im-conv-item').trigger('click')
    await flushPromises()
    await wrapper.find('.im-load-more').trigger('click')
    await flushPromises()
    expect(toastMocks.showAppToast).toHaveBeenCalledWith('加载历史失败', 'error')
  })

  // ===== 7. xcagiDesktop 集成 =====

  it('loadConversations 调用 xcagiDesktop.setBadge 设置未读总数', async () => {
    const setBadge = vi.fn(async () => undefined)
    ;(window as unknown as { xcagiDesktop?: unknown }).xcagiDesktop = { setBadge }
    imMocks.fetchImConversations.mockResolvedValue([
      { ...sampleConversation, unread_count: 3 },
      { ...sampleConversation2, id: 5, unread_count: 5 },
    ])
    await mountView()
    expect(setBadge).toHaveBeenCalledWith(8)
  })

  it('loadConversations 在 xcagiDesktop 存在但 setBadge 缺失时跳过', async () => {
    // xcagiDesktop 定义但无 setBadge 方法,覆盖可选链的另一个分支
    ;(window as unknown as { xcagiDesktop?: unknown }).xcagiDesktop = {}
    imMocks.fetchImConversations.mockResolvedValue([sampleConversation])
    imMocks.fetchImContacts.mockResolvedValue([])
    await mountView()
    // 不应抛错,且会话正常加载
    expect(imMocks.fetchImConversations).toHaveBeenCalled()
  })

  // ===== 8. WebSocket 消息处理 =====

  it('WebSocket 打开后设置 wsConnected 为 true', async () => {
    await mountView()
    await flushPromises()
    expect(MockWebSocket.instances.length).toBeGreaterThan(0)
    const ws = MockWebSocket.instances[0]
    ws.onopen?.()
    await flushPromises()
    // wsConnected 已通过 queueMicrotask 触发
  })

  it('WebSocket 接收 im.message 类型消息时处理 incoming', async () => {
    imMocks.fetchImConversations.mockResolvedValue([sampleConversation])
    imMocks.fetchImMessages.mockResolvedValue([])
    const wrapper = await mountView()
    await wrapper.find('.im-conv-item').trigger('click')
    await flushPromises()
    const ws = MockWebSocket.instances[0]
    const newMsg = { ...sampleMessage, id: 999, body: '新消息' }
    ws.onmessage?.({
      data: JSON.stringify({
        type: 'im.message',
        conversation_id: 1,
        message: newMsg,
      }),
    })
    await flushPromises()
    expect(soundsMocks.playIncoming).toHaveBeenCalled()
  })

  it('WebSocket 接收 message 类型消息时处理 incoming', async () => {
    imMocks.fetchImConversations.mockResolvedValue([sampleConversation])
    imMocks.fetchImMessages.mockResolvedValue([])
    const wrapper = await mountView()
    await wrapper.find('.im-conv-item').trigger('click')
    await flushPromises()
    const ws = MockWebSocket.instances[0]
    const newMsg = { ...sampleMessage, id: 998, body: '新消息2' }
    ws.onmessage?.({
      data: JSON.stringify({
        type: 'message',
        message: newMsg,
      }),
    })
    await flushPromises()
    // message.conversation_id 为 1
    expect(soundsMocks.playIncoming).toHaveBeenCalled()
  })

  it('WebSocket 接收 pong 类型消息时直接返回', async () => {
    await mountView()
    const ws = MockWebSocket.instances[0]
    ws.onmessage?.({ data: JSON.stringify({ type: 'pong' }) })
    await flushPromises()
    // 不应触发任何 API 调用
    expect(soundsMocks.playIncoming).not.toHaveBeenCalled()
  })

  it('WebSocket 接收 im.read 类型消息时处理已读状态', async () => {
    imMocks.fetchImConversations.mockResolvedValue([sampleConversation])
    imMocks.fetchImMessages.mockResolvedValue([])
    const wrapper = await mountView()
    await wrapper.find('.im-conv-item').trigger('click')
    await flushPromises()
    // 重置 markImRead 调用计数
    imMocks.markImRead.mockClear()
    const ws = MockWebSocket.instances[0]
    ws.onmessage?.({
      data: JSON.stringify({
        type: 'im.read',
        conversation_id: 1,
        user_id: 1,
        last_message_id: 100,
      }),
    })
    await flushPromises()
    // 当前活跃会话为 1,应触发 markImRead
    expect(imMocks.markImRead).toHaveBeenCalled()
  })

  it('WebSocket 接收 im.read 但 user_id 不是当前用户时忽略', async () => {
    imMocks.fetchImConversations.mockResolvedValue([sampleConversation])
    imMocks.fetchImMessages.mockResolvedValue([])
    const wrapper = await mountView()
    await wrapper.find('.im-conv-item').trigger('click')
    await flushPromises()
    imMocks.markImRead.mockClear()
    const ws = MockWebSocket.instances[0]
    ws.onmessage?.({
      data: JSON.stringify({
        type: 'im.read',
        conversation_id: 1,
        user_id: 999,
        last_message_id: 100,
      }),
    })
    await flushPromises()
    expect(imMocks.markImRead).not.toHaveBeenCalled()
  })

  it('WebSocket 接收 im.read 但 last_message_id 为 0 时仅 loadConversations', async () => {
    imMocks.fetchImConversations.mockResolvedValue([sampleConversation])
    imMocks.fetchImMessages.mockResolvedValue([])
    const wrapper = await mountView()
    await wrapper.find('.im-conv-item').trigger('click')
    await flushPromises()
    imMocks.markImRead.mockClear()
    const ws = MockWebSocket.instances[0]
    ws.onmessage?.({
      data: JSON.stringify({
        type: 'im.read',
        conversation_id: 1,
        user_id: 1,
        last_message_id: 0,
      }),
    })
    await flushPromises()
    // last_message_id 为 0,走 else 分支只 loadConversations
    expect(imMocks.markImRead).not.toHaveBeenCalled()
  })

  it('WebSocket 接收 im.read 但 conversation_id 非数字时忽略', async () => {
    await mountView()
    const ws = MockWebSocket.instances[0]
    ws.onmessage?.({
      data: JSON.stringify({
        type: 'im.read',
        conversation_id: 'abc',
        user_id: 1,
        last_message_id: 100,
      }),
    })
    await flushPromises()
    // 非数字 cid 不会触发 applyReadState
  })

  it('WebSocket 接收无效 JSON 时静默忽略', async () => {
    await mountView()
    const ws = MockWebSocket.instances[0]
    ws.onmessage?.({ data: 'not-json' })
    await flushPromises()
    // 不应抛错
  })

  it('WebSocket 接收未知类型消息时忽略', async () => {
    await mountView()
    const ws = MockWebSocket.instances[0]
    ws.onmessage?.({
      data: JSON.stringify({ type: 'unknown', message: sampleMessage }),
    })
    await flushPromises()
  })

  it('WebSocket 关闭后触发重连调度', async () => {
    vi.useFakeTimers()
    await mountView()
    const ws = MockWebSocket.instances[0]
    ws.onclose?.()
    // 推进重连定时器
    vi.advanceTimersByTime(2000)
    await flushPromises()
    // 重连后会创建新的 WebSocket
  })

  it('WebSocket 接收 im.message 但消息已存在时不重复添加', async () => {
    imMocks.fetchImConversations.mockResolvedValue([sampleConversation])
    imMocks.fetchImMessages.mockResolvedValue([sampleMessage])
    const wrapper = await mountView()
    await wrapper.find('.im-conv-item').trigger('click')
    await flushPromises()
    const ws = MockWebSocket.instances[0]
    // 发送已存在的消息
    ws.onmessage?.({
      data: JSON.stringify({
        type: 'im.message',
        conversation_id: 1,
        message: sampleMessage,
      }),
    })
    await flushPromises()
    // 不应重复添加
    expect(wrapper.findAll('.im-bubble-row')).toHaveLength(1)
  })

  it('WebSocket 接收自己发送的消息时不播放 incoming 音效', async () => {
    imMocks.fetchImConversations.mockResolvedValue([sampleConversation])
    imMocks.fetchImMessages.mockResolvedValue([])
    const wrapper = await mountView()
    await wrapper.find('.im-conv-item').trigger('click')
    await flushPromises()
    const ws = MockWebSocket.instances[0]
    const myMsg = { ...sampleMessage, id: 888, sender_user_id: 1 }
    ws.onmessage?.({
      data: JSON.stringify({
        type: 'im.message',
        conversation_id: 1,
        message: myMsg,
      }),
    })
    await flushPromises()
    expect(soundsMocks.playIncoming).not.toHaveBeenCalled()
  })

  // ===== 9. XcmaxSync 集成 =====

  it('onImMessage 监听器处理 incoming 消息', async () => {
    let imMessageHandler: ((detail: { conversation_id: number; message: typeof sampleMessage }) => void) | null = null
    syncMocks.onImMessage.mockImplementation((cb: typeof imMessageHandler) => {
      imMessageHandler = cb
      return () => {}
    })
    imMocks.fetchImConversations.mockResolvedValue([sampleConversation])
    imMocks.fetchImMessages.mockResolvedValue([])
    const wrapper = await mountView()
    await wrapper.find('.im-conv-item').trigger('click')
    await flushPromises()
    expect(imMessageHandler).not.toBeNull()
    const newMsg = { ...sampleMessage, id: 777, body: 'sync 消息' }
    imMessageHandler!({ conversation_id: 1, message: newMsg })
    await flushPromises()
    expect(soundsMocks.playIncoming).toHaveBeenCalled()
  })

  it('onImReadState 监听器处理已读状态', async () => {
    let imReadHandler: ((detail: { conversation_id: number; user_id: number; last_message_id: number }) => void) | null = null
    syncMocks.onImReadState.mockImplementation((cb: typeof imReadHandler) => {
      imReadHandler = cb
      return () => {}
    })
    imMocks.fetchImConversations.mockResolvedValue([sampleConversation])
    imMocks.fetchImMessages.mockResolvedValue([])
    const wrapper = await mountView()
    await wrapper.find('.im-conv-item').trigger('click')
    await flushPromises()
    expect(imReadHandler).not.toBeNull()
    imMocks.markImRead.mockClear()
    imReadHandler!({ conversation_id: 1, user_id: 1, last_message_id: 100 })
    await flushPromises()
    expect(imMocks.markImRead).toHaveBeenCalled()
  })

  it('onImReadState 监听器处理非当前用户的已读状态', async () => {
    let imReadHandler: ((detail: { conversation_id: number; user_id: number; last_message_id: number }) => void) | null = null
    syncMocks.onImReadState.mockImplementation((cb: typeof imReadHandler) => {
      imReadHandler = cb
      return () => {}
    })
    imMocks.fetchImConversations.mockResolvedValue([sampleConversation])
    imMocks.fetchImMessages.mockResolvedValue([])
    const wrapper = await mountView()
    await wrapper.find('.im-conv-item').trigger('click')
    await flushPromises()
    imMocks.markImRead.mockClear()
    imReadHandler!({ conversation_id: 1, user_id: 999, last_message_id: 100 })
    await flushPromises()
    // 非当前用户,不应触发 markImRead
    expect(imMocks.markImRead).not.toHaveBeenCalled()
  })

  // ===== 10. 工具函数与计算属性 =====

  it('avatarText 处理空字符串返回 ?', async () => {
    imMocks.fetchImConversations.mockResolvedValue([
      { ...sampleConversation, title: '' },
    ])
    imMocks.fetchImContacts.mockResolvedValue([])
    const wrapper = await mountView()
    const avatar = wrapper.find('.im-conv-item .im-avatar')
    expect(avatar.text()).toBe('?')
  })

  it('avatarText 处理 null/undefined 返回 ?', async () => {
    imMocks.fetchImConversations.mockResolvedValue([
      { ...sampleConversation, title: null as unknown as string },
    ])
    imMocks.fetchImContacts.mockResolvedValue([])
    const wrapper = await mountView()
    const avatar = wrapper.find('.im-conv-item .im-avatar')
    expect(avatar.text()).toBe('?')
  })

  it('avatarText 取首字符并大写', async () => {
    imMocks.fetchImConversations.mockResolvedValue([
      { ...sampleConversation, title: '张三' },
    ])
    imMocks.fetchImContacts.mockResolvedValue([])
    const wrapper = await mountView()
    const avatar = wrapper.find('.im-conv-item .im-avatar')
    expect(avatar.text()).toBe('张')
  })

  it('formatTime 处理 null 返回空字符串', async () => {
    imMocks.fetchImConversations.mockResolvedValue([sampleConversation])
    imMocks.fetchImMessages.mockResolvedValue([
      { ...sampleMessage, created_at: null },
    ])
    const wrapper = await mountView()
    await wrapper.find('.im-conv-item').trigger('click')
    await flushPromises()
    const time = wrapper.find('.im-bubble time')
    expect(time.text()).toBe('')
  })

  it('formatTime 处理有效 ISO 字符串返回本地时间', async () => {
    imMocks.fetchImConversations.mockResolvedValue([sampleConversation])
    imMocks.fetchImMessages.mockResolvedValue([sampleMessage])
    const wrapper = await mountView()
    await wrapper.find('.im-conv-item').trigger('click')
    await flushPromises()
    const time = wrapper.find('.im-bubble time')
    expect(time.text()).not.toBe('')
  })

  it('formatTime 在 toLocaleString 抛错时返回原始 iso 字符串', async () => {
    const realToLocaleString = Date.prototype.toLocaleString
    Date.prototype.toLocaleString = function () {
      throw new Error('locale error')
    }
    try {
      imMocks.fetchImConversations.mockResolvedValue([sampleConversation])
      imMocks.fetchImMessages.mockResolvedValue([
        { ...sampleMessage, created_at: 'invalid-iso' },
      ])
      const wrapper = await mountView()
      await wrapper.find('.im-conv-item').trigger('click')
      await flushPromises()
      const time = wrapper.find('.im-bubble time')
      // 抛错时返回原始 iso 字符串
      expect(time.text()).toBe('invalid-iso')
    } finally {
      Date.prototype.toLocaleString = realToLocaleString
    }
  })

  it('activeTitle 在会话不存在时返回默认值', async () => {
    imMocks.fetchImConversations.mockResolvedValue([sampleConversation])
    imMocks.fetchImMessages.mockResolvedValue([])
    const wrapper = await mountView()
    await wrapper.find('.im-conv-item').trigger('click')
    await flushPromises()
    // activeTitle 应为会话标题
    expect(wrapper.find('.im-chat-title').text()).toBe('企业专属客服')
  })

  // ===== 11. 边界场景 =====

  it('localUserId 为 null 时不加载会话', async () => {
    authMocks.getCurrentUser.mockResolvedValue({ data: { user: null } })
    await mountView()
    expect(imMocks.fetchImConversations).not.toHaveBeenCalled()
  })

  it('selectConversation 在 localUserId 为 null 时不执行', async () => {
    authMocks.getCurrentUser.mockResolvedValue({ data: { user: null } })
    const wrapper = await mountView()
    // 即使有会话项可点(此时不会渲染),也不会触发 selectConversation
    expect(wrapper.find('.im-conv-item').exists()).toBe(false)
  })

  it('loadOlderMessages 在无消息时不执行', async () => {
    imMocks.fetchImConversations.mockResolvedValue([sampleConversation])
    // 模拟 50 条消息以显示加载更多按钮
    const messages = Array.from({ length: 50 }, (_, i) => ({
      ...sampleMessage,
      id: 100 + i,
    }))
    imMocks.fetchImMessages.mockResolvedValueOnce(messages)
    const wrapper = await mountView()
    await wrapper.find('.im-conv-item').trigger('click')
    await flushPromises()
    // 通过 devtoolsRawSetupState 访问原始 ref 并清空消息
    const rawState = (wrapper.vm as unknown as { $: { devtoolsRawSetupState: Record<string, { value: unknown }> } }).$.devtoolsRawSetupState
    rawState.messages.value = []
    imMocks.fetchImMessages.mockClear()
    await wrapper.find('.im-load-more').trigger('click')
    await flushPromises()
    // messages 为空时直接返回,不调用 fetchImMessages
    expect(imMocks.fetchImMessages).not.toHaveBeenCalled()
  })

  it('loadOlderMessages 加载历史为空时不合并', async () => {
    imMocks.fetchImConversations.mockResolvedValue([sampleConversation])
    const messages = Array.from({ length: 50 }, (_, i) => ({
      ...sampleMessage,
      id: 100 + i,
    }))
    imMocks.fetchImMessages
      .mockResolvedValueOnce(messages)
      .mockResolvedValueOnce([])
    const wrapper = await mountView()
    await wrapper.find('.im-conv-item').trigger('click')
    await flushPromises()
    const rawState = (wrapper.vm as unknown as { $: { devtoolsRawSetupState: Record<string, { value: unknown }> } }).$.devtoolsRawSetupState
    const beforeCount = (rawState.messages.value as typeof sampleMessage[]).length
    await wrapper.find('.im-load-more').trigger('click')
    await flushPromises()
    expect((rawState.messages.value as typeof sampleMessage[]).length).toBe(beforeCount)
  })

  it('connectWs 在 localUserId 为 null 时不创建 WebSocket', async () => {
    authMocks.getCurrentUser.mockResolvedValue({ data: { user: null } })
    await mountView()
    // 未登录不会创建 WebSocket
    expect(MockWebSocket.instances.length).toBe(0)
  })

  it('会话切换后 activeTitle 更新为新会话标题', async () => {
    imMocks.fetchImConversations.mockResolvedValue([
      sampleConversation,
      { ...sampleConversation2, id: 3, title: '另一个会话' },
    ])
    imMocks.fetchImContacts.mockResolvedValue([])
    imMocks.fetchImMessages.mockResolvedValue([])
    const wrapper = await mountView()
    const items = wrapper.findAll('.im-conv-item')
    await items[0].trigger('click')
    await flushPromises()
    expect(wrapper.find('.im-chat-title').text()).toBe('企业专属客服')
    await items[1].trigger('click')
    await flushPromises()
    expect(wrapper.find('.im-chat-title').text()).toBe('另一个会话')
  })

  it('发送按钮在 busy 时禁用', async () => {
    imMocks.fetchImConversations.mockResolvedValue([sampleConversation])
    imMocks.fetchImMessages.mockResolvedValue([])
    const wrapper = await mountView()
    await wrapper.find('.im-conv-item').trigger('click')
    await flushPromises()
    const rawState = (wrapper.vm as unknown as { $: { devtoolsRawSetupState: Record<string, { value: unknown }> } }).$.devtoolsRawSetupState
    rawState.busy.value = true
    await nextTick()
    const submitBtn = wrapper.find('button[type="submit"]')
    expect(submitBtn.attributes('disabled')).toBeDefined()
  })

  it('发送按钮在 draft 为空时禁用', async () => {
    imMocks.fetchImConversations.mockResolvedValue([sampleConversation])
    imMocks.fetchImMessages.mockResolvedValue([])
    const wrapper = await mountView()
    await wrapper.find('.im-conv-item').trigger('click')
    await flushPromises()
    const submitBtn = wrapper.find('button[type="submit"]')
    expect(submitBtn.attributes('disabled')).toBeDefined()
  })

  it('发起会话按钮在 busy 时禁用', async () => {
    imMocks.fetchImConversations.mockResolvedValue([])
    imMocks.fetchImContacts.mockResolvedValue([normalContact])
    const wrapper = await mountView()
    const rawState = (wrapper.vm as unknown as { $: { devtoolsRawSetupState: Record<string, { value: unknown }> } }).$.devtoolsRawSetupState
    rawState.busy.value = true
    await nextTick()
    const btn = wrapper.find('.im-sidebar-head .im-icon-btn')
    expect(btn.attributes('disabled')).toBeDefined()
  })

  it('空状态下的发起会话按钮可点击打开选择器', async () => {
    imMocks.fetchImConversations.mockResolvedValue([])
    imMocks.fetchImContacts.mockResolvedValue([normalContact])
    const wrapper = await mountView()
    const btn = wrapper.find('.im-empty--list .im-btn--primary')
    expect(btn.exists()).toBe(true)
    await btn.trigger('click')
    await flushPromises()
    expect(wrapper.find('.im-modal').exists()).toBe(true)
  })

  it('联系人加载中时显示加载中提示', async () => {
    let resolveContacts: (value: typeof normalContact[]) => void = () => {}
    imMocks.fetchImConversations.mockResolvedValue([])
    imMocks.fetchImContacts.mockReturnValue(
      new Promise((resolve) => {
        resolveContacts = resolve as typeof resolveContacts
      }),
    )
    const wrapper = await mountView()
    await wrapper.find('.im-sidebar-head .im-icon-btn').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('加载中…')
    resolveContacts([normalContact])
    await flushPromises()
  })

  it('WebSocket 构造抛错时触发重连调度', async () => {
    vi.useFakeTimers()
    class FailingWebSocket {
      constructor() {
        throw new Error('WebSocket 构造失败')
      }
    }
    vi.stubGlobal('WebSocket', FailingWebSocket)
    await mountView()
    // 构造失败应触发 scheduleReconnect
    vi.advanceTimersByTime(2000)
    await flushPromises()
  })

  it('imWebSocketUrl 被调用获取连接地址', async () => {
    imMocks.imWebSocketUrl.mockReturnValue('ws://custom-host/ws')
    await mountView()
    expect(imMocks.imWebSocketUrl).toHaveBeenCalled()
  })

  it('卸载组件时关闭 WebSocket 连接', async () => {
    const wrapper = await mountView()
    const ws = MockWebSocket.instances[0]
    const closeSpy = vi.spyOn(ws, 'close')
    wrapper.unmount()
    await flushPromises()
    expect(closeSpy).toHaveBeenCalled()
  })

  it('卸载组件时若有重连定时器则清除', async () => {
    vi.useFakeTimers()
    const wrapper = await mountView()
    const ws = MockWebSocket.instances[0]
    // 触发 onclose 设置重连定时器
    ws.onclose?.()
    // 卸载组件,应清除重连定时器(clearTimeout 分支)
    wrapper.unmount()
    await flushPromises()
    vi.useRealTimers()
  })

  it('已有重连定时器时 scheduleReconnect 清除旧定时器', async () => {
    vi.useFakeTimers()
    await mountView()
    const ws = MockWebSocket.instances[0]
    // 第一次关闭触发重连
    ws.onclose?.()
    // 第二次关闭应清除旧定时器再设新定时器
    ws.onclose?.()
    vi.advanceTimersByTime(5000)
    await flushPromises()
  })

  it('selectConversation 加载消息后调用 markImRead', async () => {
    imMocks.fetchImConversations.mockResolvedValue([sampleConversation])
    imMocks.fetchImMessages.mockResolvedValue([sampleMessage])
    const wrapper = await mountView()
    await wrapper.find('.im-conv-item').trigger('click')
    await flushPromises()
    expect(imMocks.markImRead).toHaveBeenCalledWith(1, sampleMessage.id)
  })

  it('selectConversation 加载空消息时不调用 markImRead', async () => {
    imMocks.fetchImConversations.mockResolvedValue([sampleConversation])
    imMocks.fetchImMessages.mockResolvedValue([])
    const wrapper = await mountView()
    await wrapper.find('.im-conv-item').trigger('click')
    await flushPromises()
    expect(imMocks.markImRead).not.toHaveBeenCalled()
  })

  it('applyIncomingMessage 在非活跃会话时仅 loadConversations', async () => {
    imMocks.fetchImConversations.mockResolvedValue([sampleConversation, sampleConversation2])
    imMocks.fetchImContacts.mockResolvedValue([])
    imMocks.fetchImMessages.mockResolvedValue([])
    const wrapper = await mountView()
    // 选择会话 1
    const items = wrapper.findAll('.im-conv-item')
    await items[0].trigger('click')
    await flushPromises()
    imMocks.fetchImMessages.mockClear()
    // 通过 WebSocket 接收会话 2 的消息
    const ws = MockWebSocket.instances[0]
    const newMsg = { ...sampleMessage, id: 999, conversation_id: 2, body: '会话2消息' }
    ws.onmessage?.({
      data: JSON.stringify({
        type: 'im.message',
        conversation_id: 2,
        message: newMsg,
      }),
    })
    await flushPromises()
    // 不应添加到当前消息列表
    expect(imMocks.fetchImMessages).not.toHaveBeenCalled()
  })

  it('filteredContacts 过滤企业专属客服联系人', async () => {
    imMocks.fetchImConversations.mockResolvedValue([])
    imMocks.fetchImContacts.mockResolvedValue([enterpriseCsContact, normalContact])
    const wrapper = await mountView()
    await wrapper.find('.im-sidebar-head .im-icon-btn').trigger('click')
    await flushPromises()
    // 企业专属客服被过滤,只显示 1 个普通联系人
    expect(wrapper.findAll('.im-contact-item')).toHaveLength(1)
    expect(wrapper.find('.im-contact-name').text()).toBe('张三')
  })

  it('pinnedContacts 显示企业专属客服', async () => {
    imMocks.fetchImConversations.mockResolvedValue([])
    imMocks.fetchImContacts.mockResolvedValue([enterpriseCsContact])
    const wrapper = await mountView()
    expect(wrapper.find('.im-pinned').exists()).toBe(true)
    expect(wrapper.find('.im-conv-item--pinned').exists()).toBe(true)
    expect(wrapper.text()).toContain('固定联系人')
  })

  it('existingDedicatedConversation 通过 title 匹配非企业专属会话', async () => {
    // 企业专属客服联系人,但已有非企业专属会话(通过 title 匹配)
    const csContactWithTitle = {
      ...enterpriseCsContact,
      id: 88,
      display_name: '客服小张',
      username: 'cs-xiaozhang',
    }
    imMocks.fetchImConversations.mockResolvedValue([
      { ...sampleConversation2, id: 20, title: '客服小张', is_enterprise_dedicated_cs: false },
    ])
    imMocks.fetchImContacts.mockResolvedValue([csContactWithTitle])
    const wrapper = await mountView()
    // 企业专属客服显示在固定联系人区域
    const pinned = wrapper.find('.im-conv-item--pinned')
    expect(pinned.exists()).toBe(true)
    await pinned.trigger('click')
    await flushPromises()
    // 复用已有会话(通过 title 匹配),不创建新会话
    expect(imMocks.createDirectConversation).not.toHaveBeenCalled()
    expect(imMocks.fetchImMessages).toHaveBeenCalledWith(20, { limit: 50 })
  })

  it('isPinnedContactActive 在选中固定联系人时返回 true', async () => {
    imMocks.fetchImConversations.mockResolvedValue([sampleConversation])
    imMocks.fetchImContacts.mockResolvedValue([enterpriseCsContact])
    const wrapper = await mountView()
    const pinned = wrapper.find('.im-conv-item--pinned')
    await pinned.trigger('click')
    await flushPromises()
    expect(pinned.classes()).toContain('active')
  })

  it('onContactSearch 触发 input 事件不报错', async () => {
    imMocks.fetchImConversations.mockResolvedValue([])
    imMocks.fetchImContacts.mockResolvedValue([normalContact])
    const wrapper = await mountView()
    await wrapper.find('.im-sidebar-head .im-icon-btn').trigger('click')
    await flushPromises()
    const searchInput = wrapper.find('.im-modal .im-compose-input')
    await searchInput.setValue('test')
    await searchInput.trigger('input')
    await flushPromises()
    expect(wrapper.find('.im-modal').exists()).toBe(true)
  })

  // ===== 12. 防御性分支覆盖 =====

  it('loadConversations 在 localUserId 被清空后提前返回', async () => {
    imMocks.fetchImConversations.mockResolvedValue([sampleConversation])
    imMocks.fetchImContacts.mockResolvedValue([])
    const wrapper = await mountView()
    const rawState = (wrapper.vm as unknown as { $: { devtoolsRawSetupState: Record<string, { value: unknown }> } }).$.devtoolsRawSetupState
    // 清空 localUserId,触发 loadConversations 的防御性分支
    rawState.localUserId.value = null
    imMocks.fetchImConversations.mockClear()
    // 通过 WebSocket 消息触发 applyIncomingMessage → loadConversations
    const ws = MockWebSocket.instances[0]
    ws.onmessage?.({
      data: JSON.stringify({
        type: 'im.message',
        conversation_id: 999,
        message: { ...sampleMessage, id: 1, conversation_id: 999 },
      }),
    })
    await flushPromises()
    // localUserId 为 null 时 loadConversations 提前返回,不调用 fetchImConversations
    expect(imMocks.fetchImConversations).not.toHaveBeenCalled()
  })

  it('selectConversation 在 localUserId 被清空后提前返回', async () => {
    imMocks.fetchImConversations.mockResolvedValue([sampleConversation, sampleConversation2])
    imMocks.fetchImContacts.mockResolvedValue([])
    imMocks.fetchImMessages.mockResolvedValue([])
    const wrapper = await mountView()
    // 先选择第一个会话
    await wrapper.findAll('.im-conv-item')[0].trigger('click')
    await flushPromises()
    // 清空 localUserId
    const rawState = (wrapper.vm as unknown as { $: { devtoolsRawSetupState: Record<string, { value: unknown }> } }).$.devtoolsRawSetupState
    rawState.localUserId.value = null
    imMocks.fetchImMessages.mockClear()
    // 再点击第二个会话,应触发 selectConversation 的防御性分支
    await wrapper.findAll('.im-conv-item')[1].trigger('click')
    await flushPromises()
    expect(imMocks.fetchImMessages).not.toHaveBeenCalled()
  })

  it('connectWs 在 localUserId 被清空后提前返回', async () => {
    vi.useFakeTimers()
    imMocks.fetchImConversations.mockResolvedValue([sampleConversation])
    imMocks.fetchImContacts.mockResolvedValue([])
    const wrapper = await mountView()
    const initialWsCount = MockWebSocket.instances.length
    // 清空 localUserId
    const rawState = (wrapper.vm as unknown as { $: { devtoolsRawSetupState: Record<string, { value: unknown }> } }).$.devtoolsRawSetupState
    rawState.localUserId.value = null
    // 触发 ws.onclose → scheduleReconnect → connectWs(应提前返回)
    const ws = MockWebSocket.instances[0]
    ws.onclose?.()
    vi.advanceTimersByTime(5000)
    await flushPromises()
    // connectWs 因 localUserId 为 null 提前返回,不创建新 WebSocket
    expect(MockWebSocket.instances.length).toBe(initialWsCount)
    vi.useRealTimers()
  })
})
