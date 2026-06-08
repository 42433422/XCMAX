import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import { setActivePinia, createPinia } from 'pinia'
import LoginView from './LoginView.vue'

vi.mock('@/stores/auth', () => ({
  useAuthStore: vi.fn(() => ({
    loginWithPassword: vi.fn(),
  })),
}))

vi.mock('@/authPaths', () => ({
  pickRedirectFromRoute: vi.fn(() => '/'),
}))

describe('LoginView', () => {
  let router: ReturnType<typeof createRouter>

  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', name: 'home', component: { template: '<div />' } },
        { path: '/login', name: 'login', component: { template: '<div />' } },
        { path: '/login-email', name: 'login-email', component: { template: '<div />' } },
        { path: '/forgot-password', name: 'forgot-password', component: { template: '<div />' } },
        { path: '/register', name: 'register', component: { template: '<div />' } },
      ],
    })
  })

  it('renders login form', async () => {
    router.push('/login')
    await router.isReady()

    const wrapper = mount(LoginView, {
      global: { plugins: [router] },
    })

    expect(wrapper.text()).toContain('登录')
    expect(wrapper.find('input[autocomplete="username"]').exists()).toBe(true)
    expect(wrapper.find('input[type="password"]').exists()).toBe(true)
    expect(wrapper.find('button[type="submit"]').exists()).toBe(true)
  })

  it('renders footer links', async () => {
    router.push('/login')
    await router.isReady()

    const wrapper = mount(LoginView, {
      global: { plugins: [router] },
    })

    expect(wrapper.text()).toContain('邮箱验证码登录')
    expect(wrapper.text()).toContain('忘记密码')
    expect(wrapper.text()).toContain('注册')
  })

  it('disables submit button while loading', async () => {
    router.push('/login')
    await router.isReady()

    const wrapper = mount(LoginView, {
      global: { plugins: [router] },
    })

    const button = wrapper.find('button[type="submit"]')
    expect(button.element.disabled).toBe(false)
  })
})
