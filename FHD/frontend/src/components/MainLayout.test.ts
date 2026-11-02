import { describe, it, expect, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import MainLayout from './MainLayout.vue'
import * as sidebarNavigation from '@/utils/sidebarNavigation'

vi.mock('./Sidebar.vue', () => ({
  default: {
    name: 'Sidebar',
    template: `
      <nav class="sidebar-stub">
        <button class="sidebar-chat" type="button" @click="$emit('change-view', 'chat')">智能对话</button>
        <button class="sidebar-workflow" type="button" @click="$emit('change-view', 'employee-workflow')">员工工作台</button>
      </nav>
    `,
    props: ['activeView'],
    emits: ['change-view'],
  },
}))

vi.mock('./PaneResizeHandle.vue', () => ({
  default: { template: '<span />' },
}))

vi.mock('./task-center/GlobalTaskCenter.vue', () => ({
  default: { template: '<button class="task-center-stub">工作区</button>' },
}))

vi.mock('./TopQuickNav.vue', () => ({
  default: {
    template: '<input class="top-quick-nav-stub" />',
    emits: ['select'],
  },
}))

describe('MainLayout.vue', () => {
  function createTestRouter() {
    return createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', name: 'chat', component: { template: '<div>Chat</div>' } },
        { path: '/settings', name: 'settings', component: { template: '<div>Settings</div>' } },
        {
          path: '/workflow-employee-space',
          name: 'workflow-employee-space',
          component: { template: '<div>Workflow</div>' },
        },
      ],
    })
  }

  it('mounts shell with sidebar stub', () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const router = createTestRouter()

    const wrapper = mount(MainLayout, {
      global: {
        plugins: [pinia, router],
        stubs: {
          RouterView: { template: '<div class="router-view-stub" />' },
          RouterLink: { template: '<a><slot /></a>' },
        },
      },
    })

    expect(wrapper.find('.sidebar-stub').exists()).toBe(true)
    expect(wrapper.find('.main-container').exists()).toBe(true)
    expect(wrapper.find('.top-bar-actions .task-center-stub').exists()).toBe(true)
    wrapper.unmount()
  })

  it('does not show loading feedback after the idle shell has settled', async () => {
    vi.useFakeTimers({ toFake: ['Date', 'setTimeout', 'clearTimeout'] })
    const pinia = createPinia()
    setActivePinia(pinia)
    const router = createTestRouter()
    await router.push('/')
    const wrapper = mount(MainLayout, { global: { plugins: [pinia, router] } })
    try {
      await flushPromises()
      await vi.advanceTimersByTimeAsync(6000)
      expect(wrapper.find('.route-nav-feedback').exists()).toBe(false)
    } finally {
      wrapper.unmount()
      vi.useRealTimers()
    }
  })

  it('keeps Windows desktop parity by navigating sidebar chat and aliases', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const router = createTestRouter()
    await router.push('/settings')

    const wrapper = mount(MainLayout, {
      global: {
        plugins: [pinia, router],
        stubs: {
          RouterView: { template: '<div class="router-view-stub" />' },
          RouterLink: { template: '<a><slot /></a>' },
        },
      },
    })

    await wrapper.find('.sidebar-chat').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('chat')

    await wrapper.find('.sidebar-workflow').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('workflow-employee-space')
    wrapper.unmount()
  })

  it('shows slow navigation in the content region and ignores repeat clicks to that target', async () => {
    vi.useFakeTimers({ toFake: ['Date', 'setTimeout', 'clearTimeout'] })
    const pinia = createPinia()
    setActivePinia(pinia)
    const router = createTestRouter()
    await router.push('/settings')
    let finish!: (applied: boolean) => void
    const navigation = vi.spyOn(sidebarNavigation, 'navigateFromSidebarKey').mockImplementation(() => new Promise(resolve => { finish = resolve }))
    const wrapper = mount(MainLayout, { slots: { default: '<section class="current-page">当前内容</section>' }, global: { plugins: [pinia, router] } })
    try {
      await wrapper.get('.sidebar-chat').trigger('click')
      await wrapper.get('.sidebar-chat').trigger('click')
      expect(navigation).toHaveBeenCalledTimes(1)
      await vi.advanceTimersByTimeAsync(280)
      expect(wrapper.get('.route-content [role="status"]').text()).toContain('正在打开「')
      expect(wrapper.find('.top-bar [role="status"]').exists()).toBe(false)
      expect(wrapper.get('.current-page').text()).toBe('当前内容')
      finish(true)
      await flushPromises()
      expect(wrapper.find('.route-nav-feedback').exists()).toBe(false)
    } finally {
      wrapper.unmount(); navigation.mockRestore(); vi.useRealTimers()
    }
  })

  it('offers retry after navigation fails and keeps other navigation available', async () => {
    vi.useFakeTimers({ toFake: ['Date', 'setTimeout', 'clearTimeout'] })
    const pinia = createPinia()
    setActivePinia(pinia)
    const router = createTestRouter()
    await router.push('/settings')
    const pending = new Map<string, { resolve: (applied: boolean) => void; reject: (error: Error) => void }>()
    const navigation = vi.spyOn(sidebarNavigation, 'navigateFromSidebarKey')
      .mockRejectedValueOnce(new Error('network interrupted'))
      .mockImplementation((_router, key) => new Promise((resolve, reject) => { pending.set(key, { resolve, reject }) }))
    const wrapper = mount(MainLayout, { global: { plugins: [pinia, router] } })
    try {
      await wrapper.get('.sidebar-chat').trigger('click')
      await flushPromises()
      expect(wrapper.get('.route-content [role="alert"]').text()).toContain('页面加载失败')
      await wrapper.get('.route-loading-feedback__retry').trigger('click')
      expect(navigation).toHaveBeenCalledTimes(2)
      expect(wrapper.find('[role="alert"]').exists()).toBe(false)
      await wrapper.get('.sidebar-workflow').trigger('click')
      expect(navigation).toHaveBeenCalledTimes(3)
      expect(navigation.mock.calls[2][1]).toBe('employee-workflow')
      pending.get('chat')!.reject(new Error('older target failed'))
      await flushPromises()
      expect(wrapper.find('[role="alert"]').exists()).toBe(false)
      await vi.advanceTimersByTimeAsync(280)
      expect(wrapper.get('[role="status"]').text()).toContain('正在打开「员工工作台」')
      pending.get('employee-workflow')!.resolve(true)
      await flushPromises()
    } finally {
      wrapper.unmount(); navigation.mockRestore(); vi.useRealTimers()
    }
  })
})
