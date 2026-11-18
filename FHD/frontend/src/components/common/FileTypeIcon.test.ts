import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import FileTypeIcon from './FileTypeIcon.vue'
const { ensure } = vi.hoisted(() => ({ ensure: vi.fn() }))
vi.mock('@/utils/fileTypeIcon', () => ({ ensureFileTypeIcons: ensure, fileIconName: (name: string, kind: string) => `icon:${name || kind}` }))
vi.mock('@iconify/vue', () => ({ Icon: { props: ['icon', 'width', 'height'], template: '<svg :data-icon="icon" :width="width" :height="height" />' } }))
let wrapper: VueWrapper | undefined
beforeEach(() => ensure.mockReset())
afterEach(() => wrapper?.unmount())
it('keeps a visible accessible fallback while loading and renders the requested icon afterward', async () => {
  let finish!: (ready: boolean) => void
  ensure.mockReturnValue(new Promise(resolve => { finish = resolve }))
  wrapper = mount(FileTypeIcon, { props: { name: 'report.xlsx', size: 20, label: '电子表格' } })
  expect(wrapper.get('.fa-file-o').attributes('aria-label')).toBe('电子表格')
  expect(wrapper.find('svg').exists()).toBe(false)
  finish(true); await flushPromises()
  expect(wrapper.get('svg').attributes()).toMatchObject({ 'data-icon': 'icon:report.xlsx', width: '20', height: '20', 'aria-label': '电子表格' })
})
it('retains the fallback on failure and retries on a later file selection', async () => {
  ensure.mockResolvedValueOnce(false).mockResolvedValueOnce(true)
  wrapper = mount(FileTypeIcon, { props: { name: 'report.xlsx' } })
  await flushPromises()
  expect(wrapper.get('.fa-file-o').attributes('aria-hidden')).toBe('true')
  await wrapper.setProps({ name: 'photo.png' }); await flushPromises()
  expect(ensure).toHaveBeenCalledTimes(2)
  expect(wrapper.get('svg').attributes('data-icon')).toBe('icon:photo.png')
})
