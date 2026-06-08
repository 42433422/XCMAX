import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import { setActivePinia, createPinia } from 'pinia'
import HomeView from './HomeView.vue'
import { api } from '../../api'

vi.mock('../../api', () => ({
  api: {
    me: vi.fn(),
    catalog: vi.fn(),
    submitLandingContact: vi.fn(),
    uploadPackage: vi.fn(),
  },
}))

describe('HomeView', () => {
  let router: ReturnType<typeof createRouter>

  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.clearAllMocks()
    router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', name: 'home', component: { template: '<div />' } },
        { path: '/login', name: 'login', component: { template: '<div />' } },
        { path: '/register', name: 'register', component: { template: '<div />' } },
        { path: '/workbench', name: 'workbench-shell', component: { template: '<div />' } },
        { path: '/ai-store', name: 'ai-store', component: { template: '<div />' } },
        { path: '/plans', name: 'plans', component: { template: '<div />' } },
        { path: '/catalog/:id', name: 'catalog-detail', component: { template: '<div />' } },
      ],
    })
  })

  it('renders hero section with key text', async () => {
    vi.mocked(api.catalog).mockResolvedValue({ items: [] })
    router.push('/')
    await router.isReady()

    const wrapper = mount(HomeView, {
      global: { plugins: [router] },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('XC AGI')
    expect(wrapper.text()).toContain('智能员工团队')
    expect(wrapper.text()).toContain('开始使用')
  })

  it('renders feature section', async () => {
    vi.mocked(api.catalog).mockResolvedValue({ items: [] })
    router.push('/')
    await router.isReady()

    const wrapper = mount(HomeView, {
      global: { plugins: [router] },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('智能识别')
    expect(wrapper.text()).toContain('自动化处理')
    expect(wrapper.text()).toContain('7×24 工作')
  })

  it('renders market items when available', async () => {
    vi.mocked(api.catalog).mockResolvedValue({
      items: [
        { id: 1, name: 'AI 助手', description: '智能助手', price: 0 },
        { id: 2, name: '数据分析师', description: '数据分析', price: 99.9 },
      ],
    })
    router.push('/')
    await router.isReady()

    const wrapper = mount(HomeView, {
      global: { plugins: [router] },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('AI 助手')
    expect(wrapper.text()).toContain('数据分析师')
    expect(wrapper.text()).toContain('免费')
  })

  it('renders empty market state', async () => {
    vi.mocked(api.catalog).mockResolvedValue({ items: [] })
    router.push('/')
    await router.isReady()

    const wrapper = mount(HomeView, {
      global: { plugins: [router] },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('AI 市场暂无商品')
  })

  it('shows register link when not logged in', async () => {
    vi.mocked(api.catalog).mockResolvedValue({ items: [] })
    router.push('/')
    await router.isReady()

    const wrapper = mount(HomeView, {
      global: { plugins: [router] },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('免费注册')
  })

  it('renders contact form', async () => {
    vi.mocked(api.catalog).mockResolvedValue({ items: [] })
    router.push('/')
    await router.isReady()

    const wrapper = mount(HomeView, {
      global: { plugins: [router] },
    })
    await flushPromises()

    expect(wrapper.find('#contact-form').exists()).toBe(true)
    expect(wrapper.text()).toContain('商务合作与咨询')
  })

  it('renders footer with company info', async () => {
    vi.mocked(api.catalog).mockResolvedValue({ items: [] })
    router.push('/')
    await router.isReady()

    const wrapper = mount(HomeView, {
      global: { plugins: [router] },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('成都修茈科技有限公司')
  })
})
