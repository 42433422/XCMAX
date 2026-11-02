import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h, KeepAlive, ref } from 'vue'
import ChatModelRecovery from './ChatModelRecovery.vue'
import { PLATFORM_MODEL_CHANGED_EVENT } from '@/api/platformModel'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'
import { invalidateEnterpriseSessionCache } from '@/utils/authSessionCache'

const { resolveRoute, followPlatform } = vi.hoisted(() => ({ resolveRoute: vi.fn(), followPlatform: vi.fn() }))
vi.mock('@/api/chat', () => ({ default: { getModelStatus: resolveRoute, followPlatformModel: followPlatform } }))
const preferenceError = (code = 'INVALID_CHAT_PREFERENCE') => ({ status: 400, data: { detail: { code } } })
enableAutoUnmount(afterEach)
beforeEach(() => { resolveRoute.mockReset(); followPlatform.mockReset(); productReadAccountEpoch.value++ })

it('renders nothing while checking or when the account has a usable preference', async () => {
  let finish!: (value: unknown) => void
  resolveRoute.mockReturnValue(new Promise(resolve => { finish = resolve }))
  const wrapper = mount(ChatModelRecovery)
  expect(wrapper.text()).toBe('')
  expect(wrapper.find('button').exists()).toBe(false)
  finish({ ok: true, provider: 'private-provider', model: 'private-model', config_revision: 'private-revision' })
  await flushPromises()
  expect(wrapper.text()).toBe('')
  expect(wrapper.find('[role=alert]').exists()).toBe(false)
  expect(followPlatform).not.toHaveBeenCalled()
})

it.each(['INVALID_CHAT_PREFERENCE', 'NO_BYOK_CHAT_MODEL'])('offers an explicit preference recovery only for %s', async code => {
  resolveRoute.mockRejectedValue(preferenceError(code))
  const wrapper = mount(ChatModelRecovery)
  await flushPromises()
  expect(wrapper.get('button').text()).toBe('恢复平台默认模型')
  expect(wrapper.text()).not.toMatch(/模型信息|凭据|配置版本|BYOK|provider/)
  expect(followPlatform).not.toHaveBeenCalled()
  followPlatform.mockResolvedValue({ ok: true })
  await wrapper.get('button').trigger('click'); await flushPromises()
  expect(followPlatform).toHaveBeenCalledTimes(1)
  expect(wrapper.text()).toBe('')
})

it.each([400, 401, 503])('does not replace the removed diagnostics with a status-query failure (%s)', async status => {
  resolveRoute.mockRejectedValue({ status, data: { code: 'UNRELATED', message: 'private-query-detail' } })
  const wrapper = mount(ChatModelRecovery)
  await flushPromises()
  expect(wrapper.text()).toBe('')
  expect(wrapper.find('button').exists()).toBe(false)
})

it('prevents duplicate recovery and keeps an unconfirmed save safe to retry explicitly', async () => {
  resolveRoute.mockRejectedValue(preferenceError())
  const wrapper = mount(ChatModelRecovery)
  await flushPromises()
  let finish!: (value: unknown) => void
  followPlatform.mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
  const button = wrapper.get('button')
  await button.trigger('click'); await button.trigger('click')
  expect(followPlatform).toHaveBeenCalledTimes(1)
  expect(button.attributes('disabled')).toBeDefined()
  finish({ ok: false }); await flushPromises()
  expect(wrapper.text()).toContain('恢复未确认')
  expect(button.attributes('disabled')).toBeUndefined()
  followPlatform.mockRejectedValueOnce(new Error('private-save-detail'))
  await button.trigger('click'); await flushPromises()
  expect(wrapper.text()).not.toContain('private-save-detail')
  followPlatform.mockResolvedValueOnce({ ok: true })
  await button.trigger('click'); await flushPromises()
  expect(followPlatform).toHaveBeenCalledTimes(3)
  expect(wrapper.text()).toBe('')
})

it.each(['account', 'auth', 'session', 'mod'])('ignores a stale %s query failure', async scope => {
  let rejectOld!: (error: unknown) => void
  resolveRoute.mockReturnValueOnce(new Promise((_resolve, reject) => { rejectOld = reject }))
  const wrapper = mount(ChatModelRecovery, { props: { scopeKey: 'session-a/mod-a' } })
  resolveRoute.mockResolvedValue({ ok: true })
  if (scope === 'account') productReadAccountEpoch.value++
  else if (scope === 'auth') invalidateEnterpriseSessionCache()
  else await wrapper.setProps({ scopeKey: scope === 'session' ? 'session-b/mod-a' : 'session-a/mod-b' })
  await flushPromises()
  rejectOld(preferenceError()); await flushPromises()
  expect(resolveRoute).toHaveBeenCalledTimes(2)
  expect(wrapper.text()).toBe('')
})

it.each(['account', 'auth', 'session', 'mod'])('does not apply a previous %s recovery acknowledgement to a new scope', async scope => {
  resolveRoute.mockRejectedValue(preferenceError())
  const wrapper = mount(ChatModelRecovery, { props: { scopeKey: 'session-a/mod-a' } })
  await flushPromises()
  let finish!: (value: unknown) => void
  followPlatform.mockReturnValue(new Promise(resolve => { finish = resolve }))
  await wrapper.get('button').trigger('click')
  if (scope === 'account') productReadAccountEpoch.value++
  else if (scope === 'auth') invalidateEnterpriseSessionCache()
  else await wrapper.setProps({ scopeKey: scope === 'session' ? 'session-b/mod-a' : 'session-a/mod-b' })
  await flushPromises()
  finish({ ok: true }); await flushPromises()
  expect(wrapper.get('button').text()).toBe('恢复平台默认模型')
  expect(wrapper.get('button').attributes('disabled')).toBeUndefined()
  expect(followPlatform).toHaveBeenCalledTimes(1)
})

it('retires a deactivated check and rechecks only the active scope on return', async () => {
  const visible = ref(true)
  let rejectOld!: (error: unknown) => void
  resolveRoute.mockReturnValueOnce(new Promise((_resolve, reject) => { rejectOld = reject }))
  const wrapper = mount(defineComponent({ setup: () => () => h(KeepAlive, null, { default: () => visible.value ? h(ChatModelRecovery) : null }) }))
  visible.value = false; await flushPromises()
  rejectOld(preferenceError()); await flushPromises()
  resolveRoute.mockResolvedValue({ ok: true })
  visible.value = true; await flushPromises()
  expect(resolveRoute).toHaveBeenCalledTimes(2)
  expect(wrapper.text()).toBe('')
  wrapper.unmount()
  window.dispatchEvent(new Event(PLATFORM_MODEL_CHANGED_EVENT))
  await flushPromises()
  expect(resolveRoute).toHaveBeenCalledTimes(2)
})
