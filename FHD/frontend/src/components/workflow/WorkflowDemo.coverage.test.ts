import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'

import WorkflowDemo from '@/components/workflow/WorkflowDemo.vue'

function mountComponent() {
  return mount(WorkflowDemo)
}

describe('WorkflowDemo.coverage', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.spyOn(console, 'log').mockImplementation(() => {})
  })

  it('renders main heading', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('h2').text()).toBe('真实电话业务员工作流示例')
  })

  it('renders employee switch control section', () => {
    const wrapper = mountComponent()
    const headings = wrapper.findAll('h3')
    expect(headings[0].text()).toBe('员工开关控制')
  })

  it('renders workflow branch visualization section', () => {
    const wrapper = mountComponent()
    const headings = wrapper.findAll('h3')
    expect(headings[1].text()).toBe('工作流分支可视化')
  })

  it('renders status log section', () => {
    const wrapper = mountComponent()
    const headings = wrapper.findAll('h3')
    expect(headings[2].text()).toBe('状态日志')
  })

  it('renders three employee rows', () => {
    const wrapper = mountComponent()
    const rows = wrapper.findAll('.workflow-employee-row')
    expect(rows.length).toBe(3)
  })

  it('renders real phone employee with correct label', () => {
    const wrapper = mountComponent()
    const rows = wrapper.findAll('.workflow-employee-row')
    expect(rows[0].text()).toContain('真实电话业务员')
  })

  it('renders online service employee with correct label', () => {
    const wrapper = mountComponent()
    const rows = wrapper.findAll('.workflow-employee-row')
    expect(rows[1].text()).toContain('在线客服业务员')
  })

  it('renders email service employee with correct label', () => {
    const wrapper = mountComponent()
    const rows = wrapper.findAll('.workflow-employee-row')
    expect(rows[2].text()).toContain('邮件业务员')
  })

  it('renders two branch cards', () => {
    const wrapper = mountComponent()
    const cards = wrapper.findAll('.wf-viz-branch-card')
    expect(cards.length).toBe(2)
  })

  it('renders real phone branch card with fixed badge', () => {
    const wrapper = mountComponent()
    const cards = wrapper.findAll('.wf-viz-branch-card')
    expect(cards[0].find('.wf-viz-kind-badge').text()).toBe('固定扩展')
    expect(cards[0].classes()).toContain('wf-viz-branch-card--fixed')
  })

  it('renders online service branch card with dynamic badge', () => {
    const wrapper = mountComponent()
    const cards = wrapper.findAll('.wf-viz-branch-card')
    expect(cards[1].find('.wf-viz-kind-badge').text()).toBe('动态扩展')
    expect(cards[1].classes()).not.toContain('wf-viz-branch-card--fixed')
  })

  it('initializes all employee toggles as inactive', () => {
    const wrapper = mountComponent()
    expect((wrapper.vm as any).isRealPhoneActive).toBe(false)
    expect((wrapper.vm as any).isOnlineServiceActive).toBe(false)
    expect((wrapper.vm as any).isEmailServiceActive).toBe(false)
  })

  it('initializes logs as empty', () => {
    const wrapper = mountComponent()
    expect((wrapper.vm as any).logs).toEqual([])
    expect(wrapper.findAll('.log-entry').length).toBe(0)
  })

  it('handleEmployeeChange adds a log entry with enable message', async () => {
    const wrapper = mountComponent()
    ;(wrapper.vm as any).handleEmployeeChange(true)
    await nextTick()
    expect((wrapper.vm as any).logs.length).toBe(1)
    expect((wrapper.vm as any).logs[0].message).toContain('启用')
  })

  it('handleEmployeeChange adds a log entry with disable message', async () => {
    const wrapper = mountComponent()
    ;(wrapper.vm as any).handleEmployeeChange(false)
    await nextTick()
    expect((wrapper.vm as any).logs[0].message).toContain('禁用')
  })

  it('handleEmployeeToggle adds a log with employeeId and active state', async () => {
    const wrapper = mountComponent()
    ;(wrapper.vm as any).handleEmployeeToggle({ employeeId: 'real_phone', active: true })
    await nextTick()
    expect((wrapper.vm as any).logs[0].message).toContain('real_phone')
    expect((wrapper.vm as any).logs[0].message).toContain('启用')
  })

  it('handleEmployeeToggle adds a log with disable state', async () => {
    const wrapper = mountComponent()
    ;(wrapper.vm as any).handleEmployeeToggle({ employeeId: 'online_service', active: false })
    await nextTick()
    expect((wrapper.vm as any).logs[0].message).toContain('online_service')
    expect((wrapper.vm as any).logs[0].message).toContain('禁用')
  })

  it('handleBranchConfigure adds a log and calls console.log', async () => {
    const wrapper = mountComponent()
    ;(wrapper.vm as any).handleBranchConfigure({ branchId: 'real_phone' })
    await nextTick()
    expect((wrapper.vm as any).logs[0].message).toContain('配置分支')
    expect((wrapper.vm as any).logs[0].message).toContain('real_phone')
    expect(console.log).toHaveBeenCalledWith('Configure branch:', 'real_phone')
  })

  it('handleBranchViewDetails adds a log and calls console.log', async () => {
    const wrapper = mountComponent()
    ;(wrapper.vm as any).handleBranchViewDetails({ branchId: 'online_service' })
    await nextTick()
    expect((wrapper.vm as any).logs[0].message).toContain('查看详情')
    expect((wrapper.vm as any).logs[0].message).toContain('online_service')
    expect(console.log).toHaveBeenCalledWith('View details:', 'online_service')
  })

  it('clicking real phone employee toggle activates it and logs', async () => {
    const wrapper = mountComponent()
    const rows = wrapper.findAll('.workflow-employee-row')
    await rows[0].trigger('click')
    expect((wrapper.vm as any).isRealPhoneActive).toBe(true)
    expect((wrapper.vm as any).logs.length).toBeGreaterThanOrEqual(1)
  })

  it('clicking real phone employee toggle emits toggle event with employeeId', async () => {
    const wrapper = mountComponent()
    const rows = wrapper.findAll('.workflow-employee-row')
    await rows[0].trigger('click')
    const logMessages = (wrapper.vm as any).logs.map((l: any) => l.message)
    expect(logMessages.some((m: string) => m.includes('real_phone'))).toBe(true)
  })

  it('clicking online service employee toggle activates it', async () => {
    const wrapper = mountComponent()
    const rows = wrapper.findAll('.workflow-employee-row')
    await rows[1].trigger('click')
    expect((wrapper.vm as any).isOnlineServiceActive).toBe(true)
  })

  it('clicking email service employee toggle activates it', async () => {
    const wrapper = mountComponent()
    const rows = wrapper.findAll('.workflow-employee-row')
    await rows[2].trigger('click')
    expect((wrapper.vm as any).isEmailServiceActive).toBe(true)
  })

  it('clicking configure button on first branch card logs configure', async () => {
    const wrapper = mountComponent()
    const cards = wrapper.findAll('.wf-viz-branch-card')
    const configureBtn = cards[0].findAll('.wf-viz-action-btn')[0]
    await configureBtn.trigger('click')
    expect((wrapper.vm as any).logs[0].message).toContain('配置分支')
    expect((wrapper.vm as any).logs[0].message).toContain('real_phone')
  })

  it('clicking view details button on first branch card logs view details', async () => {
    const wrapper = mountComponent()
    const cards = wrapper.findAll('.wf-viz-branch-card')
    const viewBtn = cards[0].findAll('.wf-viz-action-btn')[1]
    await viewBtn.trigger('click')
    expect((wrapper.vm as any).logs[0].message).toContain('查看详情')
  })

  it('clicking configure button on second branch card logs online_service', async () => {
    const wrapper = mountComponent()
    const cards = wrapper.findAll('.wf-viz-branch-card')
    const configureBtn = cards[1].findAll('.wf-viz-action-btn')[0]
    await configureBtn.trigger('click')
    expect((wrapper.vm as any).logs[0].message).toContain('online_service')
  })

  it('logs are prepended (newest first)', async () => {
    const wrapper = mountComponent()
    ;(wrapper.vm as any).handleEmployeeChange(true)
    await nextTick()
    ;(wrapper.vm as any).handleEmployeeToggle({ employeeId: 'email_service', active: false })
    await nextTick()
    expect((wrapper.vm as any).logs.length).toBe(2)
    expect((wrapper.vm as any).logs[0].message).toContain('email_service')
    expect((wrapper.vm as any).logs[1].message).toContain('员工状态变更')
  })

  it('log entries render time and message in DOM', async () => {
    const wrapper = mountComponent()
    ;(wrapper.vm as any).handleEmployeeChange(true)
    await nextTick()
    const entries = wrapper.findAll('.log-entry')
    expect(entries.length).toBe(1)
    expect(entries[0].find('.log-time').exists()).toBe(true)
    expect(entries[0].find('.log-message').text()).toContain('启用')
  })

  it('realPhoneTriggers has 4 triggers', () => {
    const wrapper = mountComponent()
    expect((wrapper.vm as any).realPhoneTriggers.length).toBe(4)
  })

  it('onlineServiceTriggers has 2 triggers', () => {
    const wrapper = mountComponent()
    expect((wrapper.vm as any).onlineServiceTriggers.length).toBe(2)
  })

  it('realPhoneTriggers first trigger is adb_check', () => {
    const wrapper = mountComponent()
    expect((wrapper.vm as any).realPhoneTriggers[0].id).toBe('adb_check')
    expect((wrapper.vm as any).realPhoneTriggers[0].type).toBe('fixed')
  })

  it('onlineServiceTriggers has dynamic type', () => {
    const wrapper = mountComponent()
    expect((wrapper.vm as any).onlineServiceTriggers[0].type).toBe('dynamic')
  })

  it('first branch card renders triggers slot content', () => {
    const wrapper = mountComponent()
    const cards = wrapper.findAll('.wf-viz-branch-card')
    expect(cards[0].find('.wf-viz-branch-triggers').text()).toContain('ADB 设备连通检查')
  })

  it('addLog creates log entry with time string', async () => {
    const wrapper = mountComponent()
    ;(wrapper.vm as any).handleEmployeeChange(true)
    await nextTick()
    const log = (wrapper.vm as any).logs[0]
    expect(log.time).toBeTruthy()
    expect(typeof log.time).toBe('string')
  })

  it('toggling employee off then on logs both states', async () => {
    const wrapper = mountComponent()
    const rows = wrapper.findAll('.workflow-employee-row')
    await rows[0].trigger('click')
    await rows[0].trigger('click')
    expect((wrapper.vm as any).isRealPhoneActive).toBe(false)
    expect((wrapper.vm as any).logs.length).toBeGreaterThanOrEqual(2)
  })
})
