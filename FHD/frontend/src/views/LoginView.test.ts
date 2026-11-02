import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import { CORE_ROUTES } from '@/router/routes/core'

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
    const notice = wrapper.get('#login-data-processing-notice')
    expect(notice.text()).toContain('登录前请阅读')
    expect(notice.text()).toContain('任务所需内容并产生费用')
    expect(notice.text()).not.toContain('登录即表示同意')
    for (const element of ['#login-heading', '.login-form', '.login-submit', '.login-basic']) {
      expect(wrapper.get(element).element.compareDocumentPosition(notice.element) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    }
    expect(notice.element.compareDocumentPosition(wrapper.get('.login-footer').element) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(wrapper.get('.login-submit').text()).toBe('同意说明并登录')
    expect(wrapper.get('.login-basic').text()).toBe('仅登录')
    for (const element of ['.login-panel', '.login-form', '.login-submit']) {
      expect(wrapper.get(element).attributes('aria-describedby')).toBe(notice.attributes('id'))
    }
    expect(notice.find('input[type=checkbox]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('keeps enterprise account actions without the removed entitlement-sync guidance or its spacer', async () => {
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
    expect(actions[0].attributes('href')).toBe('https://xiu-ci.com/market/register?source=xcagi-desktop')
    expect(actions[1].text()).toContain('购买与授权')
    expect(actions[1].attributes('href')).toBe('https://xiu-ci.com/market/account-plans?plan=saas-trial-30&source=xcagi-desktop')
    expect(wrapper.text()).not.toContain('完成账号注册与企业授权后')
    expect(wrapper.find('.login-subheading').exists()).toBe(false)
    wrapper.unmount()
  })

  it('opens the local agreement and privacy documents from the login notice', async () => {
    const router = createRouter({ history: createMemoryHistory(), routes: CORE_ROUTES })
    await router.push('/login?redirect=/business-docking'); await router.isReady()
    const wrapper = mount(LoginView, { global: { plugins: [router] } })
    try {
      const links = wrapper.get('#login-data-processing-notice').findAll('a')
      expect(links.map(link => link.text())).toEqual(['《服务协议》', '《隐私政策》'])
      for (const [index, document] of ['service-agreement', 'privacy-policy'].entries()) {
        await links[index].trigger('click'); await flushPromises()
        await vi.waitFor(() => expect(router.currentRoute.value).toMatchObject({ name: 'login-legal', params: { document }, query: { redirect: '/business-docking' } }))
      }
    } finally { wrapper.unmount() }
  })
})
