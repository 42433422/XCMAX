import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import { setActivePinia, createPinia } from 'pinia'
import RegisterView from './RegisterView.vue'

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
    expect(wrapper.find('input[type="email"]').exists()).toBe(true)
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

  it('renders verification code input and send button', async () => {
    router.push('/register')
    await router.isReady()

    const wrapper = mount(RegisterView, {
      global: { plugins: [router] },
    })

    expect(wrapper.find('.input-code').exists()).toBe(true)
    expect(wrapper.find('.btn-send').exists()).toBe(true)
  })
})
