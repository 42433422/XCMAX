import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import LocalWorkspaceView from './LocalWorkspaceView.vue'
import type { LocalRecord } from '@/api/localWorkspace'

const api = vi.hoisted(() => ({
  status: vi.fn(), records: vi.fn(), write: vi.fn(),
  createPairing: vi.fn(), removePairing: vi.fn(), restore: vi.fn(),
}))

vi.mock('@/api/localWorkspace', () => ({ localWorkspaceApi: api }))
vi.mock('qrcode', () => ({ default: { toDataURL: vi.fn().mockResolvedValue('data:image/png;base64,qr') } }))

const original: LocalRecord = {
  id: 'customer-1',
  kind: 'customer',
  version: 'version-1',
  deleted: false,
  data: { name: '原客户', internal_note: '保留字段' },
}
function view() {
  return mount(LocalWorkspaceView, { global: { stubs: ['RouterLink'] } })
}

beforeEach(() => {
  api.status.mockResolvedValue({ workspace_id: 'desk', cursor: 0, record_count: 1, paired: false, archives: [] })
  api.records.mockResolvedValue({ workspace_id: 'desk', cursor: 0, records: [original] })
  api.write.mockImplementation((_workspaceId, operation) => Promise.resolve({ accepted: [operation.op_id], conflicts: [] }))
})
afterEach(() => vi.clearAllMocks())

describe('LocalWorkspaceView', () => {
  it('preserves existing fields and submits the current string version', async () => {
    const wrapper = view()
    try {
      await flushPromises()
      await wrapper.get('[aria-label="编辑 原客户"]').trigger('click')
      await wrapper.get('form input').setValue('更新客户')
      await wrapper.get('form').trigger('submit')
      await flushPromises()
      expect(api.write).toHaveBeenCalledWith('desk', expect.objectContaining({
        id: 'customer-1', kind: 'customer', base_version: 'version-1',
        data: expect.objectContaining({ name: '更新客户', internal_note: '保留字段' }),
      }))
      expect(wrapper.text()).toContain('已保存到本机')
    } finally { wrapper.unmount() }
  })

  it('creates an independent local record without a base version', async () => {
    const wrapper = view()
    try {
      await flushPromises()
      await wrapper.findAll('button').find(button => button.text() === '新建客户')!.trigger('click')
      await wrapper.get('form input').setValue('本地新客户')
      await wrapper.get('form').trigger('submit')
      await flushPromises()
      expect(api.write).toHaveBeenCalledWith('desk', expect.objectContaining({
        kind: 'customer', base_version: null, data: expect.objectContaining({ name: '本地新客户' }),
      }))
    } finally { wrapper.unmount() }
  })

  it('reuses the operation after a failed response to a local write', async () => {
    api.write.mockRejectedValueOnce(new Error('请求未确认'))
    const wrapper = view()
    try {
      await flushPromises()
      await wrapper.findAll('button').find(button => button.text() === '新建客户')!.trigger('click')
      await wrapper.get('form input').setValue('重试客户')
      await wrapper.get('form').trigger('submit')
      await flushPromises()
      expect(wrapper.get('[role="alert"]').text()).toBe('请求未确认')
      await wrapper.get('form').trigger('submit')
      await flushPromises()
      expect(api.write).toHaveBeenCalledTimes(2)
      expect(api.write.mock.calls[1]).toEqual(api.write.mock.calls[0])
    } finally { wrapper.unmount() }
  })

  it('keeps the QR visible until the phone binds or the invitation is withdrawn', async () => {
    api.createPairing.mockResolvedValue({ qr: { kind: 'xcagi_local_workspace', v: 1, endpoint: 'http://192.168.1.2:5000/api/local-workspace/peer', key: 'test-fixture' } })
    api.removePairing.mockResolvedValue({ paired: false })
    const wrapper = view()
    try {
      await flushPromises()
      await wrapper.findAll('button').find(button => button.text() === '生成绑定二维码')!.trigger('click')
      await flushPromises()
      expect(wrapper.get('img').attributes('alt')).toContain('绑定二维码')
      await wrapper.findAll('button').find(button => button.text() === '取消二维码')!.trigger('click')
      await flushPromises()
      expect(api.removePairing).toHaveBeenCalledOnce()
      expect(wrapper.find('img').exists()).toBe(false)
    } finally { wrapper.unmount() }
  })
})
