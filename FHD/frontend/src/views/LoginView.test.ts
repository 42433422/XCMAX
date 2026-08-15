import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'

const { fetchProductSku } = vi.hoisted(() => ({
  fetchProductSku: vi.fn().mockResolvedValue('generic'),
}))

vi.mock('@/utils/productSku', () => ({ fetchProductSku }))

import LoginView from './LoginView.vue'

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/login', name: 'login', component: LoginView }],
  })
}

describe('LoginView.vue', () => {
  beforeEach(() => {
    fetchProductSku.mockReset()
    fetchProductSku.mockResolvedValue('generic')
  })

  it('exports a Vue component', () => {
    expect(LoginView).toBeTruthy()
  })

  it('renders login form shell', async () => {
    const router = makeRouter()
    await router.push('/login')
    await router.isReady()
    const wrapper = mount(LoginView, {
      global: {
        plugins: [router],
        stubs: { RouterLink: true, RouterView: true },
      },
    })
    expect(wrapper.text().length).toBeGreaterThan(0)
  })

  it('shows enterprise account registration, purchase, and entitlement-sync guidance', async () => {
    fetchProductSku.mockResolvedValue('enterprise')
    const router = makeRouter()
    await router.push('/login')
    await router.isReady()
    const wrapper = mount(LoginView, {
      global: {
        plugins: [router],
        stubs: { RouterLink: true, RouterView: true },
      },
    })

    await flushPromises()

    const actions = wrapper.findAll('.login-account-action')
    expect(actions).toHaveLength(2)
    expect(actions[0].text()).toContain('注册账号')
    expect(actions[0].attributes('href')).toBe(
      'https://xiu-ci.com/market/register?source=xcagi-desktop',
    )
    expect(actions[1].text()).toContain('购买与授权')
    expect(actions[1].attributes('href')).toBe(
      'https://xiu-ci.com/market/plans?plan=plan_enterprise&source=xcagi-desktop',
    )
    expect(wrapper.find('.login-subheading').text()).toContain('同步账号权益')
  })
})
