import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { updateProductReadAccountScope } from '@/utils/productReadAccountScope'
import ReviewedExcelTemplate from './ReviewedExcelTemplate.vue'

const api = vi.hoisted(() => ({ archiveQuota: vi.fn(), setArchiveQuota: vi.fn(), archiveAssets: vi.fn(),
  setArchiveAssetState: vi.fn(), recoverArchiveVersion: vi.fn(), appendArchiveVersion: vi.fn() }))
vi.mock('@/api/templatePreview', () => ({ default: api }))
vi.mock('@/api/xcmaxMarketProxy', () => ({ default: { llmResolveChatDefault: vi.fn().mockResolvedValue(null) } }))
const asset = (state = 'active', status = 'ready') => ({ id: 'asset-1', name: 'synthetic.xlsx', state,
  versions: [{ id: 'version-1', version: 1, status, sha256: 'synthetic-sha', classification_id: null }] })
let wrapper: VueWrapper
const button = (label: string) => wrapper.findAll('button').find(item => item.text() === label)!
async function click(label: string) { await button(label).trigger('click'); await flushPromises() }
async function load() { await click('查看原件档案') }
function pending() { let resolve!: (value: unknown) => void; const promise = new Promise(done => { resolve = done }); return { promise, resolve } }
beforeEach(() => {
  vi.resetAllMocks()
  updateProductReadAccountScope({ tenantId: 1, localUserId: 'archive-test', accountKind: 'local' })
  api.archiveAssets.mockResolvedValue({ assets: [asset()] })
  api.archiveQuota.mockResolvedValue({ configured: true, limit_bytes: 2097152, reserved_bytes: 512 })
  wrapper = mount(ReviewedExcelTemplate)
})
afterEach(() => { wrapper.unmount(); vi.restoreAllMocks() })

describe('reviewed archive controls', () => {
  it.each([0, -1, 1.5, 1048577])('rejects invalid quota %s before sending', async value => {
    await wrapper.get('input[type=number]').setValue(value)
    await click('设置配额')
    expect(api.setArchiveQuota).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('请输入 1 至 1048576 MiB 的整数')
  })
  it('converts quota to bytes, refreshes receipt and shows save/read failures', async () => {
    await wrapper.get('input[type=number]').setValue(2)
    await click('设置配额')
    expect((api.setArchiveQuota.mock.calls[0][0] as FormData).get('limit_bytes')).toBe('2097152')
    expect(wrapper.text()).toContain('已预留 512 / 2097152 字节')
    api.setArchiveQuota.mockRejectedValueOnce(new Error('权限已撤销'))
    await click('设置配额'); expect(wrapper.text()).toContain('权限已撤销')
    api.archiveQuota.mockRejectedValueOnce(new Error('配额暂不可读'))
    await click('查看配额'); expect(wrapper.text()).toContain('配额暂不可读')
  })
  it('requires withdrawal confirmation and refreshes the restored asset', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    await load(); await click('撤回')
    expect(api.setArchiveAssetState).not.toHaveBeenCalled()
    confirm.mockReturnValue(true)
    api.archiveAssets.mockResolvedValueOnce({ assets: [asset('trashed')] })
    await click('撤回')
    expect(api.setArchiveAssetState.mock.calls[0][0]).toBe('asset-1')
    expect((api.setArchiveAssetState.mock.calls[0][1] as FormData).get('state')).toBe('trashed')
    expect(wrapper.text()).toContain('已撤回')
    await click('恢复')
    expect((api.setArchiveAssetState.mock.calls[1][1] as FormData).get('state')).toBe('active')
    expect(confirm).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('已归档')
  })
  it('recovers only the chosen pending version and retains errors for failed recovery', async () => {
    api.archiveAssets.mockResolvedValue({ assets: [asset('active', 'pending')] })
    await load(); await click('核对完整性并恢复')
    expect(api.recoverArchiveVersion).toHaveBeenCalledWith('version-1', expect.any(FormData))
    expect(api.archiveAssets).toHaveBeenCalledTimes(2)
    api.recoverArchiveVersion.mockRejectedValueOnce(new Error('原件不完整'))
    await click('核对完整性并恢复')
    expect(wrapper.get('[role=alert]').text()).toContain('原件不完整')
    expect(api.archiveAssets).toHaveBeenCalledTimes(2)
  })
  it('keeps selected bytes and request identity after an uncertain version write; blocks repeat clicks', async () => {
    await load()
    const source = new File(['synthetic version'], 'revision.xlsx')
    const input = wrapper.get('.reviewed-template__version-input')
    Object.defineProperty(input.element, 'files', { configurable: true, value: [source] })
    await input.trigger('change')
    api.appendArchiveVersion.mockRejectedValueOnce(new Error('响应中断'))
    await click('保存新版本')
    const first = api.appendArchiveVersion.mock.calls[0][1] as FormData
    expect(first.get('file')).toBe(source); expect(first.get('request_key')).toBeTruthy()
    expect(wrapper.get('[role=alert]').text()).toContain('勿重新选择文件重复提交')
    expect(wrapper.text()).toContain('revision.xlsx')
    const write = pending(); api.appendArchiveVersion.mockReturnValueOnce(write.promise)
    await button('保存新版本').trigger('click'); await flushPromises()
    expect(button('保存新版本').attributes('disabled')).toBeDefined()
    await button('保存新版本').trigger('click')
    expect(api.appendArchiveVersion).toHaveBeenCalledTimes(2)
    const retry = api.appendArchiveVersion.mock.calls[1][1] as FormData
    expect(retry.get('file')).toBe(source); expect(retry.get('request_key')).toBe(first.get('request_key'))
    write.resolve({}); await flushPromises()
    expect(wrapper.text()).not.toContain('revision.xlsx')
    expect(button('保存新版本').attributes('disabled')).toBeDefined()
    expect(api.archiveAssets).toHaveBeenCalledTimes(2)
  })
  it('discards an archive list response after the account changes', async () => {
    const request = pending(); api.archiveAssets.mockReturnValueOnce(request.promise)
    await button('查看原件档案').trigger('click')
    updateProductReadAccountScope({ tenantId: 2, localUserId: 'other-account', accountKind: 'local' })
    await flushPromises(); request.resolve({ assets: [asset()] }); await flushPromises()
    expect(wrapper.text()).not.toContain('synthetic.xlsx')
    expect(wrapper.find('.reviewed-template__version-input').exists()).toBe(false)
  })
})
