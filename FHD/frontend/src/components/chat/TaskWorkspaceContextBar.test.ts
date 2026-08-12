import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import TaskWorkspaceContextBar from './TaskWorkspaceContextBar.vue'

describe('TaskWorkspaceContextBar', () => {
  it('renders the canonical workspace state, unified progress and attention signals', async () => {
    const wrapper = mount(TaskWorkspaceContextBar, {
      props: {
        title: '客户B销售开票',
        status: 'waiting_user',
        stage: '等待审批',
        progress: 45,
        unreadCount: 1,
        approvalRequired: true,
        attempt: 2,
        runCount: 3,
        capabilities: { approve: true, pause: true, cancel: true },
      },
    })

    expect(wrapper.text()).toContain('客户B销售开票')
    expect(wrapper.text()).toContain('等待审批')
    expect(wrapper.text()).toContain('待审批')
    expect(wrapper.text()).toContain('1 未读')
    expect(wrapper.text()).toContain('第 2 次尝试 · 3 次运行')
    expect(wrapper.text()).toContain('审批并执行')
    expect(wrapper.text()).toContain('暂停')
    await wrapper.get('.chat-workspace-context__actions button').trigger('click')
    expect(wrapper.emitted('control')).toEqual([['approve']])
    expect(wrapper.get('[aria-label="客户B销售开票工作区统一进度"]').attributes('aria-valuenow')).toBe('45')
  })

  it('derives resume, retry and cancel controls from canonical status fallbacks', async () => {
    const paused = mount(TaskWorkspaceContextBar, {
      props: { title: '暂停任务', status: 'paused' },
    })
    expect(paused.text()).toContain('已暂停')
    expect(paused.text()).toContain('恢复')
    expect(paused.text()).toContain('取消')
    expect(paused.findAll('.chat-workspace-context__actions button').map((button) => button.text())).toEqual(['恢复', '取消'])
    await paused.findAll('.chat-workspace-context__actions button')[0].trigger('click')
    expect(paused.emitted('control')).toEqual([['resume']])

    const failed = mount(TaskWorkspaceContextBar, {
      props: { title: '失败任务', status: 'failed' },
    })
    expect(failed.text()).toContain('重试')
    expect(failed.findAll('.chat-workspace-context__actions button').map((button) => button.text())).toEqual(['重试'])
    await failed.findAll('.chat-workspace-context__actions button')[0].trigger('click')
    expect(failed.emitted('control')).toEqual([['retry']])
  })

  it('honors explicit disabled capabilities instead of status fallbacks', () => {
    const wrapper = mount(TaskWorkspaceContextBar, {
      props: {
        title: '已锁定工作区',
        status: 'waiting_user',
        capabilities: { approve: false, pause: false, cancel: false, resume: false, retry: false },
      },
    })

    expect(wrapper.find('.chat-workspace-context__actions').exists()).toBe(false)
    expect(wrapper.find('.chat-workspace-context__signals .is-approval').exists()).toBe(false)
    expect(wrapper.find('.chat-workspace-context__signals .is-unread').exists()).toBe(false)
  })
})
