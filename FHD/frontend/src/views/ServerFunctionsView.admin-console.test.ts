import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, expect, it, vi } from 'vitest'
import ServerFunctionsView from '../../../admin-console/src/views/ServerFunctionsView.vue'
import { api } from '@/api'
vi.mock('@/api', () => ({ api: { get: vi.fn(), post: vi.fn() } }))
afterEach(() => vi.resetAllMocks())
const rows = [
  { module_id: 'core-a', display_name: '核心模块', active: true, source: 'core', route: '/a' },
  { module_id: 'remote-b', display_name: '远端模块', active: false, source: 'remote' },
]
function respond(data: unknown = rows) {
  vi.mocked(api.get).mockImplementation(async (url: string) => ({ data: url.endsWith('/modules') ? data : {} }) as any)
}
it('combines name/id search with status and preserves details', async () => {
  respond()
  const wrapper = mount(ServerFunctionsView)
  await flushPromises()
  expect(wrapper.findAll('tbody tr')).toHaveLength(2)
  await wrapper.get('[aria-label="搜索模块"]').setValue('REMOTE')
  expect(wrapper.findAll('tbody tr')).toHaveLength(1)
  await wrapper.get('[aria-label="模块状态"]').setValue('enabled')
  expect(wrapper.text()).toContain('没有匹配的模块')
  await wrapper.get('[aria-label="搜索模块"]').setValue('')
  expect(wrapper.findAll('tbody tr')).toHaveLength(1)
  expect(wrapper.get('.module-detail').text()).toContain('/a')
  wrapper.unmount()
})
it.each(['network', 'malformed'])('distinguishes %s errors from an empty registry and supports retry', async kind => {
  respond(kind === 'malformed' ? {} : rows)
  if (kind === 'network') vi.mocked(api.get).mockRejectedValueOnce(new Error('连接失败'))
  const wrapper = mount(ServerFunctionsView)
  await flushPromises()
  expect(wrapper.find('[role="alert"]').exists()).toBe(true)
  expect(wrapper.text()).not.toContain('暂无模块数据')
  expect(wrapper.get('[aria-label="模块统计"]').text()).toContain('—')
  respond([])
  await wrapper.get('[role="alert"] button').trigger('click')
  await flushPromises()
  expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  expect(wrapper.text()).toContain('暂无模块数据')
  wrapper.unmount()
})
