import { expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import TaskExecutionGraph from './TaskExecutionGraph.vue'
const fitView = vi.hoisted(() => vi.fn())
vi.mock('@vue-flow/core', () => ({
  useVueFlow: () => ({ fitView }),
  VueFlow: { name: 'VueFlow', props: ['nodes', 'edges'], emits: ['node-click'], template: '<div><slot /></div>' },
}))
vi.mock('@vue-flow/background', () => ({ Background: { template: '<div />' } }))
vi.mock('@vue-flow/controls', () => ({ Controls: { template: '<div />' } }))
vi.mock('@vue-flow/minimap', () => ({ MiniMap: { template: '<div />' } }))
it('renders persisted graph, reveals selected failures and fits changed topology', async () => {
  const step = { step_id: 'one', tool_id: 'employee', action: 'execute', status: 'failed', error: '真实失败' }
  const wrapper = mount(TaskExecutionGraph, { props: { runId: 'run', steps: [step] } })
  const flow = wrapper.findComponent({ name: 'VueFlow' })
  expect(flow.props('nodes')).toHaveLength(1)
  expect(wrapper.find('.execution-node-detail').exists()).toBe(false)
  flow.vm.$emit('node-click', { node: { id: 'one' } })
  await flushPromises()
  expect(wrapper.get('[role="alert"]').text()).toBe('真实失败')
  expect(wrapper.get('.execution-node-detail').text()).toContain('employee')
  await wrapper.setProps({ steps: [{ ...step, node_id: 'two', description: '新步骤', error: '' }] })
  await flushPromises()
  expect(fitView).toHaveBeenCalledWith({ padding: 0.3, maxZoom: 1 })
  expect(wrapper.find('.execution-node-detail').exists()).toBe(false)
  flow.vm.$emit('node-click', { node: { id: 'two' } })
  await flushPromises()
  expect(wrapper.get('.execution-node-detail').text()).toContain('新步骤')
  expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  wrapper.unmount()
})
