import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ToolInvocationPills from './ToolInvocationPills.vue'

describe('ToolInvocationPills', () => {
  it('renders nothing when content is undefined/empty', () => {
    const wrapper = mount(ToolInvocationPills)
    expect(wrapper.find('.tool-invocation-summary').exists()).toBe(false)
  })

  it('renders nothing when content has no tool invocation JSON', () => {
    const wrapper = mount(ToolInvocationPills, {
      props: { content: '普通文本消息，没有工具调用' },
    })
    expect(wrapper.find('.tool-invocation-summary').exists()).toBe(false)
  })

  it('renders a chip when content contains a tool invocation JSON line', () => {
    const json = JSON.stringify({ action: 'read', tool_id: 'excel_reader', file_path: '/tmp/a.xlsx' })
    const wrapper = mount(ToolInvocationPills, {
      props: { content: json },
    })
    expect(wrapper.find('.tool-invocation-summary').exists()).toBe(true)
    expect(wrapper.findAll('.context-summary__chip').length).toBeGreaterThan(0)
  })

  it('renders the label "工具"', () => {
    const json = JSON.stringify({ action: 'read', tool_id: 'excel_reader', file_path: '/tmp/a.xlsx' })
    const wrapper = mount(ToolInvocationPills, { props: { content: json } })
    expect(wrapper.find('.context-summary__label').text()).toContain('工具')
  })

  it('renders chip with label and detail when both are present', () => {
    const json = JSON.stringify({ action: 'read', file_path: '/tmp/report.xlsx' })
    const wrapper = mount(ToolInvocationPills, { props: { content: json } })
    const chip = wrapper.find('.context-summary__chip')
    expect(chip.exists()).toBe(true)
    expect(chip.text()).toContain('report.xlsx')
  })

  it('renders multiple chips for multiple tool invocation lines', () => {
    const line1 = JSON.stringify({ action: 'read', file_path: '/tmp/a.xlsx' })
    const line2 = JSON.stringify({ action: 'write', file_path: '/tmp/b.csv' })
    const wrapper = mount(ToolInvocationPills, {
      props: { content: `${line1}\n${line2}` },
    })
    expect(wrapper.findAll('.context-summary__chip')).toHaveLength(2)
  })

  it('deduplicates identical chips', () => {
    const line = JSON.stringify({ action: 'read', file_path: '/tmp/a.xlsx' })
    const wrapper = mount(ToolInvocationPills, {
      props: { content: `${line}\n${line}` },
    })
    expect(wrapper.findAll('.context-summary__chip')).toHaveLength(1)
  })

  it('sets title attribute on chip for tooltip', () => {
    const json = JSON.stringify({ action: 'read', file_path: '/tmp/a.xlsx' })
    const wrapper = mount(ToolInvocationPills, { props: { content: json } })
    const chip = wrapper.find('.context-summary__chip')
    expect(chip.attributes('title')).toBeTruthy()
  })

  it('renders svg icon inside label', () => {
    const json = JSON.stringify({ action: 'read', file_path: '/tmp/a.xlsx' })
    const wrapper = mount(ToolInvocationPills, { props: { content: json } })
    expect(wrapper.find('.context-summary__icon').exists()).toBe(true)
  })
})
