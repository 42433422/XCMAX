import { describe, it, expect, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import MainLayout from './MainLayout.vue'

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
})
