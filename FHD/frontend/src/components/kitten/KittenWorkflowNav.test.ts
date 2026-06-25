import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import KittenWorkflowNav from './KittenWorkflowNav.vue'

const sampleSteps = [
  { key: 'a', label: '采集', desc: '数据采集阶段' },
  { key: 'b', label: '清洗', desc: '数据清洗阶段' },
  { key: 'c', label: '分析', desc: '数据分析阶段' },
  { key: 'd', label: '输出', desc: '结果输出阶段' },
]

describe('KittenWorkflowNav', () => {
  it('renders nav with aria-label', () => {
    const wrapper = mount(KittenWorkflowNav, { props: { steps: sampleSteps } })
    expect(wrapper.find('nav.kitten-workflow').exists()).toBe(true)
    expect(wrapper.find('nav.kitten-workflow').attributes('aria-label')).toBe('分析工作流')
  })

  it('renders no steps when steps prop is empty', () => {
    const wrapper = mount(KittenWorkflowNav, { props: { steps: [] } })
    expect(wrapper.findAll('.kitten-workflow-step')).toHaveLength(0)
  })

  it('renders all provided steps with index labels', () => {
    const wrapper = mount(KittenWorkflowNav, { props: { steps: sampleSteps } })
    const items = wrapper.findAll('.kitten-workflow-step')
    expect(items).toHaveLength(4)
    expect(items[0].find('.kitten-workflow-index').text()).toBe('1')
    expect(items[3].find('.kitten-workflow-index').text()).toBe('4')
  })

  it('renders step label and desc', () => {
    const wrapper = mount(KittenWorkflowNav, { props: { steps: sampleSteps } })
    const first = wrapper.findAll('.kitten-workflow-step')[0]
    expect(first.find('.kitten-workflow-label').text()).toBe('采集')
    expect(first.find('.kitten-workflow-desc').text()).toBe('数据采集阶段')
  })

  it('marks steps before activeIndex as done', () => {
    const wrapper = mount(KittenWorkflowNav, { props: { steps: sampleSteps, activeIndex: 2 } })
    const items = wrapper.findAll('.kitten-workflow-step')
    expect(items[0].classes()).toContain('done')
    expect(items[1].classes()).toContain('done')
    expect(items[2].classes()).not.toContain('done')
  })

  it('marks the step at activeIndex as current', () => {
    const wrapper = mount(KittenWorkflowNav, { props: { steps: sampleSteps, activeIndex: 1 } })
    const items = wrapper.findAll('.kitten-workflow-step')
    expect(items[1].classes()).toContain('current')
    expect(items[0].classes()).not.toContain('current')
  })

  it('marks steps after activeIndex as upcoming', () => {
    const wrapper = mount(KittenWorkflowNav, { props: { steps: sampleSteps, activeIndex: 0 } })
    const items = wrapper.findAll('.kitten-workflow-step')
    expect(items[1].classes()).toContain('upcoming')
    expect(items[2].classes()).toContain('upcoming')
    expect(items[0].classes()).not.toContain('upcoming')
  })

  it('uses default activeIndex=0 when not provided', () => {
    const wrapper = mount(KittenWorkflowNav, { props: { steps: sampleSteps } })
    const items = wrapper.findAll('.kitten-workflow-step')
    expect(items[0].classes()).toContain('current')
    expect(items[1].classes()).toContain('upcoming')
  })

  it('updates classes when activeIndex changes', async () => {
    const wrapper = mount(KittenWorkflowNav, { props: { steps: sampleSteps, activeIndex: 0 } })
    expect(wrapper.findAll('.kitten-workflow-step')[2].classes()).toContain('upcoming')
    await wrapper.setProps({ activeIndex: 3 })
    expect(wrapper.findAll('.kitten-workflow-step')[2].classes()).toContain('done')
    expect(wrapper.findAll('.kitten-workflow-step')[3].classes()).toContain('current')
  })
})
