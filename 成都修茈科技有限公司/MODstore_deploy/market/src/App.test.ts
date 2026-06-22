import { mount, flushPromises } from '@vue/test-utils'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import App from './App.vue'
import { createModstoreI18n } from './i18n'
import { ACCESS_TOKEN_KEY } from './infrastructure/storage/tokenStore'

vi.mock('./realtimeClient', () => ({
  connectRealtime: vi.fn(),
  disconnectRealtime: vi.fn(),
}))

vi.mock('./api', () => ({
  api: {
    me: vi.fn(),
    balance: vi.fn(),
    walletAdminSelfCredit: vi.fn(),
    verifyAdminDigestCode: vi.fn(),
    notificationsList: vi.fn(),
    paymentMyPlan: vi.fn(),
    listButlerSkills: vi.fn().mockResolvedValue([]),
    agentButlerChat: vi.fn().mockResolvedValue({ text: '', tool_calls: [], conversation_id: null }),
  },
  clearAuthTokens: vi.fn(),
}))

vi.mock('./components/floating-agent/FloatingAgentRoot.vue', () => ({
  default: { template: '<div class="butler-stub" />' },
}))

vi.mock('./composables/asr/micPreflight', () => ({
  requestMicInUserGesture: vi.fn(),
}))

vi.mock('./composables/useDangerConfirm', () => ({
  confirmDanger: vi.fn(async () => true),
  resolveDangerConfirm: vi.fn(),
  useDangerConfirmState: () => ({
    open: { value: false },
    options: { value: {} },
  }),
}))

import { api } from './api'

const Stub = { template: '<div class="stub-view" />' }

function createTestRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'home', component: Stub },
      { path: '/about', name: 'about', component: Stub },
      { path: '/workbench/home', name: 'workbench-home', component: Stub },
      { path: '/workbench/mod/:id?', name: 'workbench-mod', component: Stub },
      { path: '/plans', name: 'plans', component: Stub },
      { path: '/ai-store', name: 'ai-store', component: Stub },
      { path: '/wallet', name: 'wallet', component: Stub },
      { path: '/customer-service', name: 'customer-service', component: Stub },
      { path: '/notifications', name: 'notifications', component: Stub },
      { path: '/account', name: 'account', component: Stub },
      { path: '/login', name: 'login', component: Stub },
      { path: '/register', name: 'register', component: Stub },
      { path: '/admin/database', name: 'admin-database', component: Stub },
      { path: '/admin/customer-service', name: 'admin-customer-service', component: Stub },
      { path: '/admin/butler-skills', name: 'admin-butler-skills', component: Stub },
      { path: '/admin/duty-employees', name: 'admin-duty-employees', component: Stub },
      { path: '/admin/employee-autonomy', name: 'admin-employee-autonomy', component: Stub },
      { path: '/admin/ops-terminal', name: 'admin-ops-terminal', component: Stub },
      {
        path: '/ai-test',
        component: Stub,
        children: [
          { path: '', redirect: { name: 'ai-test-sandbox' } },
          { path: 'sandbox', name: 'ai-test-sandbox', component: Stub },
          { path: 'exam', name: 'ai-test-exam', component: Stub },
        ],
      },
      { path: '/sandbox', name: 'sandbox', redirect: { name: 'ai-test-sandbox' } },
      { path: '/recharge', name: 'recharge', component: Stub },
      { path: '/workbench/shell/:target?/:id?', name: 'workbench-shell', component: Stub },
    ],
  })
}

