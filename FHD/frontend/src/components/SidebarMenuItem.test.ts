import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import SidebarMenuItem from './SidebarMenuItem.vue'

const employeeWorkflowItem = {
  key: 'employee-workflow',
  name: '员工工作台',
  iconClass: 'fa-users',
  children: [
    { key: 'workflow-employee-space', name: '员工空间', iconClass: 'fa-th-large' },
    { key: 'workflow-employee-stitch-full', name: '员工拼版', iconClass: 'fa-puzzle-piece' },
  ],
}

describe('SidebarMenuItem.vue', () => {
  it('shows "name · description" tooltip when description is present', () => {
    const wrapper = mount(SidebarMenuItem, {
      props: {
        item: {
          key: 'chat',
          name: '智能对话',
          iconClass: 'fa-comments-o',
          description: '找小C办事、下指令、看任务进度',
        },
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

      expect(wrapper.emitted('select-view')).toEqual([['workflow-employee-space']])
    } finally {
      vi.useRealTimers()
    }
  })

  it('emits parent-click when the top-level button is clicked', async () => {
    const wrapper = mount(SidebarMenuItem, {
      props: {
        item: { key: 'chat', name: '智能对话', iconClass: 'fa-comments-o' },
        activeView: 'chat',
      },
    })
    await wrapper.get('button.menu-item').trigger('click')
    expect(wrapper.emitted('parent-click')).toHaveLength(1)
  })

  it('emits reorder-pointer-down on pointerdown', async () => {
    const wrapper = mount(SidebarMenuItem, {
      props: {
        item: { key: 'chat', name: '智能对话', iconClass: 'fa-comments-o' },
        activeView: 'chat',
      },
    })
    await wrapper.get('button.menu-item').trigger('pointerdown')
    expect(wrapper.emitted('reorder-pointer-down')).toHaveLength(1)
  })

  it('emits keydown on keydown', async () => {
    const wrapper = mount(SidebarMenuItem, {
      props: {
        item: { key: 'chat', name: '智能对话', iconClass: 'fa-comments-o' },
        activeView: 'chat',
      },
    })
    await wrapper.get('button.menu-item').trigger('keydown', { key: 'Enter' })
    expect(wrapper.emitted('keydown')).toHaveLength(1)
  })

  it('shows IM unread badge when imUnreadTotal > 0', () => {
    const wrapper = mount(SidebarMenuItem, {
      props: {
        item: { key: 'im', name: '信息', iconClass: 'fa-comments' },
        activeView: 'im',
        imUnreadTotal: 5,
      },
    })
    const badge = wrapper.get('.menu-item-badge')
    expect(badge.text()).toBe('5')
    expect(badge.attributes('aria-label')).toBe('未读消息')
  })

  it('caps IM unread badge at 99+', () => {
    const wrapper = mount(SidebarMenuItem, {
      props: {
        item: { key: 'im', name: '信息', iconClass: 'fa-comments' },
        activeView: 'im',
        imUnreadTotal: 150,
      },
    })
    expect(wrapper.get('.menu-item-badge').text()).toBe('99+')
  })

  it('does not show IM unread badge when imUnreadTotal is 0', () => {
    const wrapper = mount(SidebarMenuItem, {
      props: {
        item: { key: 'im', name: '信息', iconClass: 'fa-comments' },
        activeView: 'im',
        imUnreadTotal: 0,
      },
    })
    expect(wrapper.find('.menu-item-badge').exists()).toBe(false)
  })

  it('renders submenu children when isExpanded is true', () => {
    const wrapper = mount(SidebarMenuItem, {
      props: {
        item: employeeWorkflowItem,
        activeView: 'chat',
        isExpanded: true,
      },
    })
    const children = wrapper.findAll('button.submenu-item')
    expect(children).toHaveLength(2)
    expect(children[0].attributes('data-view')).toBe('workflow-employee-space')
  })

  it('hides submenu when isExpanded is false', () => {
    const wrapper = mount(SidebarMenuItem, {
      props: {
        item: employeeWorkflowItem,
        activeView: 'chat',
        isExpanded: false,
      },
    })
    expect(wrapper.find('button.submenu-item').exists()).toBe(false)
  })

  it('sets aria-current to page when active and no active child', () => {
    const wrapper = mount(SidebarMenuItem, {
      props: {
        item: { key: 'chat', name: '智能对话', iconClass: 'fa-comments-o' },
        activeView: 'chat',
        isActive: true,
        hasActiveChild: false,
      },
    })
    expect(wrapper.get('button.menu-item').attributes('aria-current')).toBe('page')
  })

  it('omits aria-current when active but has active child', () => {
    const wrapper = mount(SidebarMenuItem, {
      props: {
        item: employeeWorkflowItem,
        activeView: 'workflow-employee-space',
        isActive: true,
        hasActiveChild: true,
        isExpanded: true,
      },
    })
    expect(wrapper.get('button.menu-item').attributes('aria-current')).toBeUndefined()
  })

  it('sets aria-expanded on parent when has children', () => {
    const wrapper = mount(SidebarMenuItem, {
      props: {
        item: employeeWorkflowItem,
        activeView: 'chat',
        isExpanded: true,
      },
    })
    expect(wrapper.get('button.menu-item').attributes('aria-expanded')).toBe('true')
  })

  it('child submenu button ignores non-primary button pointerup', async () => {
    const wrapper = mount(SidebarMenuItem, {
      props: {
        item: employeeWorkflowItem,
        activeView: 'printer-list',
        isExpanded: true,
      },
    })
    const child = wrapper.get('button.submenu-item[data-view="workflow-employee-space"]')
    await child.trigger('pointerup', { button: 2 }) // right click
    expect(wrapper.emitted('select-view')).toBeUndefined()
  })

  it('deduplicates rapid clicks within 80ms', async () => {
    vi.useFakeTimers()
    try {
      const wrapper = mount(SidebarMenuItem, {
        props: {
          item: employeeWorkflowItem,
          activeView: 'chat',
          isExpanded: true,
        },
      })
      const child = wrapper.get('button.submenu-item[data-view="workflow-employee-space"]')
      // First pointerup should emit
      await child.trigger('pointerup', { button: 0 })
      expect(wrapper.emitted('select-view')).toHaveLength(1)
      // Rapid second pointerup should be deduplicated (within 80ms)
      await child.trigger('pointerup', { button: 0 })
      expect(wrapper.emitted('select-view')).toHaveLength(1)
      // Advance past 80ms
      vi.advanceTimersByTime(100)
      await child.trigger('pointerup', { button: 0 })
      expect(wrapper.emitted('select-view')).toHaveLength(2)
    } finally {
      vi.useRealTimers()
    }
  })

  it('child click also activates via click event', async () => {
    vi.useFakeTimers()
    try {
      const wrapper = mount(SidebarMenuItem, {
        props: {
          item: employeeWorkflowItem,
          activeView: 'chat',
          isExpanded: true,
        },
      })
      const child = wrapper.get('button.submenu-item[data-view="workflow-employee-stitch-full"]')
      await child.trigger('click')
      expect(wrapper.emitted('select-view')).toEqual([['workflow-employee-stitch-full']])
    } finally {
      vi.useRealTimers()
    }
  })

  it('renders child tooltip with description when present', () => {
    const wrapper = mount(SidebarMenuItem, {
      props: {
        item: {
          key: 'parent',
          name: '父',
          iconClass: 'fa-parent',
          children: [{ key: 'child-1', name: '子', iconClass: 'fa-child', description: '子说明' }],
        },
        activeView: 'parent',
        isExpanded: true,
      },
    })
    const child = wrapper.get('button.submenu-item[data-view="child-1"]')
    expect(child.attributes('title')).toBe('子 · 子说明')
  })

  it('renders SidebarDragHoldProgress when pressing', () => {
    const wrapper = mount(SidebarMenuItem, {
      props: {
        item: { key: 'chat', name: '智能对话', iconClass: 'fa-comments-o' },
        activeView: 'chat',
        isPressing: true,
        longPressMs: 500,
      },
    })
    // SidebarDragHoldProgress is a child component
    expect(wrapper.findComponent({ name: 'SidebarDragHoldProgress' }).exists()).toBe(true)
  })
})
