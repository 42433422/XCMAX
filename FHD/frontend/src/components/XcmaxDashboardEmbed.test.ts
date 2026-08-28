import { afterEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import XcmaxDashboardEmbed from '../../../admin-console/src/components/admin/XcmaxDashboardEmbed.vue'

describe('XcmaxDashboardEmbed', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('shows a branded loading state instead of a blank iframe', () => {
    const wrapper = mount(XcmaxDashboardEmbed, {
      props: { src: '/xcmax-dashboard/pipeline.html', title: '自动化方针' },
    })

    expect(wrapper.get('[role="status"]').text()).toContain('正在加载 自动化方针')
    expect(wrapper.get('iframe').attributes('src')).toContain('/xcmax-dashboard/pipeline.html')
    wrapper.unmount()
  })

  it('retries one failed load and then presents actionable recovery', async () => {
    vi.useFakeTimers()
    const wrapper = mount(XcmaxDashboardEmbed, {
      props: { src: '/xcmax-dashboard/pipeline.html?embed=loops#s-loops', title: '自动化方针' },
    })

    await wrapper.get('iframe').trigger('error')
    await vi.advanceTimersByTimeAsync(1_200)
    expect(wrapper.get('iframe').attributes('src')).toContain('xcagi_embed_retry=')

    await wrapper.get('iframe').trigger('error')
    expect(wrapper.get('[role="alert"]').text()).toContain('自动化方针暂时未能载入')
    expect(wrapper.get('[role="alert"]').text()).toContain('重新加载')
    expect(wrapper.get('[role="alert"] a').attributes('href')).toBe('/xcmax-dashboard/pipeline.html?embed=loops#s-loops')

    await wrapper.get('[role="alert"] button').trigger('click')
    expect(wrapper.get('[role="status"]').exists()).toBe(true)
    wrapper.unmount()
  })
})
