import { mount } from '@vue/test-utils'
import { afterEach, expect, it, vi } from 'vitest'
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
  expect(wrapper.get('[role="status"]').text()).toBe('页面加载中…')
  await wrapper.setProps({ active: false })
  expect(wrapper.find('[role="status"]').exists()).toBe(false)
  wrapper.unmount()
})

it('retires a previous target timer and cleans up on unmount', async () => {
  vi.useFakeTimers()
  const wrapper = mount(RouteLoadingFeedback, { props: { active: 'first' } })
  await vi.advanceTimersByTimeAsync(200)
  await wrapper.setProps({ active: 'second' })
  await vi.advanceTimersByTimeAsync(80)
  expect(wrapper.find('[role="status"]').exists()).toBe(false)
  wrapper.unmount()
  expect(vi.getTimerCount()).toBe(0)
})
