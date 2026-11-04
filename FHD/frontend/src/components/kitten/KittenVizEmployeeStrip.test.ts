import { mount } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import KittenVizEmployeeStrip from './KittenVizEmployeeStrip.vue'
import { KITTEN_VIZ_EMPLOYEES } from '@/constants/kittenVisualizationEmployees'

it.each(['', 'https://market.example.test/'])('selects installed employees and opens the configured market for locked employees (%s)', async base => {
  vi.stubEnv('VITE_MARKET_BASE', base)
  const open = vi.spyOn(window, 'open').mockImplementation(() => null)
  const employees = KITTEN_VIZ_EMPLOYEES.slice(0, 2).map((employee, i) => ({ ...employee, installed: i === 0 }))
  const wrapper = mount(KittenVizEmployeeStrip, { props: { employees, selectedPkgId: employees[0].pkgId, installedCount: 1, loading: true } })
  expect(wrapper.text()).toContain('已安装 1/2'); expect(wrapper.text()).toContain('同步中')
  expect(wrapper.get('.is-active').text()).toContain('使用中')
  await wrapper.get('.is-active').trigger('click')
  expect(wrapper.emitted('select')).toEqual([[employees[0].pkgId]])
  await wrapper.get('.is-locked').trigger('click'); await wrapper.get('.kitten-viz-strip__market').trigger('click')
  expect(open).toHaveBeenCalledTimes(2)
  expect(open).toHaveBeenLastCalledWith(`${(base || 'https://xiu-ci.com/market').replace(/\/$/, '')}/ai-store?nav=office_aux`, '_blank', 'noopener,noreferrer')
  expect(wrapper.emitted('select')).toHaveLength(1)
  await wrapper.setProps({ loading: false }); expect(wrapper.find('.kitten-viz-strip__loading').exists()).toBe(false)
  wrapper.unmount(); open.mockRestore(); vi.unstubAllEnvs()
})
