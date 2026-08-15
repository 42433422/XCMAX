import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import { setActivePinia, createPinia } from 'pinia'
import RegisterView from './RegisterView.vue'

const registerMock = vi.hoisted(() => vi.fn())

vi.mock('@/api', () => ({
  api: {
    register: registerMock,
    sendRegisterVerificationCode: vi.fn(),
  },
}))

describe('RegisterView', () => {
  let router: ReturnType<typeof createRouter>

  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/register', name: 'register', component: { template: '<div />' } },
        { path: '/login', name: 'login', component: { template: '<div />' } },
        { path: '/workbench/home', name: 'workbench-home', component: { template: '<div />' } },
        { path: '/plans', name: 'plans', component: { template: '<div />' } },
      ],
    })
  })

  it('renders register form', async () => {
    router.push('/register')
    await router.isReady()

    const wrapper = mount(RegisterView, {
      global: { plugins: [router] },
    })

    expect(wrapper.text()).toContain('注册')
    expect(wrapper.text()).toContain('邮箱（选填）')
    expect(wrapper.find('input[type="email"]').attributes('required')).toBeUndefined()
    expect(wrapper.find('input[type="password"]').exists()).toBe(true)
    expect(wrapper.find('button[type="submit"]').exists()).toBe(true)
  })

  it('renders login link', async () => {
    router.push('/register')
    await router.isReady()

    const wrapper = mount(RegisterView, {
      global: { plugins: [router] },
    })

    expect(wrapper.text()).toContain('登录')
  })

  it('shows email verification controls only after an email is entered', async () => {
    router.push('/register')
    await router.isReady()

    const wrapper = mount(RegisterView, {
      global: { plugins: [router] },
    })

    expect(wrapper.find('.input-code').exists()).toBe(false)
    expect(wrapper.find('.btn-send').exists()).toBe(false)

    await wrapper.find('input[type="email"]').setValue('verify@example.test')

    expect(wrapper.find('.input-code').exists()).toBe(true)
    expect(wrapper.find('.btn-send').exists()).toBe(true)
    expect(wrapper.text()).toContain('填写邮箱后必填')
  })

  it('registers with only username and password when email is blank', async () => {
    router.push('/register')
    await router.isReady()
    const replaceSpy = vi.spyOn(router, 'replace')
    registerMock.mockResolvedValue({ ok: true })

    const wrapper = mount(RegisterView, { global: { plugins: [router] } })
    await wrapper.find('input[autocomplete="username"]').setValue('no-email-user')
    await wrapper.find('input[type="password"]').setValue('secret123')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(registerMock).toHaveBeenCalledWith('no-email-user', 'secret123', '', '')
    expect(replaceSpy).toHaveBeenCalledWith({
      name: 'plans',
      query: { plan: 'plan_enterprise' },
    })
  })

  it('sends ordinary web registration to plan selection', async () => {
    router.push('/register')
    await router.isReady()
    const replaceSpy = vi.spyOn(router, 'replace')
    registerMock.mockResolvedValue({ ok: true })

    const wrapper = mount(RegisterView, { global: { plugins: [router] } })
    await wrapper.find('input[autocomplete="username"]').setValue('web-user')
    await wrapper.find('input[type="email"]').setValue('web@example.test')
    await wrapper.find('.input-code').setValue('123456')
    await wrapper.find('input[type="password"]').setValue('secret123')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(registerMock).toHaveBeenCalledWith('web-user', 'secret123', 'web@example.test', '123456')
    expect(replaceSpy).toHaveBeenCalledWith({
      name: 'plans',
      query: { plan: 'plan_enterprise' },
    })
  })

  it('shows a desktop-specific handoff after the same registration call without entering web workbench', async () => {
    router.push('/register?source=xcagi-desktop')
    await router.isReady()
    const replaceSpy = vi.spyOn(router, 'replace')
    registerMock.mockResolvedValue({ ok: true })

    const wrapper = mount(RegisterView, { global: { plugins: [router] } })
    expect(wrapper.text()).toContain('来自 XCAGI 桌面端')
    expect(wrapper.text()).toContain('桌面端与网页端共用同一账号')
    expect(wrapper.text()).toContain('请关闭本页，回到 XCAGI 桌面端登录')
    expect(wrapper.find('a[href="/login"]').exists()).toBe(false)
    await wrapper.find('input[autocomplete="username"]').setValue('desktop-user')
    await wrapper.find('input[type="email"]').setValue('desktop@example.test')
    await wrapper.find('.input-code').setValue('654321')
    await wrapper.find('input[type="password"]').setValue('secret123')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(registerMock).toHaveBeenCalledWith('desktop-user', 'secret123', 'desktop@example.test', '654321')
    expect(wrapper.text()).toContain('账号注册成功')
    expect(wrapper.text()).toContain('选择套餐并完成支付')
    expect(wrapper.text()).toContain('权益生效后，再回到 XCAGI 桌面端登录')
    expect(replaceSpy).not.toHaveBeenCalled()
  })
})
