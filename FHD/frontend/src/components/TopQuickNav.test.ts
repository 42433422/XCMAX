import { computed, ref } from 'vue'
import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import TopQuickNav from './TopQuickNav.vue'

const navItems = vi.hoisted(() => [
  { key: 'chat', name: '智能对话', routeName: 'chat', source: 'core', iconClass: 'fa-comments-o' },
  { key: 'im', name: '信息', routeName: 'im', source: 'core', iconClass: 'fa-envelope-o' },
  { key: 'orders', name: '订单管理', routeName: 'orders', source: 'core', iconClass: 'fa-file-text-o' },
  { key: 'customers', name: '客户管理', routeName: 'customers', source: 'core', iconClass: 'fa-users' },
  {
    key: 'workflow-employee-space',
    name: '员工空间',
    routeName: 'workflow-employee-space',
    source: 'child',
    iconClass: 'fa-th-large',
    parentKey: 'employee-workflow',
  },
  { key: 'settings', name: '系统设置', routeName: 'settings', source: 'settings', iconClass: 'fa-cog' },
])

vi.mock('@/composables/useVisibleNavItems', () => ({
  useVisibleNavItems: () => ({
    menuItems: ref([]),
    visibleNavItems: computed(() => navItems),
    coreMenuOverrides: computed(() => new Map()),
  }),
}))

async function mountNav() {
  const wrapper = mount(TopQuickNav, {
    attachTo: document.body,
  })
  await wrapper.find('input').trigger('focus')
  return wrapper
}

const optionNames = (wrapper) => wrapper.findAll('.top-quick-nav__option').map((node) => node.text())

describe('TopQuickNav', () => {
  it('聚焦后展示全部侧边栏入口', async () => {
    const wrapper = await mountNav()
    const names = optionNames(wrapper)
    expect(names).toContain('智能对话')
    expect(names).toContain('订单管理')
    expect(names).toContain('员工空间')
    expect(names).toContain('系统设置')
    wrapper.unmount()
  })

  it('按关键词过滤功能名', async () => {
    const wrapper = await mountNav()
    await wrapper.find('input').setValue('订单')
    expect(optionNames(wrapper)).toEqual(['订单管理'])
    await wrapper.find('input').setValue('不存在的东西')
    expect(wrapper.find('.top-quick-nav__empty').exists()).toBe(true)
    wrapper.unmount()
  })

  it('回车选中高亮项并 emit select', async () => {
    const wrapper = await mountNav()
    await wrapper.find('input').setValue('客户')
    await wrapper.find('input').trigger('keydown', { key: 'Enter' })
    expect(wrapper.emitted('select')).toEqual([['customers']])
    expect((wrapper.find('input').element as HTMLInputElement).value).toBe('')
    wrapper.unmount()
  })

  it('方向键移动高亮，Escape 关闭下拉', async () => {
    const wrapper = await mountNav()
    const input = wrapper.find('input')
    await input.trigger('keydown', { key: 'ArrowDown' })
    await input.trigger('keydown', { key: 'ArrowDown' })
    const highlighted = wrapper.findAll('.top-quick-nav__option').findIndex((node) => node.classes().includes('highlighted'))
    expect(highlighted).toBe(2)
    await input.trigger('keydown', { key: 'Escape' })
    expect(wrapper.find('.top-quick-nav__list').exists()).toBe(false)
    wrapper.unmount()
  })

  it('点击选项 emit select 并收起下拉', async () => {
    const wrapper = await mountNav()
    const options = wrapper.findAll('.top-quick-nav__option')
    const target = options.find((node) => node.text().includes('系统设置'))
    await target.trigger('mousedown')
    expect(wrapper.emitted('select')).toEqual([['settings']])
    expect(wrapper.find('.top-quick-nav__list').exists()).toBe(false)
    wrapper.unmount()
  })
})
