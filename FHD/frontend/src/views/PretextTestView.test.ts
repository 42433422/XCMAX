import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'

vi.mock('@/utils/pretext-performance-test', () => ({
  runSingleMessageTest: vi.fn().mockReturnValue({
    name: 'Single test',
    domTime: 5.0,
    pretextTime: 0.1,
    speedup: 50,
    iterations: 100,
  }),
  runBatchMessageTest: vi.fn().mockReturnValue({
    name: 'Batch test',
    domTime: 50.0,
    pretextTime: 1.0,
    speedup: 50,
    iterations: 10,
  }),
  runFullTestSuite: vi.fn().mockReturnValue([
    { name: 'Short text', domTime: 2.0, pretextTime: 0.05, speedup: 40, iterations: 100 },
    { name: 'Long text', domTime: 10.0, pretextTime: 0.2, speedup: 50, iterations: 100 },
  ]),
}))

import PretextTestView from '@/views/PretextTestView.vue'

function mountComponent() {
  return mount(PretextTestView)
}

describe('PretextTestView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders the view container', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.pretext-test-view').exists()).toBe(true)
  })

  it('renders the title', () => {
    const wrapper = mountComponent()
    expect(wrapper.text()).toContain('Pretext.js 性能测试')
  })

  it('renders single test section', () => {
    const wrapper = mountComponent()
    expect(wrapper.text()).toContain('单条消息测试')
  })

  it('renders batch test section', () => {
    const wrapper = mountComponent()
    expect(wrapper.text()).toContain('批量消息测试')
  })

  it('renders full test section', () => {
    const wrapper = mountComponent()
    expect(wrapper.text()).toContain('完整测试套件')
  })

  it('renders textarea for test message', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('textarea').exists()).toBe(true)
  })

  it('renders run test button', () => {
    const wrapper = mountComponent()
    const buttons = wrapper.findAll('button')
    expect(buttons.length).toBeGreaterThanOrEqual(3)
  })

  it('runs single test on button click', async () => {
    const { runSingleMessageTest } = await import('@/utils/pretext-performance-test')
    const wrapper = mountComponent()
    const btn = wrapper.findAll('button')[0]
    await btn.trigger('click')
    expect(runSingleMessageTest).toHaveBeenCalled()
  })

  it('displays single test result after running', async () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    await vm.runSingleTest()
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('50.0x')
  })

  it('runs batch test on button click', async () => {
    const { runBatchMessageTest } = await import('@/utils/pretext-performance-test')
    const wrapper = mountComponent()
    const btn = wrapper.findAll('button')[1]
    await btn.trigger('click')
    expect(runBatchMessageTest).toHaveBeenCalled()
  })

  it('displays batch test result after running', async () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    await vm.runBatchTest()
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('50.0x')
  })

  it('runs full test on button click', async () => {
    const { runFullTestSuite } = await import('@/utils/pretext-performance-test')
    const wrapper = mountComponent()
    const btn = wrapper.findAll('button')[2]
    await btn.trigger('click')
    expect(runFullTestSuite).toHaveBeenCalled()
  })

  it('displays full test results after running', async () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    await vm.runFullTest()
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('Short text')
    expect(wrapper.text()).toContain('Long text')
  })

  it('computes average speedup correctly', async () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    await vm.runFullTest()
    expect(vm.averageSpeedup).toBe(45) // (40 + 50) / 2
  })

  it('disables buttons while testing', async () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    vm.isTesting = true
    await wrapper.vm.$nextTick()
    const buttons = wrapper.findAll('button')
    for (const btn of buttons) {
      expect(btn.element.disabled).toBe(true)
    }
  })

  it('initializes with default test message', () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    expect(vm.testMessage).toContain('测试消息')
  })

  it('renders info section with usage instructions', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.info-section').exists()).toBe(true)
    expect(wrapper.text()).toContain('runFullTestSuite')
  })

  it('sets isTesting to false after test completes', async () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    await vm.runSingleTest()
    expect(vm.isTesting).toBe(false)
  })
})
