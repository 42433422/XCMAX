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
})
