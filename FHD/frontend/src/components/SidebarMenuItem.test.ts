import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import SidebarMenuItem from './SidebarMenuItem.vue'

const employeeWorkflowItem = {
  key: 'employee-workflow',
  name: '员工工作台',
  iconClass: 'fa-users',
  children: [
    { key: 'workflow-employee-space', name: '员工空间', iconClass: 'fa-th-large' },
  ],
}

describe('SidebarMenuItem.vue', () => {
  it('shows "name · description" tooltip when description is present', () => {
    const wrapper = mount(SidebarMenuItem, {
      props: {
        item: { key: 'chat', name: '智能对话', iconClass: 'fa-comments-o', description: '找小C办事、下指令、看任务进度' },
        activeView: 'chat',
      },
    })
    const button = wrapper.get('button.menu-item')
    expect(button.attributes('title')).toBe('智能对话 · 找小C办事、下指令、看任务进度')
  })

  it('falls back to plain name when description is absent', () => {
    const wrapper = mount(SidebarMenuItem, {
      props: {
        item: { key: 'products', name: '业务对象', iconClass: 'fa-cubes' },
        activeView: 'products',
      },
    })
    const button = wrapper.get('button.menu-item')
    expect(button.attributes('title')).toBe('业务对象')
  })

  it('activates employee space submenu via pointerup without duplicate click emission', async () => {
    vi.useFakeTimers()
    try {
      const wrapper = mount(SidebarMenuItem, {
        props: {
          item: employeeWorkflowItem,
          activeView: 'printer-list',
          isExpanded: true,
        },
      })
      const child = wrapper.get('button.submenu-item[data-view="workflow-employee-space"]')

      await child.trigger('pointerup', { button: 0 })
      await child.trigger('click')

      expect(wrapper.emitted('select-view')).toEqual([[ 'workflow-employee-space' ]])
    } finally {
      vi.useRealTimers()
    }
  })
})
