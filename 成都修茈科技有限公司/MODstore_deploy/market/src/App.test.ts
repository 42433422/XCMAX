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

import { api } from './api'

const Stub = { template: '<div class="stub-view" />' }

function createTestRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'home', component: Stub },
      { path: '/workbench/home', name: 'workbench-home', component: Stub },
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
    setActivePinia(createPinia())
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
})
