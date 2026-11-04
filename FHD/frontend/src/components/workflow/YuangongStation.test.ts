import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import YuangongStation from './YuangongStation.vue'
import * as assets from '@/constants/yuangongAssets'

it.each(['default', 'composed'] as const)('renders %s occupancy and advances broken image fallbacks only once', async pixelLayout => {
  const wrapper = mount(YuangongStation, { props: { enabled: false, busy: false, ariaLabel: '员工工位', pixelLayout } })
  expect(wrapper.get('[role="group"]').attributes('aria-label')).toBe('员工工位')
  expect(wrapper.findAll('img')).toHaveLength(1)
  const desk = wrapper.get('img')
  for (const src of [assets.YUANGONG_DESK_SVG, assets.YUANGONG_FALLBACK_DESK, assets.YUANGONG_FALLBACK_DESK]) {
    await desk.trigger('error'); expect(desk.attributes('src')).toBe(src)
  }
  await wrapper.setProps({ alwaysShowStaff: true })
  expect(wrapper.findAll('img')).toHaveLength(pixelLayout === 'composed' ? 1 : 2)
  for (const busy of [false, true]) {
    await wrapper.setProps({ enabled: true, busy })
    const staff = wrapper.findAll('img').at(-1)!
    expect(staff.attributes('src')).toBe(busy ? assets.YUANGONG_STAFF_BUSY_PNG : assets.YUANGONG_STAFF_PNG)
    expect(staff.classes().some(x => x.endsWith('--bob'))).toBe(busy)
    for (const src of [busy ? assets.YUANGONG_STAFF_BUSY_SVG : assets.YUANGONG_STAFF_SVG,
      busy ? assets.YUANGONG_FALLBACK_STAFF_BUSY : assets.YUANGONG_FALLBACK_STAFF]) {
      await staff.trigger('error'); expect(staff.attributes('src')).toBe(src)
    }
    const final = staff.attributes('src'); await staff.trigger('error')
    expect(staff.attributes('src')).toBe(final)
  }
  await wrapper.setProps({ enabled: false, alwaysShowStaff: false, composedIdleDeskVisible: false })
  expect(wrapper.findAll('img')).toHaveLength(pixelLayout === 'composed' ? 0 : 1)
  wrapper.unmount()
})
