import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'

const mocks = vi.hoisted(() => ({
  forgotAccountMock: vi.fn(),
}))

vi.mock('@/api/auth', () => ({
  authApi: {
    forgotAccount: mocks.forgotAccountMock,
  },
}))

vi.mock('@/api', () => ({
  ApiError: class ApiError extends Error {
    data: unknown
    constructor(message: string, data: unknown = undefined) {
      super(message)
      this.name = 'ApiError'
      this.data = data
    }
  },
}))

import ForgotAccountView from './ForgotAccountView.vue'

const forgotAccountMock = mocks.forgotAccountMock

function mountView(query: Record<string, string> = {}) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/forgot-account', name: 'forgot-account', component: ForgotAccountView },
      { path: '/login', name: 'login', component: { template: '<div />' } },
      { path: '/forgot-password', name: 'login-forgot-password', component: { template: '<div />' } },
    ],
  })
  return router.push({ path: '/forgot-account', query }).then(() =>
    router.isReady().then(() =>
      mount(ForgotAccountView, {
        global: {
          plugins: [router],
          stubs: { RouterLink: { template: '<a><slot /></a>' } },
        },
      }),
    ),
  )
}

describe('ForgotAccountView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders the page heading', async () => {
    const wrapper = await mountView()
    expect(wrapper.find('.login-heading').text()).toBe('忘记账号')
  })

  it('renders the page hint', async () => {
    const wrapper = await mountView()
    expect(wrapper.find('.page-hint').text()).toContain('邮箱')
  })

  it('renders email input', async () => {
    const wrapper = await mountView()
    expect(wrapper.find('input[type="email"]').exists()).toBe(true)
  })

  it('renders submit button', async () => {
    const wrapper = await mountView()
    const btn = wrapper.find('.login-submit')
    expect(btn.exists()).toBe(true)
    expect(btn.text()).toContain('查询账号')
  })

  it('disables submit button when email is empty', async () => {
    const wrapper = await mountView()
    expect(wrapper.find('.login-submit').attributes('disabled')).toBeDefined()
  })

  it('enables submit button when email is filled', async () => {
    const wrapper = await mountView()
    await wrapper.find('input[type="email"]').setValue('user@example.com')
    expect(wrapper.find('.login-submit').attributes('disabled')).toBeUndefined()
  })

  it('shows error for invalid email (no @)', async () => {
    const wrapper = await mountView()
    await wrapper.find('input[type="email"]').setValue('not-an-email')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()
    expect(wrapper.find('.login-error').text()).toContain('请填写有效邮箱')
  })

  it('shows error for empty email', async () => {
    const wrapper = await mountView()
    await wrapper.find('input[type="email"]').setValue('   ')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()
    expect(wrapper.find('.login-error').text()).toContain('请填写有效邮箱')
  })

  it('calls authApi.forgotAccount with trimmed lowercase email', async () => {
    forgotAccountMock.mockResolvedValue({ data: { usernames: ['alice'] }, message: '找到账号' })
    const wrapper = await mountView()
    await wrapper.find('input[type="email"]').setValue('  USER@EXAMPLE.COM  ')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()
    expect(forgotAccountMock).toHaveBeenCalledWith('user@example.com')
  })

  it('shows success message and usernames when found', async () => {
    forgotAccountMock.mockResolvedValue({
      data: { usernames: ['alice', 'bob'] },
      message: '找到账号',
    })
    const wrapper = await mountView()
    await wrapper.find('input[type="email"]').setValue('user@example.com')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()
    expect(wrapper.find('.login-success').exists()).toBe(true)
    expect(wrapper.find('.username-list').exists()).toBe(true)
    const items = wrapper.findAll('.username-list li')
    expect(items).toHaveLength(2)
    expect(items[0].text()).toBe('alice')
  })

  it('shows "未找到关联账号" when no usernames returned', async () => {
    forgotAccountMock.mockResolvedValue({ data: { usernames: [] } })
    const wrapper = await mountView()
    await wrapper.find('input[type="email"]').setValue('user@example.com')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()
    expect(wrapper.find('.login-success').text()).toContain('未找到关联账号')
  })

  it('uses message from response when available', async () => {
    forgotAccountMock.mockResolvedValue({
      data: { usernames: [] },
      message: '自定义消息',
    })
    const wrapper = await mountView()
    await wrapper.find('input[type="email"]').setValue('user@example.com')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()
    expect(wrapper.find('.login-success').text()).toContain('自定义消息')
  })

  it('shows loading state during submit', async () => {
    let resolveFn: (v: unknown) => void
    forgotAccountMock.mockReturnValue(
      new Promise((resolve) => {
        resolveFn = resolve
      }),
    )
    const wrapper = await mountView()
    await wrapper.find('input[type="email"]').setValue('user@example.com')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()
    expect(wrapper.find('.login-submit').text()).toContain('查询中...')
    expect(wrapper.find('input[type="email"]').attributes('disabled')).toBeDefined()
    resolveFn!({ data: { usernames: [] } })
    await flushPromises()
    expect(wrapper.find('.login-submit').text()).toContain('查询账号')
  })

  it('shows error message on ApiError', async () => {
    const { ApiError } = await import('@/api')
    forgotAccountMock.mockRejectedValue(
      new ApiError('请求失败', { message: '邮箱不存在' }),
    )
    const wrapper = await mountView()
    await wrapper.find('input[type="email"]').setValue('user@example.com')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()
    expect(wrapper.find('.login-error').text()).toContain('邮箱不存在')
  })

  it('shows error message on ApiError with error object', async () => {
    const { ApiError } = await import('@/api')
    forgotAccountMock.mockRejectedValue(
      new ApiError('请求失败', { error: { message: '服务异常' } }),
    )
    const wrapper = await mountView()
    await wrapper.find('input[type="email"]').setValue('user@example.com')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()
    expect(wrapper.find('.login-error').text()).toContain('服务异常')
  })

  it('shows generic error on non-ApiError exception', async () => {
    forgotAccountMock.mockRejectedValue(new Error('network'))
    const wrapper = await mountView()
    await wrapper.find('input[type="email"]').setValue('user@example.com')
    await wrapper.find('form').trigger('submit.prevent')
    await flushPromises()
    expect(wrapper.find('.login-error').text()).toContain('查询失败')
  })

  it('renders login and forgot-password links', async () => {
    const wrapper = await mountView()
    const links = wrapper.findAll('a')
    expect(links.length).toBeGreaterThanOrEqual(2)
    expect(wrapper.text()).toContain('忘记密码')
    expect(wrapper.text()).toContain('返回登录')
  })
})
