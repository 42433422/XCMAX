import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import { ApiError } from '@/api'

const flushPromises = () => new Promise<void>((resolve) => setTimeout(resolve, 0))

const { sendForgotPasswordCode, resetForgotPassword } = vi.hoisted(() => ({
  sendForgotPasswordCode: vi.fn(),
  resetForgotPassword: vi.fn(),
}))

vi.mock('@/api/auth', () => ({
  authApi: {
    sendForgotPasswordCode,
    resetForgotPassword,
  },
}))

import ForgotPasswordView from './ForgotPasswordView.vue'

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/forgot-password', name: 'forgot-password', component: ForgotPasswordView },
      { path: '/login', name: 'login', component: { template: '<div />' } },
      { path: '/login-forgot-account', name: 'login-forgot-account', component: { template: '<div />' } },
    ],
  })
}

async function mountView() {
  const router = makeRouter()
  await router.push('/forgot-password')
  await router.isReady()
  const wrapper = mount(ForgotPasswordView, {
    global: {
      plugins: [router],
      stubs: { RouterLink: { template: '<a><slot /></a>' } },
    },
  })
  return { wrapper, router }
}

describe('ForgotPasswordView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('renders step 1 form by default', async () => {
    const { wrapper } = await mountView()
    expect(wrapper.find('.login-heading').text()).toBe('忘记密码')
    expect(wrapper.find('input[type="email"]').exists()).toBe(true)
    const submitBtn = wrapper.find('.login-submit')
    expect(submitBtn.text()).toContain('获取验证码')
  })

  it('disables submit button when email is empty', async () => {
    const { wrapper } = await mountView()
    const submitBtn = wrapper.find('.login-submit')
    expect(submitBtn.attributes('disabled')).toBeDefined()
  })

  it('shows error for invalid email without @', async () => {
    const { wrapper } = await mountView()
    await wrapper.find('input[type="email"]').setValue('not-an-email')
    await wrapper.find('.login-form').trigger('submit')
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.login-error').text()).toBe('请填写有效邮箱')
    expect(sendForgotPasswordCode).not.toHaveBeenCalled()
  })

  it('shows error for empty email', async () => {
    const { wrapper } = await mountView()
    await wrapper.find('input[type="email"]').setValue('   ')
    await wrapper.find('.login-form').trigger('submit')
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.login-error').text()).toBe('请填写有效邮箱')
  })

  it('sends code successfully and moves to step 2', async () => {
    sendForgotPasswordCode.mockResolvedValue({ success: true, message: '验证码已发送' })
    const { wrapper } = await mountView()
    await wrapper.find('input[type="email"]').setValue('user@example.com')
    await wrapper.find('.login-form').trigger('submit')
    await flushPromises()
    await wrapper.vm.$nextTick()
    expect(sendForgotPasswordCode).toHaveBeenCalledWith('user@example.com')
    expect(wrapper.find('.login-success').text()).toContain('验证码已发送')
    // Step 2: should show code input and password fields
    expect(wrapper.find('input[autocomplete="one-time-code"]').exists()).toBe(true)
    expect(wrapper.find('input[autocomplete="new-password"]').exists()).toBe(true)
  })

  it('shows default info message when API returns no message', async () => {
    sendForgotPasswordCode.mockResolvedValue({ success: true })
    const { wrapper } = await mountView()
    await wrapper.find('input[type="email"]').setValue('user@example.com')
    await wrapper.find('.login-form').trigger('submit')
    await flushPromises()
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.login-success').text()).toContain('若该邮箱已注册')
  })

  it('handles ApiError on sendCode', async () => {
    const apiError = new ApiError('邮箱不存在', 404, {
      message: '邮箱未注册',
    })
    sendForgotPasswordCode.mockRejectedValue(apiError)
    const { wrapper } = await mountView()
    await wrapper.find('input[type="email"]').setValue('unknown@example.com')
    await wrapper.find('.login-form').trigger('submit')
    await flushPromises()
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.login-error').text()).toContain('邮箱未注册')
  })

  it('handles ApiError with nested error object', async () => {
    const apiError = new ApiError('fail', 400, {
      error: { message: '验证码发送频率过高' },
    })
    sendForgotPasswordCode.mockRejectedValue(apiError)
    const { wrapper } = await mountView()
    await wrapper.find('input[type="email"]').setValue('user@example.com')
    await wrapper.find('.login-form').trigger('submit')
    await flushPromises()
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.login-error').text()).toContain('验证码发送频率过高')
  })

  it('handles generic error on sendCode', async () => {
    sendForgotPasswordCode.mockRejectedValue(new Error('network'))
    const { wrapper } = await mountView()
    await wrapper.find('input[type="email"]').setValue('user@example.com')
    await wrapper.find('.login-form').trigger('submit')
    await flushPromises()
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.login-error').text()).toContain('发送失败')
    expect(wrapper.find('.login-error').text()).toContain('XCAGI_MARKET_BASE_URL')
  })

  it('lowercases email before sending', async () => {
    sendForgotPasswordCode.mockResolvedValue({ success: true })
    const { wrapper } = await mountView()
    await wrapper.find('input[type="email"]').setValue('USER@Example.COM')
    await wrapper.find('.login-form').trigger('submit')
    await flushPromises()
    expect(sendForgotPasswordCode).toHaveBeenCalledWith('user@example.com')
  })

  it('starts cooldown after sending code', async () => {
    sendForgotPasswordCode.mockResolvedValue({ success: true })
    const { wrapper } = await mountView()
    await wrapper.find('input[type="email"]').setValue('user@example.com')
    await wrapper.find('.login-form').trigger('submit')
    await flushPromises()
    await wrapper.vm.$nextTick()
    const resendBtn = wrapper.find('.btn-resend')
    expect(resendBtn.exists()).toBe(true)
    expect(resendBtn.attributes('disabled')).toBeDefined()
    expect(resendBtn.text()).toContain('s')
  })

  it('disables resend button during cooldown and enables after', async () => {
    vi.useFakeTimers()
    sendForgotPasswordCode.mockResolvedValue({ success: true })
    const { wrapper } = await mountView()
    await wrapper.find('input[type="email"]').setValue('user@example.com')
    await wrapper.find('.login-form').trigger('submit')
    await vi.advanceTimersByTimeAsync(0)
    await vi.advanceTimersByTimeAsync(61000)
    await wrapper.vm.$nextTick()
    const resendBtn = wrapper.find('.btn-resend')
    expect(resendBtn.text()).toBe('重发')
  })

  it('can resend code from step 2', async () => {
    vi.useFakeTimers()
    sendForgotPasswordCode.mockResolvedValue({ success: true, message: '重新发送' })
    const { wrapper } = await mountView()
    await wrapper.find('input[type="email"]').setValue('user@example.com')
    await wrapper.find('.login-form').trigger('submit')
    await vi.advanceTimersByTimeAsync(0)
    await vi.advanceTimersByTimeAsync(61000)
    await wrapper.vm.$nextTick()
    sendForgotPasswordCode.mockClear()
    await wrapper.find('.btn-resend').trigger('click')
    await vi.advanceTimersByTimeAsync(0)
    await wrapper.vm.$nextTick()
    expect(sendForgotPasswordCode).toHaveBeenCalledWith('user@example.com')
  })

  it('shows mismatch error when passwords do not match on reset', async () => {
    sendForgotPasswordCode.mockResolvedValue({ success: true })
    const { wrapper } = await mountView()
    await wrapper.find('input[type="email"]').setValue('user@example.com')
    await wrapper.find('.login-form').trigger('submit')
    await flushPromises()
    await wrapper.vm.$nextTick()
    const passwordInputs = wrapper.findAll('input[type="password"]')
    await passwordInputs[0].setValue('password1')
    await passwordInputs[1].setValue('password2')
    await wrapper.find('.login-form').trigger('submit')
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.login-error').text()).toBe('两次输入的密码不一致')
    expect(resetForgotPassword).not.toHaveBeenCalled()
  })

  it('disables reset button when canReset is false', async () => {
    sendForgotPasswordCode.mockResolvedValue({ success: true })
    const { wrapper } = await mountView()
    await wrapper.find('input[type="email"]').setValue('user@example.com')
    await wrapper.find('.login-form').trigger('submit')
    await flushPromises()
    await wrapper.vm.$nextTick()
    const resetBtn = wrapper.find('.login-submit')
    expect(resetBtn.attributes('disabled')).toBeDefined()
  })

  it('resets password successfully and redirects to login', async () => {
    sendForgotPasswordCode.mockResolvedValue({ success: true })
    resetForgotPassword.mockResolvedValue({ success: true })
    const { wrapper, router } = await mountView()
    await wrapper.find('input[type="email"]').setValue('user@example.com')
    await wrapper.find('.login-form').trigger('submit')
    await flushPromises()
    await wrapper.vm.$nextTick()
    await wrapper.find('input[autocomplete="one-time-code"]').setValue('1234')
    const passwordInputs = wrapper.findAll('input[type="password"]')
    await passwordInputs[0].setValue('newpass123')
    await passwordInputs[1].setValue('newpass123')
    const pushSpy = vi.spyOn(router, 'push')
    vi.useFakeTimers()
    await wrapper.find('.login-form').trigger('submit')
    await vi.advanceTimersByTimeAsync(0)
    await vi.advanceTimersByTimeAsync(1300)
    await wrapper.vm.$nextTick()
    expect(resetForgotPassword).toHaveBeenCalledWith('user@example.com', '1234', 'newpass123')
    expect(wrapper.find('.login-success').text()).toContain('密码已重置')
    expect(pushSpy).toHaveBeenCalled()
  })

  it('handles ApiError on resetPassword', async () => {
    sendForgotPasswordCode.mockResolvedValue({ success: true })
    const apiError = new ApiError('reset fail', 400, { message: '验证码无效' })
    resetForgotPassword.mockRejectedValue(apiError)
    const { wrapper } = await mountView()
    await wrapper.find('input[type="email"]').setValue('user@example.com')
    await wrapper.find('.login-form').trigger('submit')
    await flushPromises()
    await wrapper.vm.$nextTick()
    await wrapper.find('input[autocomplete="one-time-code"]').setValue('wrong')
    const passwordInputs = wrapper.findAll('input[type="password"]')
    await passwordInputs[0].setValue('newpass123')
    await passwordInputs[1].setValue('newpass123')
    await wrapper.find('.login-form').trigger('submit')
    await flushPromises()
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.login-error').text()).toContain('验证码无效')
  })

  it('handles generic error on resetPassword', async () => {
    sendForgotPasswordCode.mockResolvedValue({ success: true })
    resetForgotPassword.mockRejectedValue(new Error('timeout'))
    const { wrapper } = await mountView()
    await wrapper.find('input[type="email"]').setValue('user@example.com')
    await wrapper.find('.login-form').trigger('submit')
    await flushPromises()
    await wrapper.vm.$nextTick()
    await wrapper.find('input[autocomplete="one-time-code"]').setValue('1234')
    const passwordInputs = wrapper.findAll('input[type="password"]')
    await passwordInputs[0].setValue('newpass123')
    await passwordInputs[1].setValue('newpass123')
    await wrapper.find('.login-form').trigger('submit')
    await flushPromises()
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.login-error').text()).toContain('重置失败')
  })

  it('clears interval on unmount', async () => {
    vi.useRealTimers()
    sendForgotPasswordCode.mockResolvedValue({ success: true })
    const { wrapper } = await mountView()
    await wrapper.find('input[type="email"]').setValue('user@example.com')
    await wrapper.find('.login-form').trigger('submit')
    await flushPromises()
    await wrapper.vm.$nextTick()
    // Component should have started cooldown interval; unmount should not throw
    expect(() => wrapper.unmount()).not.toThrow()
  })
})
