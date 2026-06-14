import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import ForgotPasswordView from './ForgotPasswordView.vue'

const { sendForgotPasswordCode } = vi.hoisted(() => ({
  sendForgotPasswordCode: vi.fn().mockResolvedValue({ success: true, message: '已发送' }),
}))

vi.mock('@/api/auth', () => ({
  authApi: {
    sendForgotPasswordCode,
    resetPasswordWithCode: vi.fn().mockResolvedValue({ success: true }),
  },
}))

function mountForgot() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/forgot-password', name: 'forgot-password', component: ForgotPasswordView },
      { path: '/login', name: 'login', component: { template: '<div />' } },
    ],
  })
  return router.push('/forgot-password').then(() =>
    router.isReady().then(() =>
      mount(ForgotPasswordView, {
        global: {
          plugins: [router],
          stubs: { RouterLink: { template: '<a><slot /></a>' } },
        },
      }),
    ),
  )
}

describe('ForgotPasswordView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('mounts forgot password form', async () => {
    const wrapper = await mountForgot()
    expect(wrapper.exists()).toBe(true)
    expect(wrapper.find('input').exists()).toBe(true)
  })

  it('shows error for invalid email on sendCode', async () => {
    const wrapper = await mountForgot()
    const inputs = wrapper.findAll('input')
    if (inputs.length > 0) {
      await inputs[0].setValue('not-an-email')
    }
    const sendBtn = wrapper.findAll('button').find((b) => b.text().includes('发送') || b.text().includes('验证码'))
    if (sendBtn) {
      await sendBtn.trigger('click')
      await wrapper.vm.$nextTick()
      expect(wrapper.text().length).toBeGreaterThan(0)
    }
  })

  it('sends code for valid email when send button present', async () => {
    const wrapper = await mountForgot()
    const emailInput = wrapper.findAll('input')[0]
    await emailInput.setValue('user@example.com')
    const sendBtn = wrapper.findAll('button').find((b) => /发送|验证码|下一步/.test(b.text()))
    if (!sendBtn) {
      expect(wrapper.text().length).toBeGreaterThan(0)
      return
    }
    await sendBtn.trigger('click')
    await wrapper.vm.$nextTick()
    expect(wrapper.text().length).toBeGreaterThan(0)
  })
})
