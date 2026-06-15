import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'

vi.mock('@/stores/mods', () => ({
  useModsStore: () => ({
    mods: [],
    modsForUi: [
      { id: 'test-mod', name: '测试Mod', primary: true, version: '1.0.0', menu: [
        { id: 'm1', label: '菜单1', path: '/mod/test-mod/page1' },
        { id: 'm2', label: '菜单2', path: '/mod/test-mod/page2' },
      ]},
    ],
    isLoaded: true,
    loadError: null,
    initialize: vi.fn().mockResolvedValue(undefined),
  }),
}))
vi.mock('@/utils/apiBase', () => ({
  apiFetch: vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({ success: true, data: { message: '推送成功' } }),
  }),
}))

import ModLandingView from '@/views/ModLandingView.vue'

async function mountComponent(modId = 'test-mod') {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div />' } },
      { name: 'chat', path: '/chat', component: { template: '<div />' } },
      { path: '/mod/:modId', component: ModLandingView },
    ],
  })
  await router.push(`/mod/${modId}`)
  await router.isReady()
  return mount(ModLandingView, {
    global: {
      plugins: [router],
      stubs: {
        RouterLink: {
          name: 'RouterLink',
          props: ['to'],
          template: '<a class="router-link" :href="typeof to === \'string\' ? to : to.name"><slot /></a>',
        },
      },
    },
  })
}

describe('ModLandingView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders the shell container', async () => {
    const wrapper = await mountComponent()
    expect(wrapper.find('.mod-shell').exists()).toBe(true)
  })

  it('renders hero section with mod name', async () => {
    const wrapper = await mountComponent()
    expect(wrapper.find('.hero').exists()).toBe(true)
    expect(wrapper.text()).toContain('测试Mod')
  })

  it('renders PRIMARY badge for primary mod', async () => {
    const wrapper = await mountComponent()
    expect(wrapper.find('.badge-primary').exists()).toBe(true)
    expect(wrapper.text()).toContain('PRIMARY')
  })

  it('renders mod id', async () => {
    const wrapper = await mountComponent()
    expect(wrapper.text()).toContain('test-mod')
  })

  it('renders version', async () => {
    const wrapper = await mountComponent()
    expect(wrapper.text()).toContain('v1.0.0')
  })

  it('renders menu items as cards', async () => {
    const wrapper = await mountComponent()
    const cards = wrapper.findAll('.card')
    expect(cards.length).toBe(2)
    expect(wrapper.text()).toContain('菜单1')
    expect(wrapper.text()).toContain('菜单2')
  })

  it('renders go back button', async () => {
    const wrapper = await mountComponent()
    expect(wrapper.find('.btn-ghost').exists()).toBe(true)
    expect(wrapper.find('.btn-ghost').text()).toContain('返回助手')
  })

  it('renders push to XCAGI button', async () => {
    const wrapper = await mountComponent()
    const pushBtn = wrapper.findAll('.btn').find(b => b.text().includes('推送到 XCAGI'))
    expect(pushBtn).toBeTruthy()
  })

  it('pushToXcagi calls apiFetch on button click', async () => {
    const { apiFetch } = await import('@/utils/apiBase')
    const wrapper = await mountComponent()
    const pushBtn = wrapper.findAll('.btn').find(b => b.text().includes('推送到 XCAGI'))
    await pushBtn!.trigger('click')
    await flushPromises()
    expect(apiFetch).toHaveBeenCalled()
  })

  it('shows loading text during push', async () => {
    const { apiFetch } = await import('@/utils/apiBase')
    let resolvePromise!: (v: any) => void
    ;(apiFetch as any).mockImplementationOnce(() => new Promise(r => { resolvePromise = r }))
    const wrapper = await mountComponent()
    const pushBtn = wrapper.findAll('.btn').find(b => b.text().includes('推送到 XCAGI'))
    await pushBtn!.trigger('click')
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('请求中')
    resolvePromise({ ok: true, status: 200, json: async () => ({ success: true, data: { message: 'ok' } }) })
    await flushPromises()
  })

  it('shows success message after push', async () => {
    const wrapper = await mountComponent()
    const pushBtn = wrapper.findAll('.btn').find(b => b.text().includes('推送到 XCAGI'))
    await pushBtn!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('推送成功')
  })

  it('shows error message on API failure', async () => {
    const { apiFetch } = await import('@/utils/apiBase')
    ;(apiFetch as any).mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ success: false, message: '推送失败' }),
    })
    const wrapper = await mountComponent()
    const pushBtn = wrapper.findAll('.btn').find(b => b.text().includes('推送到 XCAGI'))
    await pushBtn!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('推送失败')
  })

  it('shows network error message on fetch failure', async () => {
    const { apiFetch } = await import('@/utils/apiBase')
    ;(apiFetch as any).mockRejectedValueOnce(new Error('Network error'))
    const wrapper = await mountComponent()
    const pushBtn = wrapper.findAll('.btn').find(b => b.text().includes('推送到 XCAGI'))
    await pushBtn!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('Network error')
  })

  it('shows not-found message for unknown mod id', async () => {
    const wrapper = await mountComponent('nonexistent-mod')
    expect(wrapper.text()).toContain('未找到')
  })

  it('renders push message area after push', async () => {
    const wrapper = await mountComponent()
    const pushBtn = wrapper.findAll('.btn').find(b => b.text().includes('推送到 XCAGI'))
    await pushBtn!.trigger('click')
    await flushPromises()
    expect(wrapper.find('.push-msg').exists()).toBe(true)
  })
})
