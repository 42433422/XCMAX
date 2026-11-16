import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AgentStepChain from './AgentStepChain.vue'
import type { AgentStepView } from '@/utils/agentStepChain'

function step(overrides: Partial<AgentStepView> = {}): AgentStepView {
  return {
    id: 'n1',
    toolId: 'business_db',
    action: 'query',
    title: '业务数据库',
    subtitle: '查询',
    state: 'success',
    retries: 0,
    live: false,
    ...overrides,
  }
}

describe('AgentStepChain', () => {
  it('渲染步骤数、状态与耗时', () => {
    const wrapper = mount(AgentStepChain, {
      props: { steps: [step({ durationMs: 320 }), step({ id: 'n2', title: '表格' })] },
    })
    expect(wrapper.text()).toContain('执行链')
    expect(wrapper.text()).toContain('2 步')
    expect(wrapper.text()).toContain('已完成')
    expect(wrapper.text()).toContain('320ms')
  })

  it('执行中自动展开，完成后自动收起', async () => {
    const wrapper = mount(AgentStepChain, { props: { steps: [step({ live: true, state: 'running' })] } })
    expect(wrapper.find('details.asc-chain').attributes('open')).toBeDefined()
    await wrapper.setProps({ steps: [step()] })
    expect(wrapper.find('details.asc-chain').attributes('open')).toBeUndefined()
  })

  it('带详情的步骤可展开查看输出与错误', async () => {
    const wrapper = mount(AgentStepChain, {
      props: {
        steps: [step({ state: 'failed', error: '文件被占用', hint: '关闭 Excel 后重试', output: undefined })],
      },
    })
    expect(wrapper.findAll('details.asc-step-details')).toHaveLength(1)
    await wrapper.find('details.asc-step-details').trigger('toggle')
    expect(wrapper.text()).toContain('错误')
  })

  it('无详情的步骤渲染为静态行，不出现折叠箭头', () => {
    const wrapper = mount(AgentStepChain, { props: { steps: [step()] } })
    expect(wrapper.findAll('details.asc-step-details')).toHaveLength(0)
    expect(wrapper.find('.asc-step-row.is-static').exists()).toBe(true)
  })

  it('失败链路默认展开并显示失败状态', () => {
    const wrapper = mount(AgentStepChain, { props: { steps: [step({ state: 'failed', error: 'boom' })] } })
    expect(wrapper.text()).toContain('失败')
    expect(wrapper.find('details.asc-chain').attributes('open')).toBeDefined()
  })
})
