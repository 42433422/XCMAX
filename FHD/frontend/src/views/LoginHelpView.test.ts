import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'

vi.mock('@/utils/productSku', () => ({
  fetchProductSku: vi.fn().mockResolvedValue('generic'),
}))

vi.mock('@/constants/loginBranding', () => ({
  LOGIN_HELP_PAGE_TITLE: '登录帮助',
  LOGIN_HELP_SECTIONS: [
    { title: '账号问题', items: ['忘记账号', '账号被锁定'] },
    { title: '密码问题', items: ['忘记密码', '密码过期'] },
  ],
  loginHelpDocUrl: () => 'https://help.example.com/login',
  loginPageTitle: () => 'FHD · 登录',
  marketForgotPasswordUrl: () => 'https://market.example.com/forgot',
}))

import LoginHelpView from './LoginHelpView.vue'

function mountView(query: Record<string, string> = {}) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/login-help', name: 'login-help', component: LoginHelpView },
      { path: '/login', name: 'login', component: { template: '<div />' } },
    ],
  })
  return router.push({ path: '/login-help', query }).then(() =>
    router.isReady().then(() =>
      mount(LoginHelpView, {
        global: {
          plugins: [router],
          stubs: { RouterLink: { template: '<a><slot /></a>' } },
        },
      }),
    ),
  )
}

describe('LoginHelpView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders the page title', async () => {
    const wrapper = await mountView()
    expect(wrapper.find('.login-help-title').text()).toBe('登录帮助')
  })

  it('renders the intro text', async () => {
    const wrapper = await mountView()
    expect(wrapper.find('.login-help-intro').text()).toContain('常见问题')
  })

  it('renders all sections from LOGIN_HELP_SECTIONS', async () => {
    const wrapper = await mountView()
    const sections = wrapper.findAll('.login-help-section')
    expect(sections).toHaveLength(2)
    expect(sections[0].find('h2').text()).toBe('账号问题')
    expect(sections[1].find('h2').text()).toBe('密码问题')
  })

  it('renders items in each section', async () => {
    const wrapper = await mountView()
    const firstSectionItems = wrapper.findAll('.login-help-section')[0].findAll('li')
    expect(firstSectionItems).toHaveLength(2)
    expect(firstSectionItems[0].text()).toBe('忘记账号')
  })

  it('renders back to login button', async () => {
    const wrapper = await mountView()
    expect(wrapper.find('.login-help-back').text()).toContain('返回登录')
  })

  it('renders forgot password link', async () => {
    const wrapper = await mountView()
    const links = wrapper.findAll('.login-help-actions a')
    const forgotLink = links.find((l) => l.text().includes('忘记密码'))
    expect(forgotLink).toBeTruthy()
    expect(forgotLink!.attributes('href')).toBe('https://market.example.com/forgot')
  })

  it('renders external help doc link', async () => {
    const wrapper = await mountView()
    const links = wrapper.findAll('.login-help-actions a')
    const docLink = links.find((l) => l.text().includes('在线文档'))
    expect(docLink).toBeTruthy()
    expect(docLink!.attributes('href')).toBe('https://help.example.com/login')
  })

  it('navigates to login page when back button is clicked', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/login-help', name: 'login-help', component: LoginHelpView },
        { path: '/login', name: 'login', component: { template: '<div class="login-page" />' } },
      ],
    })
    await router.push('/login-help')
    await router.isReady()
    const wrapper = mount(LoginHelpView, {
      global: {
        plugins: [router],
        stubs: { RouterLink: { template: '<a><slot /></a>' } },
      },
    })
    await wrapper.find('.login-help-back').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('login')
  })

  it('sets document title on mount', async () => {
    await mountView()
    expect(document.title).toContain('登录帮助')
  })

  it('preserves query params when navigating back to login', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/login-help', name: 'login-help', component: LoginHelpView },
        { path: '/login', name: 'login', component: { template: '<div />' } },
      ],
    })
    await router.push({ path: '/login-help', query: { redirect: '/dashboard' } })
    await router.isReady()
    const wrapper = mount(LoginHelpView, {
      global: {
        plugins: [router],
        stubs: { RouterLink: { template: '<a><slot /></a>' } },
      },
    })
    await wrapper.find('.login-help-back').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.query.redirect).toBe('/dashboard')
  })
})
