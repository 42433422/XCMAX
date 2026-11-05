import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import AdminReleaseStatusCard from '../../../../admin-console/src/components/admin/AdminReleaseStatusCard.vue'
import { xcmaxAdminApi } from '@/api/xcmaxAdmin'

vi.mock('@/api/xcmaxAdmin', () => ({
  xcmaxAdminApi: { checkDeployUpdates: vi.fn(), listUpdateInstallReceipts: vi.fn() },
}))

const data = { enterprise: { reachable: false }, update_hub: { git_sha: 'build-a' }, flags: { up_to_date: true } }
const report = { summary: { installed_devices: 0, failed_devices: 0 }, items: [] }
const deferred = () => {
  let resolve, reject
  const promise = new Promise((yes, no) => {
    resolve = yes
    reject = no
  })
  return { promise, resolve, reject }
}
let wrapper
const fields = () => Object.fromEntries(wrapper.findAll('dt').map(node => [
  node.text(), node.element.nextElementSibling.textContent.trim(),
]))
const refresh = () => wrapper.vm.refresh().then(() => nextTick())
beforeEach(() => {
  vi.resetAllMocks()
  xcmaxAdminApi.checkDeployUpdates.mockResolvedValue({ data })
  xcmaxAdminApi.listUpdateInstallReceipts.mockResolvedValue(report)
  wrapper = mount(AdminReleaseStatusCard)
})
afterEach(() => {
  wrapper.unmount()
  vi.restoreAllMocks()
})

it('keeps unobserved values unknown, serializes refreshes, and emits the settled status', async () => {
  const check = deferred()
  const receipts = deferred()
  xcmaxAdminApi.checkDeployUpdates.mockReturnValue(check.promise)
  xcmaxAdminApi.listUpdateInstallReceipts.mockReturnValue(receipts.promise)
  expect(fields()).toMatchObject({ 企业端: '未检测', 本构建安装回执: '未检测' })
  const update = vi.spyOn(window, 'dispatchEvent')
  const pending = wrapper.vm.refresh()
  await refresh()
  expect(xcmaxAdminApi.checkDeployUpdates).toHaveBeenCalledTimes(1)
  expect(fields()).toMatchObject({ 企业端: '检测中', 本构建安装回执: '检测中' })
  expect(wrapper.find('.status-badge').classes()).toContain('badge-dim')
  expect(wrapper.find('button').element.disabled).toBe(true)
  check.resolve({ data })
  await flushPromises()
  expect(fields()).toMatchObject({ 企业端: '不可达', 本构建安装回执: '检测中' })
  expect(xcmaxAdminApi.listUpdateInstallReceipts).toHaveBeenCalledWith('build-a')
  receipts.resolve(report)
  await pending
  await nextTick()
  expect(fields().本构建安装回执).toBe('0 台报告已安装')
  expect(wrapper.find('.status-badge').text()).toBe('最新')
  expect(update).toHaveBeenLastCalledWith(expect.objectContaining({
    type: 'xcagi:admin-deploy-updated', detail: expect.objectContaining({ text: '最新' }),
  }))
  expect(wrapper.find('button').element.disabled).toBe(false)
})

it('clears previous observations during retry and after a failed deployment check', async () => {
  await wrapper.vm.refresh()
  const check = deferred()
  xcmaxAdminApi.checkDeployUpdates.mockReturnValue(check.promise)
  const pending = wrapper.vm.refresh()
  await nextTick()
  expect(fields()).toMatchObject({ 企业端: '检测中', 本构建安装回执: '检测中' })
  check.reject(new Error('network unavailable'))
  await pending
  await nextTick()
  expect(fields()).toMatchObject({ 企业端: '检测失败', 本构建安装回执: '未检测' })
  expect(wrapper.find('.release-hint').text()).toContain('版本检测失败：network unavailable')
  expect(wrapper.find('.status-badge').classes()).toContain('badge-error')
  expect(xcmaxAdminApi.listUpdateInstallReceipts).toHaveBeenCalledTimes(1)
  xcmaxAdminApi.checkDeployUpdates.mockResolvedValue({ data })
  await refresh()
  expect(fields()).toMatchObject({ 企业端: '不可达', 本构建安装回执: '0 台报告已安装' })
  expect(wrapper.find('.status-badge').text()).toBe('最新')
})

it('reports a receipt failure without replacing it with zero or keeping old receipts', async () => {
  xcmaxAdminApi.listUpdateInstallReceipts.mockResolvedValue({
    summary: { installed_devices: 2, failed_devices: 1 },
    items: [{ id: 1, status: 'failed', error: 'old receipt' }],
  })
  await refresh()
  expect(fields().本构建安装回执).toContain('2 台报告已安装')
  expect(wrapper.find('.install-receipts').exists()).toBe(true)
  xcmaxAdminApi.checkDeployUpdates.mockResolvedValue({ data: { ...data, enterprise: { reachable: true } } })
  xcmaxAdminApi.listUpdateInstallReceipts.mockRejectedValue(new Error('receipt timeout'))
  await refresh()
  expect(fields()).toMatchObject({ 企业端: '在线', 本构建安装回执: '读取失败' })
  expect(wrapper.find('.install-receipts').exists()).toBe(false)
  expect(wrapper.find('.release-hint').text()).toContain('安装回执读取失败：receipt timeout')
})

it('does not let success flags mask observed update-hub unreachability', async () => {
  xcmaxAdminApi.checkDeployUpdates.mockResolvedValue({ data: { ...data, update_hub: { reachable: false } } })
  await refresh()
  expect(wrapper.find('.status-badge').text()).toBe('未连通')
  expect(wrapper.find('.status-badge').classes()).toContain('badge-error')
})

it.each([undefined, null, 0, 'false'])('does not coerce unknown reachability %s into unreachable', async reachable => {
  xcmaxAdminApi.checkDeployUpdates.mockResolvedValue({ data: { ...data, enterprise: { reachable } } })
  await refresh()
  expect(fields().企业端).toBe('未知')
})

it.each([undefined, {}, { installed_devices: 0 }, { installed_devices: -1, failed_devices: 0 }])(
  'does not treat incomplete or invalid receipt summary %j as zero', async summary => {
    xcmaxAdminApi.listUpdateInstallReceipts.mockResolvedValue({ summary, items: [] })
    await refresh()
    expect(fields().本构建安装回执).toBe('读取失败')
    expect(wrapper.find('.release-hint').text()).toContain('安装回执数据不完整')
  },
)

it.each(['', undefined, 'local'])('does not query all historical receipts when build identity is %s', async git_sha => {
  xcmaxAdminApi.checkDeployUpdates.mockResolvedValue({ data: { ...data, update_hub: { git_sha } } })
  await refresh()
  expect(xcmaxAdminApi.listUpdateInstallReceipts).not.toHaveBeenCalled()
  expect(fields().本构建安装回执).toBe('未检测')
})
