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
  it('shows traceable runtime details and controls the exact task', async () => {
    const wrapper = mount(AgentTaskRuntimePanel, {
      props: { task },
      global: { mocks: { $t: (key: string) => key } },
    })

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
})
