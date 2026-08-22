import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AgentTaskRuntimePanel from './AgentTaskRuntimePanel.vue'

const task = {
  id: 'agent_task_task-1',
  type: 'agent_task',
  title: '月度库存核对',
  source: 'agent' as const,
  status: 'running' as const,
  startedAt: 1,
  updatedAt: 2,
  payload: {
    runCount: 2,
    attempt: 2,
    workspaceId: 'inventory-workspace',
    workspaceIsolation: 'business_workspace',
    artifactCount: 1,
    steps: [{ step_id: 'step-1', tool_id: 'business_db', action: 'read', status: 'running' }],
    toolCalls: [{ call_id: 'call-1', tool_id: 'business_db', action: 'read', status: 'running' }],
  },
}

describe('AgentTaskRuntimePanel', () => {
  const mountTask = (overrides: Record<string, unknown> = {}) =>
    mount(AgentTaskRuntimePanel, {
      props: { task: { ...task, ...overrides } },
      global: { mocks: { $t: (key: string) => key } },
    })

  it('shows traceable runtime details and controls the exact task', async () => {
    const wrapper = mountTask()

    expect(wrapper.text()).toContain('inventory-workspace')
    expect(wrapper.text()).toContain('business_db.read')
    expect(wrapper.text()).toContain('chat.toolSessions')

    const buttons = wrapper.findAll('button')
    await buttons.find((button) => button.text() === 'chat.openTask')!.trigger('click')
    await buttons.find((button) => button.text() === 'chat.pauseTask')!.trigger('click')
    await buttons.find((button) => button.text() === 'chat.cancel')!.trigger('click')
    expect(wrapper.emitted('open')).toHaveLength(1)
    expect(wrapper.emitted('pause')).toHaveLength(1)
    expect(wrapper.emitted('cancel')).toHaveLength(1)
  })

  it('keeps an empty completed task compact and uses counter defaults', () => {
    const wrapper = mountTask({ status: 'success', payload: {} })

    expect(wrapper.find('.agent-task-workspace').exists()).toBe(false)
    expect(wrapper.find('.agent-task-steps').exists()).toBe(false)
    expect(wrapper.find('.agent-tool-sessions').exists()).toBe(false)
    expect(wrapper.find('.agent-task-evidence').text()).toContain('结果证据：0 条事件')
    expect(wrapper.findAll('button').map((button) => button.text())).toEqual(['chat.openTask'])
  })

  it('renders payload fallbacks, every step label, durations, and paused controls', async () => {
    const wrapper = mountTask({
      status: 'paused',
      payload: {
        runCount: 0,
        attempt: 0,
        workspacePath: '/tmp/task-worktree',
        steps: [
          { step_id: 'pending', tool_id: 'repo', action: 'inspect' },
          { step_id: 'running', description: '执行工具', status: 'running' },
          { step_id: 'retrying', description: '重试工具', status: 'retrying' },
          { step_id: 'waiting', description: '等待确认', status: 'waiting_user' },
          { step_id: 'completed', description: '完成工具', status: 'completed' },
          { step_id: 'failed', description: '失败工具', status: 'failed' },
          { step_id: 'skipped', description: '跳过工具', status: 'skipped' },
          { step_id: 'unknown', description: '未知状态', status: 'unknown' },
        ],
        toolCalls: [
          {
            call_id: 'timed',
            tool_id: 'terminal',
            action: 'test',
            status: 'completed',
            duration_ms: 42,
          },
        ],
        artifactCount: 0,
      },
    })

    expect(wrapper.text()).toContain('/tmp/task-worktree')
    expect(wrapper.text()).toContain('business_workspace')
    expect(wrapper.text()).toContain('repo.inspect')
    expect(wrapper.text()).toContain('待执行')
    expect(wrapper.text()).toContain('重试中')
    expect(wrapper.text()).toContain('等待确认')
    expect(wrapper.text()).toContain('已完成')
    expect(wrapper.text()).toContain('失败')
    expect(wrapper.text()).toContain('已跳过')
    expect(wrapper.text()).toContain('42ms')

    const buttons = wrapper.findAll('button')
    await buttons.find((button) => button.text() === 'chat.resumeTask')!.trigger('click')
    await buttons.find((button) => button.text() === 'chat.cancel')!.trigger('click')
    expect(wrapper.emitted('resume')).toHaveLength(1)
    expect(wrapper.emitted('cancel')).toHaveLength(1)
  })

  it.each(['failed', 'cancelled', 'blocked'] as const)('offers a retry for %s tasks', async (status) => {
    const wrapper = mountTask({ status, payload: null })
    const retry = wrapper.findAll('button').find((button) => button.text() === 'chat.retryTask')

    expect(retry).toBeDefined()
    await retry!.trigger('click')
    expect(wrapper.emitted('retry')).toHaveLength(1)
    expect(wrapper.findAll('button').some((button) => button.text() === 'chat.cancel')).toBe(status === 'blocked')
  })

  it('offers a real approval action only at the waiting checkpoint', async () => {
    const wrapper = mountTask({
      status: 'blocked',
      payload: {
        rawRunStatus: 'waiting_user',
        capabilities: { approve: true, pause: true, cancel: true },
      },
    })
    const approval = wrapper.findAll('button').find((button) => button.text() === '审批并执行')

    expect(approval).toBeDefined()
    await approval!.trigger('click')
    expect(wrapper.emitted('approve')).toHaveLength(1)
  })

  it('exposes persisted result output and artifact identity as evidence', () => {
    const wrapper = mountTask({
      status: 'success',
      payload: {
        eventCount: 8,
        completedToolCount: 1,
        artifactCount: 1,
        finalOutput: { node_outputs: { shipment: { success: true, order_id: 41 } } },
        artifacts: [{ artifact_id: 'art-1', name: 'shipment-41.docx', uri: '/tmp/shipment-41.docx' }],
      },
    })

    expect(wrapper.text()).toContain('8 条事件')
    expect(wrapper.text()).toContain('shipment-41.docx')
    expect(wrapper.find('.agent-result-evidence pre').text()).toContain('"order_id": 41')
  })

  it('shows a beginner-readable business result before optional technical JSON', () => {
    const wrapper = mountTask({
      status: 'success',
      payload: {
        eventCount: 4,
        completedToolCount: 1,
        finalOutput: {
          chat_payload: { success: true, response: '当前客户库暂无数据。' },
          node_outputs: { customers: { success: true, data: [] } },
        },
      },
    })

    expect(wrapper.find('.agent-result-summary').text()).toContain('业务结果')
    expect(wrapper.find('.agent-result-summary').text()).toContain('当前客户库暂无数据。')
    expect(wrapper.find('.agent-result-evidence summary').text()).toBe('技术明细（高级）')
    expect(wrapper.find('.agent-result-evidence').attributes('open')).toBeUndefined()
  })

  it('renders the canonical Business Harness summary and facts before raw node output', () => {
    const wrapper = mountTask({
      status: 'success',
      payload: {
        finalOutput: {
          business_result: {
            status: 'completed',
            summary: '订单创建成功',
            facts: { order_id: 41, order_number: 'SO-0041' },
          },
          node_outputs: { order: { message: '内部节点文本' } },
        },
      },
    })

    const summary = wrapper.find('.agent-result-summary').text()
    expect(summary).toContain('订单创建成功')
    expect(summary).toContain('订单 ID：41')
    expect(summary).toContain('业务单号：SO-0041')
    expect(summary).not.toContain('内部节点文本')
  })
})