describe('App shell', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setActivePinia(createPinia())
    Object.defineProperty(window, 'matchMedia', {
      configurable: true,
      writable: true,
      value: vi.fn().mockImplementation(() => ({
        matches: false,
        media: '',
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    })
    delete (window as Window & { __XCAGI_CLIENT__?: string }).__XCAGI_CLIENT__
    document.documentElement.classList.remove('xcagi-client-android', 'xcagi-embedded-android')
    vi.mocked(api.me).mockResolvedValue({
      id: 1,
      username: 'admin',
      is_admin: true,
    })
    vi.mocked(api.balance).mockResolvedValue({ balance: 10 })
    vi.mocked(api.notificationsList).mockResolvedValue({ items: [], unread_count: 0 })
    vi.mocked(api.paymentMyPlan).mockResolvedValue({
      plan: null,
      membership: { tier: 'free', label: '普通用户', is_member: false },
    })
    localStorage.setItem(ACCESS_TOKEN_KEY, 'tok')
  })

  it('renders main navigation with landmark and client nav labels', async () => {
    const router = createTestRouter()
    const pinia = createPinia()
    const wrapper = mount(App, {
      global: {
        plugins: [pinia, router, createModstoreI18n('zh-CN')],
        stubs: { RouterView: { template: '<div class="rv" />' } },
      },
    })

    await router.isReady()
    await router.push('/plans')
    await flushPromises()

    const nav = wrapper.get('.navbar')
    expect(nav.attributes('role')).toBe('navigation')
    expect(nav.attributes('aria-label')).toBe('主导航')
    expect(wrapper.text()).toContain('工作台')
    expect(wrapper.text()).toContain('会员')
    expect(wrapper.text()).toContain('AI 客服')
    expect(wrapper.text()).toContain('AI 测试')
    expect(wrapper.text()).toContain('¥10.00')
    expect(wrapper.find('.nav-self-credit-btn').exists()).toBe(true)
  })

  it('switches to admin mode and shows admin customer service link', async () => {
    const router = createTestRouter()
    const pinia = createPinia()
    setActivePinia(pinia)
    const wrapper = mount(App, {
      global: {
        plugins: [pinia, router, createModstoreI18n('zh-CN')],
        stubs: { RouterView: { template: '<div class="rv" />' } },
      },
    })

    await router.isReady()
    await router.push('/plans')
    await flushPromises()

    const { useAuthStore } = await import('./stores/auth')
    useAuthStore().setAdminDigestUnlock(new Date(Date.now() + 60_000).toISOString())
    await flushPromises()

    const adminTab = wrapper.findAll('button.mode-tab').find((w) => w.text() === '管理端')
    expect(adminTab).toBeTruthy()
    await adminTab!.trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.name).toBe('admin-database')
    expect(wrapper.text()).toContain('AI 客服后台')
  })

  it('drives shell modals, admin unlock, sidebar mode, and conversation gestures', async () => {
    vi.mocked(api.walletAdminSelfCredit).mockResolvedValue({ ok: true })
    vi.mocked(api.verifyAdminDigestCode).mockResolvedValue({ ok: true, expires_at: new Date(Date.now() + 60_000).toISOString() })

    const router = createTestRouter()
    const pinia = createPinia()
    setActivePinia(pinia)
    const wrapper = mount(App, {
      global: {
        plugins: [pinia, router, createModstoreI18n('zh-CN')],
        stubs: { RouterView: { template: '<div class="rv" />' } },
      },
    })

    await router.isReady()
    await router.push('/workbench/home')
    await flushPromises()

    const { useWorkbenchSidebarStore } = await import('./stores/workbenchSidebar')
    const wbSidebar = useWorkbenchSidebarStore()
    wbSidebar.setConversations([
      { id: 'c1', title: '第一轮', updatedAt: Date.now(), messages: [] },
      { id: 'c2', title: '第二轮', updatedAt: Date.now() - 120_000, messages: [] },
    ])
    wbSidebar.setActiveConversationId('c1')
    await wrapper.vm.$nextTick()

    const vm = wrapper.vm as any
    expect(vm.formatConvTime(Date.now())).toBe('刚刚')
    expect(vm.formatConvTime(Date.now() - 90_000)).toContain('分钟前')
    expect(vm.formatConvTime(Date.now() - 3_600_000 * 2)).toContain('小时前')
    expect(vm.formatConvTime(Date.now() - 86_400_000 * 2)).toContain('天前')
    expect(vm.formatConvTime(Date.now() - 8 * 86_400_000)).toContain('/')

    vm.openSelfCreditModal()
    expect(vm.selfCreditOpen).toBe(true)
    vm.selfCreditAmount = '0'
    await vm.submitSelfCredit()
    expect(vm.selfCreditErr).toBeTruthy()
    vm.selfCreditBusy = true
    vm.closeSelfCreditModal()
    expect(vm.selfCreditOpen).toBe(true)
    vm.selfCreditBusy = false
    vm.selfCreditAmount = '12.50'
    vm.selfCreditNote = '测试补额'
    await vm.submitSelfCredit()
    expect(api.walletAdminSelfCredit).toHaveBeenCalledWith(12.5, '测试补额')
    expect(vm.selfCreditOpen).toBe(false)

    vm.enterAdminRoute('admin-customer-service')
    expect(vm.adminUnlockOpen).toBe(true)
    vm.adminUnlockCode = 'bad'
    await vm.submitAdminUnlock()
    expect(vm.adminUnlockErr).toContain('6 位')
    vi.mocked(api.verifyAdminDigestCode).mockResolvedValueOnce({ ok: false })
    vm.adminUnlockCode = 'a 5 0 6 e 7'
    vm.onAdminUnlockInputBlur()
    expect(vm.adminUnlockCode).toBe('A506E7')
    await vm.submitAdminUnlock()
    expect(vm.adminUnlockErr).toContain('校验失败')
    vi.mocked(api.verifyAdminDigestCode).mockResolvedValueOnce({ ok: true, expires_at: new Date(Date.now() + 60_000).toISOString() })
    vm.adminUnlockCode = 'A506E7'
    await vm.submitAdminUnlock()
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('admin-customer-service')

    vm.handleModeClick('voice')
    await flushPromises()
    expect(wbSidebar.activeMode).toBe('voice')
    expect(router.currentRoute.value.name).toBe('workbench-home')

    const dispatchSpy = vi.spyOn(window, 'dispatchEvent')
    vm.handleNewChat()
    vm.handleSidebarSettings()
    expect(dispatchSpy).toHaveBeenCalled()

    vm.onConvTouchStart({ touches: [{ clientX: 120 }] }, 'c1')
    vm.onConvTouchMove({ touches: [{ clientX: 20 }] }, 'c1')
    vm.onConvTouchEnd('c1')
    expect(vm.convSwipeOffset.c1).toBe(56)
    vm.handlePickConversation('c1')
    expect(vm.convJustSwiped).toBe(false)
    vm.handlePickConversation('c1')
    expect(vm.convSwipeOffset.c1).toBe(0)
    vm.handlePickConversation('c2')
    expect(wbSidebar.activeConversationId).toBe('c2')

    vm.onConvMouseDown({ clientX: 120 }, 'c2')
    vm.onConvMouseMove({ clientX: 40 })
    vm.onConvMouseUp()
    expect(vm.convSwipeOffset.c2).toBe(56)

    await vm.doLogout()
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('login')

    wrapper.unmount()
  })

  it('covers mobile shell controls, client switching, and conversation deletion boundaries', async () => {
    vi.mocked(window.matchMedia).mockImplementation(() => ({
      matches: true,
      media: '(max-width: 768px)',
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }))
    const { confirmDanger } = await import('./composables/useDangerConfirm')
    const router = createTestRouter()
    const pinia = createPinia()
    setActivePinia(pinia)
    const wrapper = mount(App, {
      global: {
        plugins: [pinia, router, createModstoreI18n('zh-CN')],
        stubs: { RouterView: { template: '<div class="rv" />' } },
      },
    })

    await router.isReady()
    await router.push('/workbench/home')
    await flushPromises()

    const { useAuthStore } = await import('./stores/auth')
    const { useWorkbenchSidebarStore } = await import('./stores/workbenchSidebar')
    const authStore = useAuthStore()
    const wbSidebar = useWorkbenchSidebarStore()
    authStore.setAdminDigestUnlock(new Date(Date.now() + 60_000).toISOString())
    wbSidebar.setConversations([
      { id: 'c1', title: '第一轮', updatedAt: Date.now(), messages: [] },
      { id: 'c2', title: '', updatedAt: Date.now() - 10_000, messages: [] },
    ])
    wbSidebar.setActiveConversationId('c1')
    await wrapper.vm.$nextTick()

    const vm = wrapper.vm as any
    expect(vm.wbSidebarWidthCss).toBe('0px')
    await wrapper.get('.wb-mobile-hamburger').trigger('click')
    expect(wbSidebar.mobileOpen).toBe(true)
    await wrapper.get('.wb-mobile-overlay').trigger('click')
    expect(wbSidebar.mobileOpen).toBe(false)
    wbSidebar.mobileOpen = true
    await wrapper.vm.$nextTick()
    await wrapper.get('.wb-sidebar-toggle').trigger('click')
    expect(wbSidebar.mobileOpen).toBe(false)

    vm.currentMode = 'admin'
    vm.switchMode('client')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('workbench-home')
    expect(vm.currentMode).toBe('client')

    await wrapper.get('.wb-sidebar-conv-item').trigger('click')
    await wrapper.get('.wb-sidebar-conv-item').trigger('touchstart', { touches: [{ clientX: 100 }] })
    await wrapper.get('.wb-sidebar-conv-item').trigger('touchmove', { touches: [{ clientX: 90 }] })
    await wrapper.get('.wb-sidebar-conv-item').trigger('touchend')
    expect(vm.convSwipeOffset.c1).toBe(0)
    await wrapper.get('.wb-sidebar-conv-item').trigger('mousedown', { clientX: 120 })
    vm.onConvMouseMove({ clientX: 116 })
    vm.onConvMouseUp()
    expect(vm.convSwipeOffset.c1).toBe(0)
    vm.onConvMouseMove({ clientX: 20 })
    vm.onConvMouseUp()

    vm.convSwipeOffset.c2 = 12
    vm.handlePickConversation('c1')
    expect(vm.convSwipeOffset.c2).toBe(0)
    vi.mocked(confirmDanger).mockResolvedValueOnce(false)
    await vm.confirmRemoveConversation('missing')
    expect(wbSidebar.conversations).toHaveLength(2)
    vi.mocked(confirmDanger).mockResolvedValueOnce(true)
    await wrapper.get('.wb-sidebar-conv-delete').trigger('click')
    expect(wbSidebar.conversations.some((c) => c.id === 'c1')).toBe(false)

    wrapper.unmount()
  })

  it('covers android embedded shell, ai-test route state, and idle refresh scheduling', async () => {
    ;(window as Window & { __XCAGI_CLIENT__?: string }).__XCAGI_CLIENT__ = 'android'
    document.documentElement.classList.add('xcagi-embedded-android')
    const idleCallbacks: Array<() => void> = []
    const originalRequestIdleCallback = window.requestIdleCallback
    const originalCancelIdleCallback = window.cancelIdleCallback
    Object.assign(window, {
      requestIdleCallback: vi.fn((cb: () => void) => {
        idleCallbacks.push(cb)
        return idleCallbacks.length
      }),
      cancelIdleCallback: vi.fn(),
    })
    const nowSpy = vi.spyOn(Date, 'now').mockReturnValue(1000)
    const router = createTestRouter()
    const pinia = createPinia()
    setActivePinia(pinia)
    const wrapper = mount(App, {
      global: {
        plugins: [pinia, router, createModstoreI18n('zh-CN')],
        stubs: { RouterView: { template: '<div class="rv" />' } },
      },
    })

    await router.isReady()
    await router.push('/workbench/mod/demo?embedded=android')
    await flushPromises()

    const vm = wrapper.vm as any
    expect(vm.isAndroidEmbeddedShell).toBe(true)
    expect(vm.wbSidebarWidthCss).toBe('0px')
    expect(vm.shouldShowButler).toBe(false)

    await router.push('/ai-test/exam')
    await flushPromises()
    expect(vm.isAiTestRoute).toBe(true)

    vm._scheduleGlobalRefresh()
    idleCallbacks.splice(0).forEach((cb) => cb())
    await flushPromises()
    vm._scheduleGlobalRefresh()
    expect(window.requestIdleCallback).toHaveBeenCalled()

    nowSpy.mockRestore()
    Object.assign(window, {
      requestIdleCallback: originalRequestIdleCallback,
      cancelIdleCallback: originalCancelIdleCallback,
    })
    wrapper.unmount()
  })

  it('covers async error branches and off-home workbench shell actions', async () => {
    const { confirmDanger } = await import('./composables/useDangerConfirm')
    const { connectRealtime } = await import('./realtimeClient')
    vi.mocked(api.walletAdminSelfCredit).mockRejectedValueOnce(new Error('credit failed'))
    vi.mocked(api.verifyAdminDigestCode).mockRejectedValueOnce(new Error('身份码无效'))

    const router = createTestRouter()
    const pinia = createPinia()
    setActivePinia(pinia)
    const wrapper = mount(App, {
      global: {
        plugins: [pinia, router, createModstoreI18n('zh-CN')],
        stubs: { RouterView: { template: '<div class="rv" />' } },
      },
    })

    await router.isReady()
    await router.push('/plans')
    await flushPromises()

    const vm = wrapper.vm as any
    vm.openSelfCreditModal()
    vm.selfCreditAmount = '6'
    await vm.submitSelfCredit()
    expect(vm.selfCreditErr).toBe('credit failed')

    vm.openAdminUnlockModal()
    vm.adminUnlockCode = 'A506E7'
    await vm.submitAdminUnlock()
    expect(vm.adminUnlockErr).toContain('API 源一致')
    vm.adminUnlockBusy = true
    vm.pendingAdminRouteName = 'admin-database'
    vm.closeAdminUnlockModal()
    expect(vm.adminUnlockOpen).toBe(false)
    expect(vm.pendingAdminRouteName).toBeNull()

    const dispatchSpy = vi.spyOn(window, 'dispatchEvent')
    vm.handleSidebarSettings()
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('workbench-home')
    expect(dispatchSpy).toHaveBeenCalled()
    await router.push('/plans')
    vm.handleNewChat()
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('workbench-home')
    await router.push('/plans')
    vm.handleModeClick('make')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('workbench-home')
    dispatchSpy.mockRestore()

    const failingDispatch = vi.spyOn(window, 'dispatchEvent').mockImplementation(() => {
      throw new Error('dispatch failed')
    })
    const legacyEvent = { initCustomEvent: vi.fn() }
    const createEventSpy = vi.spyOn(document, 'createEvent').mockReturnValue(legacyEvent as any)
    vm.emitWorkbenchModeSwitch('direct')
    expect(createEventSpy).toHaveBeenCalledWith('CustomEvent')
    expect(legacyEvent.initCustomEvent).toHaveBeenCalled()
    failingDispatch.mockRestore()
    createEventSpy.mockRestore()

    const connectCallback = vi.mocked(connectRealtime).mock.calls.find(([cb]) => typeof cb === 'function')?.[0] as
      | (() => void)
      | undefined
    connectCallback?.()
    vi.mocked(confirmDanger).mockResolvedValueOnce(false)
    await vm.doLogout()
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('workbench-home')

    wrapper.unmount()
  })
})
