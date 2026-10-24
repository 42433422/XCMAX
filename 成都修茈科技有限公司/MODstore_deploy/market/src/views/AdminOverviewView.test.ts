import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'
import AdminOverviewView from './AdminOverviewView.vue'
import { api } from '../api'

vi.mock('../api', () => ({ api: { adminStatus: vi.fn() } }))
const setup = () => mount(AdminOverviewView, { global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } } })
beforeEach(() => vi.mocked(api.adminStatus).mockReset())

it('displays server totals and leaves missing or invalid metrics unverified', async () => {
  vi.mocked(api.adminStatus).mockResolvedValueOnce({ ok: true, total_catalog_items: 532, total_users: 21 })
  const wrapper = setup()
  await flushPromises()
  expect(wrapper.findAll('strong').map((node) => node.text())).toEqual(['532', '21'])
  vi.mocked(api.adminStatus).mockResolvedValueOnce({ ok: true, total_catalog_items: -1 })
  await wrapper.get('button').trigger('click')
  await flushPromises()
  expect(wrapper.findAll('strong').map((node) => node.text())).toEqual(['待核实', '待核实'])
  wrapper.unmount()
})

it('shows a failed load and allows the admin to retry', async () => {
  vi.mocked(api.adminStatus).mockRejectedValueOnce(new Error('服务暂不可用'))
  const wrapper = setup()
  await flushPromises()
  expect(wrapper.get('[role="alert"]').text()).toBe('服务暂不可用')
  expect(wrapper.find('strong').exists()).toBe(false)
  vi.mocked(api.adminStatus).mockResolvedValueOnce({ ok: true, total_catalog_items: 0, total_users: 0 })
  await wrapper.get('button').trigger('click')
  await flushPromises()
  expect(wrapper.findAll('strong').map((node) => node.text())).toEqual(['0', '0'])
  wrapper.unmount()
})
