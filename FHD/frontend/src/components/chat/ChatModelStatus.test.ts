import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import ChatModelStatus from './ChatModelStatus.vue'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'
import { invalidateEnterpriseSessionCache } from '@/utils/authSessionCache'

const { resolveRoute } = vi.hoisted(() => ({ resolveRoute: vi.fn() }))
vi.mock('@/api/chat', () => ({ default: { getModelStatus: resolveRoute } }))
enableAutoUnmount(afterEach)
beforeEach(() => resolveRoute.mockReset())

it('reads the platform default without claiming it is the actual request route or a successful generation', async () => {
  resolveRoute.mockResolvedValue({ ok: true, provider: 'openai', model: 'configured-model' })
  const wrapper = mount(ChatModelStatus)
  expect(wrapper.get('summary').text()).toContain('正在查询')
  await flushPromises()
  expect(wrapper.get('summary').text()).toContain('openai / configured-model')
  expect(wrapper.get('summary').text()).toContain('默认对话模型')
  expect(wrapper.text()).toContain('本次请求实际采用的模型尚未核实')
  expect(wrapper.text()).toContain('尚未发起模型生成测试')
  expect(wrapper.text()).toContain('管理员在服务器统一维护')
  expect(resolveRoute).toHaveBeenCalledTimes(1)
})

it.each([400, 401, 503])('shows an actionable failure without asking users to configure keys (%s)', async status => {
  resolveRoute.mockRejectedValue({ status })
  const wrapper = mount(ChatModelStatus)
  await flushPromises()
  expect(wrapper.get('summary').text()).toContain(status === 400 ? '尚无可用模型配置' : status === 401 ? '核对本机会话' : '暂时无法查询')
  expect(wrapper.text()).not.toContain('密钥')
  resolveRoute.mockResolvedValue({ ok: true, provider: 'platform', model: 'restored' })
  await wrapper.get('button').trigger('click')
  await flushPromises()
  expect(wrapper.get('summary').text()).toContain('platform / restored')
})

it.each(['account', 'auth'] as const)('ignores a previous %s response and reloads the current route', async scope => {
  let finishOld!: (value: unknown) => void
  resolveRoute.mockReturnValueOnce(new Promise(resolve => { finishOld = resolve }))
  const wrapper = mount(ChatModelStatus)
  resolveRoute.mockResolvedValue({ ok: true, provider: 'current', model: 'current-model' })
  if (scope === 'account') productReadAccountEpoch.value++
  else invalidateEnterpriseSessionCache()
  await flushPromises()
  finishOld({ ok: true, provider: 'old', model: 'private-old-model' })
  await flushPromises()
  expect(wrapper.get('summary').text()).toContain('current / current-model')
  expect(wrapper.text()).not.toContain('private-old-model')
})

it('retires a pending response when the status panel unmounts', async () => {
  let finish!: (value: unknown) => void
  resolveRoute.mockReturnValue(new Promise(resolve => { finish = resolve }))
  const wrapper = mount(ChatModelStatus)
  wrapper.unmount()
  finish({ ok: true, provider: 'old', model: 'late-model' })
  await flushPromises()
  expect(resolveRoute).toHaveBeenCalledTimes(1)
})
