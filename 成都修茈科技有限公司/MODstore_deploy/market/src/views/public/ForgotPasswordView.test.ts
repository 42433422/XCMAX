import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import ForgotPasswordView from './ForgotPasswordView.vue'

vi.mock('@/api', () => ({
  api: {
    sendResetPasswordCode: vi.fn(),
    resetPassword: vi.fn(),
  },
}))

describe('ForgotPasswordView', () => {
  let router: ReturnType<typeof createRouter>

  beforeEach(() => {
    vi.clearAllMocks()
    router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/forgot-password', name: 'forgot-password', component: { template: '<div />' } },
        { path: '/login', name: 'login', component: { template: '<div />' } },
      ],
    })
  })

  it('renders forgot password form step 1', async () => {
    router.push('/forgot-password')
    await router.isReady()

    const wrapper = mount(ForgotPasswordView, {
      global: { plugins: [router] },
    })

    expect(wrapper.text()).toContain('忘记密码')
    expect(wrapper.text()).toContain('注册邮箱')
    expect(wrapper.text()).toContain('发送验证码')
  })

  it('renders login link', async () => {
    router.push('/forgot-password')
    await router.isReady()

    const wrapper = mount(ForgotPasswordView, {
      global: { plugins: [router] },
    })

    expect(wrapper.text()).toContain('返回登录')
  })
})
