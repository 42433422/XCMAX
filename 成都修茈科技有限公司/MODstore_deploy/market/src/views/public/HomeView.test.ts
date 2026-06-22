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

  it('handles customer-service route intake, contact submit, and employee upload guards', async () => {
    vi.useFakeTimers()
    try {
      const brief = btoa(unescape(encodeURIComponent('需要处理售后退款')))
        .replace(/\+/g, '-')
        .replace(/\//g, '_')
        .replace(/=+$/, '')
      localStorage.setItem('modstore_token', 'token')
      vi.mocked(api.me).mockResolvedValue({ username: 'alice', email: 'alice@example.com' })
      vi.mocked(api.catalog).mockResolvedValue({ items: [] })
      vi.mocked(api.submitLandingContact).mockResolvedValue({ ok: true })
      vi.mocked(api.uploadPackage).mockResolvedValue({ ok: true })
      Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
        configurable: true,
        value: vi.fn(),
      })

      router.push({
        path: '/',
        query: {
          cs_uid: '12',
          cs_t: 'token-12',
          cs_name: '张三',
          brief,
        },
      })
      await router.isReady()

      const wrapper = mount(HomeView, {
        global: { plugins: [router] },
      })
      await flushPromises()

      const vm = wrapper.vm as any
      expect(vm.userLabel).toBe('alice')
      expect(vm.contactForm.name).toBe('张三')
      expect(vm.contactForm.message).toContain('售后退款')

      vm.toggleMobileNav()
      await wrapper.vm.$nextTick()
      expect(document.body.classList.contains('landing-nav-open')).toBe(true)
      vm.closeMobileNav()
      await wrapper.vm.$nextTick()
      expect(document.body.classList.contains('landing-nav-open')).toBe(false)

      await vm.submitContact()
      expect(api.submitLandingContact).toHaveBeenCalledWith(expect.objectContaining({
        source: 'cs_intake',
        cs_uid: 12,
        cs_t: 'token-12',
      }))
      expect(vm.contactSuccess).toBe(true)

      vi.mocked(api.submitLandingContact).mockRejectedValueOnce(new Error('contact failed'))
      vm.contactForm = { name: '李四', email: 'li@example.com', phone: '', company: '', message: '咨询' }
      await vm.submitContact()
      expect(vm.contactError).toContain('contact failed')

      await vm.uploadEmployee()
      expect(vm.uploadError).toContain('请选择')

      vm.handleFileChange({ target: { files: [new File(['pkg'], 'employee.zip', { type: 'application/zip' })] } })
      vm.uploadForm = {
        name: '收费员工',
        description: '收费但个人授权',
        industry: '客服',
        price: 9,
        license_scope: 'personal',
        origin_type: 'original',
        ip_risk_level: 'low',
      }
      await vm.uploadEmployee()
      expect(vm.uploadError).toContain('商业授权')

      vm.handleFileChange({ target: { files: [new File(['pkg'], 'employee.zip', { type: 'application/zip' })] } })
      vm.uploadForm = {
        name: '风险员工',
        description: '联动素材',
        industry: '客服',
        price: 0,
        license_scope: 'commercial',
        origin_type: 'fan_linkage',
        ip_risk_level: 'medium',
      }
      await vm.uploadEmployee()
      expect(vm.uploadError).toContain('只能免费')

      vm.handleFileChange({ target: { files: [new File(['pkg'], 'employee.zip', { type: 'application/zip' })] } })
      vm.uploadForm = {
        name: '免费员工',
        description: '原创客服员工',
        industry: '',
        price: 0,
        license_scope: 'personal',
        origin_type: 'original',
        ip_risk_level: 'low',
      }
      await vm.uploadEmployee()
      expect(api.uploadPackage).toHaveBeenCalled()
      expect(vm.uploadSuccess).toBe(true)
      await vi.advanceTimersByTimeAsync(3000)
      expect(vm.showUploadModal).toBe(false)

      router.push('/')
      await router.isReady()
      await flushPromises()
      expect(vm.csIntakeActive).toBe(false)

      wrapper.unmount()
      expect(document.body.classList.contains('landing-nav-open')).toBe(false)
    } finally {
      vi.useRealTimers()
    }
  })
})
