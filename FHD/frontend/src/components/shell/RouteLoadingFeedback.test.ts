import { mount } from '@vue/test-utils'
import { afterEach, expect, it, vi } from 'vitest'
import { h, nextTick, ref } from 'vue'
import RouteLoadingFeedback from './RouteLoadingFeedback.vue'

afterEach(() => vi.useRealTimers())

it('does not flash feedback for a completed short navigation', async () => {
  vi.useFakeTimers()
  const wrapper = mount(RouteLoadingFeedback, { props: { active: true } })
  await vi.advanceTimersByTimeAsync(80)
  expect(wrapper.find('[role="status"]').exists()).toBe(false)
  await wrapper.setProps({ active: false })
  await vi.advanceTimersByTimeAsync(1000)
  expect(wrapper.find('[role="status"]').exists()).toBe(false)
  wrapper.unmount()
})

it('reveals a slow navigation and removes feedback as soon as it completes', async () => {
  vi.useFakeTimers()
  const wrapper = mount(RouteLoadingFeedback, { props: { active: false } })
  await wrapper.setProps({ active: true })
  await vi.advanceTimersByTimeAsync(279)
  expect(wrapper.find('[role="status"]').exists()).toBe(false)
  await vi.advanceTimersByTimeAsync(1)
  expect(wrapper.get('[role="status"]').text()).toContain('页面加载中…')
  expect(wrapper.get('[role="status"]').text()).toContain('正在准备页面内容')
  expect(wrapper.get('.route-loading-feedback__spinner').attributes('aria-hidden')).toBe('true')
  await wrapper.setProps({ active: false })
  expect(wrapper.find('[role="status"]').exists()).toBe(false)
  wrapper.unmount()
})

it('announces the actual stage and offers retry only after failure', async () => {
  vi.useFakeTimers()
  const wrapper = mount(RouteLoadingFeedback, { props: { active: true, stage: '正在打开「数据对接中心」' } })
  await vi.advanceTimersByTimeAsync(280)
  expect(wrapper.get('[role="status"]').text()).toContain('正在打开「数据对接中心」')
  expect(wrapper.find('button').exists()).toBe(false)
  await wrapper.setProps({ active: false, failed: true })
  expect(wrapper.get('[role="alert"]').text()).toContain('页面加载失败')
  expect(wrapper.find('.route-loading-feedback__spinner').exists()).toBe(false)
  await wrapper.get('button').trigger('click')
  expect(wrapper.emitted('retry')).toHaveLength(1)
  await wrapper.setProps({ failed: false, active: true })
  expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  await vi.advanceTimersByTimeAsync(280)
  expect(wrapper.find('[role="status"]').exists()).toBe(true)
  wrapper.unmount()
})

it('retires a previous target timer and cleans up on unmount', async () => {
  vi.useFakeTimers()
  const target = ref('first')
  const wrapper = mount({
    setup: () => () => h(RouteLoadingFeedback, { key: target.value, active: !!target.value }),
  })
  await vi.advanceTimersByTimeAsync(200)
  target.value = 'second'
  await nextTick()
  await vi.advanceTimersByTimeAsync(80)
  expect(wrapper.find('[role="status"]').exists()).toBe(false)
  wrapper.unmount()
  expect(vi.getTimerCount()).toBe(0)
})
