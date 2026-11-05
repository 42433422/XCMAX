import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'
import WorkflowDemo from '@/components/workflow/WorkflowDemo.vue'

let wrapper: VueWrapper
function mountComponent() {
  wrapper = mount(WorkflowDemo)
  return wrapper
}

describe('WorkflowDemo', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.spyOn(console, 'log').mockImplementation(() => {})
  })
  afterEach(() => { wrapper?.unmount(); vi.restoreAllMocks() })

  it('renders the employee controls, both branch kinds, triggers and an empty log', () => {
    const wrapper = mountComponent()
    expect(wrapper.get('h2').text()).toBe('真实电话业务员工作流示例')
    expect(wrapper.findAll('h3').map(heading => heading.text())).toEqual(['员工开关控制', '工作流分支可视化', '状态日志'])
    const rows = wrapper.findAll('.workflow-employee-row')
    expect(rows.map(row => row.text())).toEqual(['真实电话业务员', '在线客服业务员', '邮件业务员'])
    expect(rows.map(row => row.attributes('aria-pressed'))).toEqual(['false', 'false', 'false'])
    const vm = wrapper.vm as any
    expect([vm.isRealPhoneActive, vm.isOnlineServiceActive, vm.isEmailServiceActive]).toEqual([false, false, false])
    expect(vm.logs).toEqual([])
    expect(wrapper.findAll('.log-entry')).toHaveLength(0)
    const cards = wrapper.findAll('.wf-viz-branch-card')
    expect(cards).toHaveLength(2)
    expect(cards[0].get('.wf-viz-kind-badge').text()).toBe('固定扩展')
    expect(cards[0].classes()).toContain('wf-viz-branch-card--fixed')
    expect(cards[1].get('.wf-viz-kind-badge').text()).toBe('动态扩展')
    expect(cards[1].classes()).not.toContain('wf-viz-branch-card--fixed')
    expect(vm.realPhoneTriggers).toHaveLength(4)
    expect(vm.realPhoneTriggers[0]).toMatchObject({ id: 'adb_check', type: 'fixed' })
    expect(vm.onlineServiceTriggers).toHaveLength(2)
    expect(vm.onlineServiceTriggers[0].type).toBe('dynamic')
    expect(cards[0].get('.wf-viz-branch-triggers').text()).toContain('ADB 设备连通检查')
  })

  it('toggles each employee on and off through its control and logs the real-phone identity', async () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    for (const [index, field] of ['isRealPhoneActive', 'isOnlineServiceActive', 'isEmailServiceActive'].entries()) {
      const row = wrapper.findAll('.workflow-employee-row')[index]
      await row.trigger('click')
      expect(vm[field]).toBe(true)
      expect(row.attributes('aria-pressed')).toBe('true')
      expect(vm.logs.map((log: { message: string }) => log.message)).toContain('员工状态变更：启用')
      if (index === 0) expect(vm.logs[0].message).toBe('员工切换：real_phone -> 启用')
      await row.trigger('click')
      expect(vm[field]).toBe(false)
      expect(row.attributes('aria-pressed')).toBe('false')
      expect(vm.logs.map((log: { message: string }) => log.message)).toContain('员工状态变更：禁用')
      if (index === 0) expect(vm.logs[0].message).toBe('员工切换：real_phone -> 禁用')
    }
    expect(vm.logs).toHaveLength(8)
  })

  it('keeps newest log entries first, with rendered timestamps and exact event details', async () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    vm.handleEmployeeChange(true)
    vm.handleEmployeeToggle({ employeeId: 'email_service', active: false })
    await nextTick()
    expect(vm.logs.map((log: { message: string }) => log.message)).toEqual(['员工切换：email_service -> 禁用', '员工状态变更：启用'])
    const entries = wrapper.findAll('.log-entry')
    expect(entries).toHaveLength(2)
    expect(entries.map(entry => entry.get('.log-message').text())).toEqual(vm.logs.map((log: { message: string }) => log.message))
    expect(entries[0].get('.log-time').text()).toMatch(/^\d{1,2}:\d{2}:\d{2}$/)
    expect(vm.logs[0].time).toBe(entries[0].get('.log-time').text())
    vm.handleEmployeeChange(false)
    vm.handleEmployeeToggle({ employeeId: 'real_phone', active: true })
    await nextTick()
    expect(vm.logs.slice(0, 2).map((log: { message: string }) => log.message)).toEqual(['员工切换：real_phone -> 启用', '员工状态变更：禁用'])
  })

  it('dispatches configure and view-details from both branches with the selected branch identity', async () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    for (const [index, branchId] of ['real_phone', 'online_service'].entries()) {
      const buttons = wrapper.findAll('.wf-viz-branch-card')[index].findAll('.wf-viz-action-btn')
      await buttons[0].trigger('click')
      expect(vm.logs[0].message).toBe(`配置分支：${branchId}`)
      expect(console.log).toHaveBeenLastCalledWith('Configure branch:', branchId)
      await buttons[1].trigger('click')
      expect(vm.logs[0].message).toBe(`查看详情：${branchId}`)
      expect(console.log).toHaveBeenLastCalledWith('View details:', branchId)
    }
    expect(vm.logs).toHaveLength(4)
  })
})
