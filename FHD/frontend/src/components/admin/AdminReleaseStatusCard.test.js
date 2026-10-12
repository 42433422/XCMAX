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
const field = label => wrapper.findAll('dt').find(node => node.text() === label).element.nextElementSibling.textContent.trim()
beforeEach(() => {
  vi.resetAllMocks()
  xcmaxAdminApi.checkDeployUpdates.mockResolvedValue({ data })
  xcmaxAdminApi.listUpdateInstallReceipts.mockResolvedValue(report)
  wrapper = mount(AdminReleaseStatusCard)
})
afterEach(() => wrapper.unmount())

it('keeps unobserved values unknown, serializes refreshes, and emits the settled status', async () => {
  const check = deferred()
  const receipts = deferred()
  xcmaxAdminApi.checkDeployUpdates.mockReturnValue(check.promise)
  xcmaxAdminApi.listUpdateInstallReceipts.mockReturnValue(receipts.promise)
  expect(field('企业端')).toBe('未检测')
  expect(field('安装回执')).toBe('未检测')
  const update = vi.fn()
  window.addEventListener('xcagi:admin-deploy-updated', update)
  try {
    const pending = wrapper.vm.refresh()
    await wrapper.vm.refresh()
    await nextTick()
    expect(xcmaxAdminApi.checkDeployUpdates).toHaveBeenCalledTimes(1)
    expect(field('企业端')).toBe('检测中')
    expect(field('安装回执')).toBe('检测中')
    expect(wrapper.find('.status-badge').classes()).toContain('badge-dim')
    expect(wrapper.find('button').element.disabled).toBe(true)
    check.resolve({ data })
    await flushPromises()
    expect(field('企业端')).toBe('不可达')
    expect(field('安装回执')).toBe('检测中')
    expect(xcmaxAdminApi.listUpdateInstallReceipts).toHaveBeenCalledWith('build-a')
    receipts.resolve(report)
    await pending
    await nextTick()
    expect(field('安装回执')).toBe('0 台已安装')
    expect(wrapper.find('.status-badge').text()).toBe('最新')
    expect(update.mock.lastCall[0].detail.text).toBe('最新')
    expect(wrapper.find('button').element.disabled).toBe(false)
  } finally {
    window.removeEventListener('xcagi:admin-deploy-updated', update)
  }
})

it('clears previous observations during retry and after a failed deployment check', async () => {
  await wrapper.vm.refresh()
  const check = deferred()
  xcmaxAdminApi.checkDeployUpdates.mockReturnValue(check.promise)
  const pending = wrapper.vm.refresh()
  await nextTick()
  expect(field('企业端')).toBe('检测中')
  expect(field('安装回执')).toBe('检测中')
  check.reject(new Error('network unavailable'))
  await pending
  await nextTick()
  expect(field('企业端')).toBe('检测失败')
  expect(field('安装回执')).toBe('未检测')
  expect(wrapper.find('.release-hint').text()).toContain('版本检测失败：network unavailable')
  expect(wrapper.find('.status-badge').classes()).toContain('badge-error')
  expect(xcmaxAdminApi.listUpdateInstallReceipts).toHaveBeenCalledTimes(1)
  xcmaxAdminApi.checkDeployUpdates.mockResolvedValue({ data })
  await wrapper.vm.refresh()
  await nextTick()
  expect(field('企业端')).toBe('不可达')
  expect(field('安装回执')).toBe('0 台已安装')
  expect(wrapper.find('.status-badge').text()).toBe('最新')
})

it('reports a receipt failure without replacing it with zero or keeping old receipts', async () => {
  xcmaxAdminApi.listUpdateInstallReceipts.mockResolvedValue({
    summary: { installed_devices: 2, failed_devices: 1 },
    items: [{ id: 1, status: 'failed', error: 'old receipt' }],
  })
  await wrapper.vm.refresh()
  await nextTick()
  expect(field('安装回执')).toContain('2 台已安装')
  expect(wrapper.find('.install-receipts').exists()).toBe(true)
  xcmaxAdminApi.checkDeployUpdates.mockResolvedValue({ data: { ...data, enterprise: { reachable: true } } })
  xcmaxAdminApi.listUpdateInstallReceipts.mockRejectedValue(new Error('receipt timeout'))
  await wrapper.vm.refresh()
  await nextTick()
  expect(field('企业端')).toBe('在线')
  expect(field('安装回执')).toBe('读取失败')
  expect(wrapper.find('.install-receipts').exists()).toBe(false)
  expect(wrapper.find('.release-hint').text()).toContain('安装回执读取失败：receipt timeout')
})

it('does not let success flags mask observed update-hub unreachability', async () => {
  xcmaxAdminApi.checkDeployUpdates.mockResolvedValue({ data: { ...data, update_hub: { reachable: false } } })
  await wrapper.vm.refresh()
  await nextTick()
  expect(wrapper.find('.status-badge').text()).toBe('未连通')
  expect(wrapper.find('.status-badge').classes()).toContain('badge-error')
})

it.each([undefined, null, 0, 'false'])('does not coerce unknown reachability %s into unreachable', async reachable => {
  xcmaxAdminApi.checkDeployUpdates.mockResolvedValue({ data: { ...data, enterprise: { reachable } } })
  await wrapper.vm.refresh()
  await nextTick()
  expect(field('企业端')).toBe('未知')
})

it.each([undefined, {}, { installed_devices: 0 }, { installed_devices: -1, failed_devices: 0 }])(
  'does not treat incomplete or invalid receipt summary %j as zero', async summary => {
    xcmaxAdminApi.listUpdateInstallReceipts.mockResolvedValue({ summary, items: [] })
    await wrapper.vm.refresh()
    await nextTick()
    expect(field('安装回执')).toBe('读取失败')
    expect(wrapper.find('.release-hint').text()).toContain('安装回执数据不完整')
  },
)
