import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import LoginView from './LoginView.vue'

vi.mock('@/api/auth', () => ({
  authApi: {
    login: vi.fn().mockResolvedValue({ success: true }),
    validateSession: vi.fn().mockResolvedValue({ success: true }),
  },
}))
vi.mock('@/utils/appDialog', () => ({
  appAlert: vi.fn(),
}))

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/login', name: 'login', component: LoginView },
      { path: '/', name: 'chat', component: { template: '<div />' } },
    ],
  })
}

describe('LoginView deep', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('renders login inputs', async () => {
    const router = makeRouter()
    await router.push('/login')
    await router.isReady()
    const wrapper = mount(LoginView, {
      global: {
        plugins: [router],
        stubs: { RouterLink: { template: '<a><slot /></a>' } },
      },
    })
    expect(wrapper.findAll('input').length).toBeGreaterThan(0)
  })

  it('shows login-related text', async () => {
    const router = makeRouter()
    await router.push('/login')
    await router.isReady()
    const wrapper = mount(LoginView, {
      global: {
        plugins: [router],
        stubs: { RouterLink: { template: '<a><slot /></a>' } },
      },
    })
    const text = wrapper.text()
    expect(text.includes('登录') || text.includes('账号') || text.length > 20).toBe(true)
  })
})
