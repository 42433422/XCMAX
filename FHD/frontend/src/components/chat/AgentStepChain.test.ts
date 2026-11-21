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
    expect(wrapper.text()).toContain('工具步骤')
    expect(wrapper.text()).toContain('2 步')
    expect(wrapper.text()).toContain('已完成')
    expect(wrapper.text()).toContain('320ms')
  })

  it('执行中自动展开，完成后自动收起', async () => {
    const wrapper = mount(AgentStepChain, { props: { steps: [step({ live: true, state: 'running' })] } })
    expect(wrapper.find('button.asc-summary').attributes('aria-expanded')).toBe('true')
    await wrapper.setProps({ steps: [step()] })
    expect(wrapper.find('button.asc-summary').attributes('aria-expanded')).toBe('false')
  })

  it('带详情的步骤可展开查看输出与错误', async () => {
    const wrapper = mount(AgentStepChain, {
      props: {
        steps: [step({ state: 'failed', error: '文件被占用', hint: '关闭 Excel 后重试', output: undefined })],
      },
    })
    const trigger = wrapper.get('button.asc-step-row')
    expect(trigger.attributes('type')).toBe('button')
    expect(trigger.attributes('aria-expanded')).toBe('false')
    expect(wrapper.text()).not.toContain('文件被占用')
    await trigger.trigger('click')
    expect(trigger.attributes('aria-expanded')).toBe('true')
    expect(wrapper.get(`[id="${trigger.attributes('aria-controls')}"]`).exists()).toBe(true)
    expect(wrapper.text()).toContain('错误')
    expect(wrapper.text()).toContain('文件被占用')
    expect(wrapper.text()).toContain('关闭 Excel 后重试')
    expect(wrapper.get('button.asc-summary').attributes('aria-expanded')).toBe('true')
  })

  it('无详情的步骤渲染为静态行，不出现折叠箭头', async () => {
    const wrapper = mount(AgentStepChain, { props: { steps: [step()] } })
    await wrapper.get('button.asc-summary').trigger('click')
    expect(wrapper.findAll('.asc-step-details')).toHaveLength(0)
    expect(wrapper.find('.asc-step-row.is-static').exists()).toBe(true)
  })

  it('失败链路默认展开并显示失败状态', () => {
    const wrapper = mount(AgentStepChain, { props: { steps: [step({ state: 'failed', error: 'boom' })] } })
    expect(wrapper.text()).toContain('失败')
    expect(wrapper.find('button.asc-summary').attributes('aria-expanded')).toBe('true')
  })

  it('流式状态变化保留用户选择的展开状态', async () => {
    const wrapper = mount(AgentStepChain, { props: { steps: [step({ state: 'running' })] } })
    const trigger = wrapper.get('button.asc-summary')
    await trigger.trigger('click')
    await wrapper.setProps({ steps: [step({ state: 'running', hint: '正在写入下一批' })] })
    expect(trigger.attributes('aria-expanded')).toBe('false')
    await trigger.trigger('click')
    await wrapper.setProps({ steps: [step()] })
    expect(trigger.attributes('aria-expanded')).toBe('true')
  })

  it('实时说明直接可见，只在有真实数值时显示进度条，零进度有效', async () => {
    const running = step({ state: 'running', hint: '正在读取数据' })
    const wrapper = mount(AgentStepChain, { props: { steps: [running] } })
    expect(wrapper.get('.asc-live-hint').text()).toBe('正在读取数据')
    expect(wrapper.find('progress').exists()).toBe(false)
    expect(wrapper.find('.asc-step-details').exists()).toBe(false)

    await wrapper.setProps({ steps: [{ ...running, progress: 0 }] })
    expect(wrapper.get('progress').attributes('value')).toBe('0')
    await wrapper.setProps({ steps: [{ ...running, progress: 50, processedRows: 120, totalRows: 240 }] })
    expect(wrapper.get('progress').attributes('value')).toBe('50')
    expect(wrapper.get('progress').attributes('max')).toBe('100')
    expect(wrapper.text()).toContain('已处理 120 / 240 行')
  })

  it('结果未知时直接展示待核对说明，停止占位图标旋转', () => {
    const wrapper = mount(AgentStepChain, {
      props: { steps: [step({ state: 'unknown', live: true, hint: '执行结果待核对' })] },
    })
    expect(wrapper.get('button.asc-summary').attributes('aria-expanded')).toBe('true')
    expect(wrapper.get('.asc-pill').text()).toBe('待核对')
    expect(wrapper.get('.asc-live-hint').text()).toBe('执行结果待核对')
    expect(wrapper.find('.fa-spin').exists()).toBe(false)
    expect(wrapper.find('.asc-step-details').exists()).toBe(false)
  })
})
