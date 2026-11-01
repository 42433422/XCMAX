import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import ChatModelStatus from './ChatModelStatus.vue'
import { recordChatModelRoute } from '@/utils/chatModelRoute'
import { PLATFORM_MODEL_CHANGED_EVENT, PLATFORM_MODEL_CHANGED_KEY } from '@/api/platformModel'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'
import { invalidateEnterpriseSessionCache } from '@/utils/authSessionCache'

const { resolveRoute, followPlatform } = vi.hoisted(() => ({ resolveRoute: vi.fn(), followPlatform: vi.fn() }))
vi.mock('@/api/chat', () => ({ default: { getModelStatus: resolveRoute, followPlatformModel: followPlatform } }))
enableAutoUnmount(afterEach)
beforeEach(() => { resolveRoute.mockReset(); followPlatform.mockReset(); productReadAccountEpoch.value++ })

it('reads the platform default without claiming it is the actual request route or a successful generation', async () => {
  resolveRoute.mockResolvedValue({ ok: true, provider: 'openai', model: 'configured-model' })
  const wrapper = mount(ChatModelStatus)
  expect(wrapper.get('summary').text()).toBe('模型信息')
  await flushPromises()
  expect(wrapper.get('summary').text()).toBe('模型信息')
  expect((wrapper.element as HTMLDetailsElement).open).toBe(false)
  expect(wrapper.text()).toContain('当前解析默认：openai / configured-model')
  expect(wrapper.text()).toContain('尚无实际模型回执')
  expect(wrapper.text()).toContain('管理员在服务器统一维护')
  expect(resolveRoute).toHaveBeenCalledTimes(1)
})

it.each([400, 401, 503])('shows an actionable failure without asking users to configure keys (%s)', async status => {
  resolveRoute.mockRejectedValue({ status })
  const wrapper = mount(ChatModelStatus)
  await flushPromises()
  expect(wrapper.text()).toContain(status === 400 ? '尚无可用模型配置' : status === 401 ? '核对本机会话' : '暂时无法查询')
  resolveRoute.mockResolvedValue({ ok: true, provider: 'platform', model: 'restored' })
  await wrapper.get('button').trigger('click')
  await flushPromises()
  expect(wrapper.text()).toContain('platform / restored')
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
  expect(wrapper.text()).toContain('current / current-model')
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


it('invalidates current defaults on platform save without rewriting the actual receipt', async () => {
  resolveRoute.mockResolvedValue({ ok: true, provider: 'xiaomi', model: 'flash-a', route_source: 'platform_default', key_source: 'managed', config_revision: 'a' })
  const wrapper = mount(ChatModelStatus, { props: { sessionId: 'chat-a' } })
  await flushPromises()
  recordChatModelRoute('chat-a', { provider: 'xiaomi', model: 'flash-a', route_source: 'platform_default', key_source: 'managed', config_revision: 'a' })
  await flushPromises()
  resolveRoute.mockResolvedValue({ ok: true, provider: 'xiaomi', model: 'flash-b', route_source: 'platform_default', key_source: 'managed', config_revision: 'b' })
  window.dispatchEvent(new Event(PLATFORM_MODEL_CHANGED_EVENT))
  await flushPromises()
  expect(wrapper.text()).toContain('当前解析默认：xiaomi / flash-b')
  expect(wrapper.get('[data-testid="actual-model-route"]').text()).toContain('xiaomi / flash-a')
  resolveRoute.mockResolvedValue({ ok: true, provider: 'xiaomi', model: 'flash-c' })
  window.dispatchEvent(new StorageEvent('storage', { key: PLATFORM_MODEL_CHANGED_KEY, newValue: 'saved' }))
  await flushPromises()
  expect(wrapper.text()).toContain('当前解析默认：xiaomi / flash-c')
  expect(wrapper.get('[data-testid="actual-model-route"]').text()).toContain('xiaomi / flash-a')
  productReadAccountEpoch.value++
  await flushPromises()
  expect(wrapper.find('[data-testid="actual-model-route"]').exists()).toBe(false)
})

it('requires an explicit click to recover an invalid preference', async () => {
  resolveRoute.mockRejectedValue({ status: 400, data: { detail: { code: 'INVALID_CHAT_PREFERENCE' } } })
  const wrapper = mount(ChatModelStatus)
  await flushPromises()
  expect(wrapper.get('summary').text()).toBe('模型配置需检查')
  expect(followPlatform).not.toHaveBeenCalled()
  followPlatform.mockResolvedValue({ ok: true })
  resolveRoute.mockResolvedValue({ ok: true, provider: 'xiaomi', model: 'flash', route_source: 'platform_default' })
  await wrapper.findAll('button').find(button => button.text().includes('改为跟随平台'))!.trigger('click')
  await flushPromises()
  expect(followPlatform).toHaveBeenCalledTimes(1)
  expect(wrapper.text()).toContain('跟随平台')
  expect(wrapper.text()).not.toContain('个人模型选择不能用于聊天')
})

it('keeps only the latest of repeated refreshes', async () => {
  let old!: (value: unknown) => void
  resolveRoute.mockReturnValueOnce(new Promise(resolve => { old = resolve }))
  const wrapper = mount(ChatModelStatus)
  resolveRoute.mockResolvedValue({ ok: true, provider: 'current', model: 'new' })
  window.dispatchEvent(new Event(PLATFORM_MODEL_CHANGED_EVENT))
  await flushPromises()
  old({ ok: true, provider: 'stale', model: 'old' })
  await flushPromises()
  expect(wrapper.text()).toContain('current / new')
  expect(wrapper.text()).not.toContain('stale / old')
})
