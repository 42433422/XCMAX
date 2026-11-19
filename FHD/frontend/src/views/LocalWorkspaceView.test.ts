import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import LocalWorkspaceView from './LocalWorkspaceView.vue'
import type { LocalArchive, LocalRecord } from '@/api/localWorkspace'

const api = vi.hoisted(() => ({
  status: vi.fn(), records: vi.fn(), write: vi.fn(), archives: vi.fn(),
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
  api.status.mockResolvedValue({ workspace_id: 'desk', cursor: 0, record_count: 1, paired: false, archives: [], archives_total: 0 })
  api.archives.mockResolvedValue({ archives: [], total: 0 })
  api.records.mockResolvedValue({ workspace_id: 'desk', cursor: 0, records: [original] })
  api.write.mockImplementation((_workspaceId, operation) => Promise.resolve({ accepted: [operation.op_id], conflicts: [] }))
})
afterEach(() => vi.clearAllMocks())

describe('LocalWorkspaceView', () => {
  function manyArchives() {
    const recent: LocalArchive[] = Array.from({ length: 100 }, (_, index) => ({
      archive_id: `recent-${index}`, workspace_id: 'archived', created_at: 1_800_000_000 - index, record_count: 1,
    }))
    const older: LocalArchive = { archive_id: 'older', workspace_id: 'original', created_at: 1_700_000_000, record_count: 2 }
    api.status.mockResolvedValue({ workspace_id: 'desk', cursor: 0, record_count: 1, paired: false, archives: recent, archives_total: 101 })
    api.archives.mockResolvedValue({ archives: [older], total: 101 })
    return older
  }

  it('keeps older archives reachable and restores the selected ID after refreshing', async () => {
    const older = manyArchives()
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const wrapper = view()
    try {
      await flushPromises()
      const navigation = () => wrapper.get('[aria-label="归档分页"]')
      expect(navigation().text()).toContain('第 1–100 条，共 101 条')
      await navigation().findAll('button')[1]!.trigger('click')
      await flushPromises()
      expect(api.archives).toHaveBeenCalledWith(100, 100)
      expect(navigation().text()).toContain('第 101–101 条，共 101 条')
      expect(navigation().findAll('button')[1]!.attributes('disabled')).toBeDefined()
      await wrapper.findAll('button').find(button => button.text() === '刷新记录')!.trigger('click')
      await flushPromises()
      expect(navigation().text()).toContain('第 101–101 条，共 101 条')
      await wrapper.get('aside .workspace-records button').trigger('click')
      await flushPromises()
      expect(api.restore).toHaveBeenCalledWith(older.archive_id, 'desk')
      await navigation().findAll('button')[0]!.trigger('click')
      await flushPromises()
      expect(api.archives).toHaveBeenLastCalledWith(0, 100)
    } finally { wrapper.unmount(); confirm.mockRestore() }
  })

  it('retains the current archive page when the next page cannot be read', async () => {
    manyArchives()
    api.archives.mockRejectedValueOnce(new Error('无法读取归档'))
    const wrapper = view()
    try {
      await flushPromises()
      await wrapper.get('[aria-label="归档分页"]').findAll('button')[1]!.trigger('click')
      await flushPromises()
      expect(wrapper.get('[role="alert"]').text()).toBe('无法读取归档')
      expect(wrapper.get('[aria-label="归档分页"]').text()).toContain('第 1–100 条，共 101 条')
      expect(wrapper.findAll('aside .workspace-records li')).toHaveLength(100)
    } finally { wrapper.unmount() }
  })

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

  it('writes a product with its edited price and preserves the local record contract', async () => {
    const wrapper = view()
    try {
      await flushPromises()
      await wrapper.findAll('button').find(button => button.text() === '商品')!.trigger('click')
      await wrapper.findAll('button').find(button => button.text() === '新建商品')!.trigger('click')
      const inputs = wrapper.findAll('form input')
      await inputs[0]!.setValue(' 商品一 ')
      await inputs[1]!.setValue(' SKU-1 ')
      await inputs[2]!.setValue('12.50')
      await wrapper.get('textarea').setValue(' 本地备注 ')
      await wrapper.get('form').trigger('submit')
      await flushPromises()
      expect(api.write).toHaveBeenCalledWith('desk', expect.objectContaining({
        kind: 'product', base_version: null, deleted: false,
        data: { name: '商品一', sku: 'SKU-1', unit_price: 12.5, notes: '本地备注' },
      }))
      expect(wrapper.find('form').exists()).toBe(false)
      expect(wrapper.get('[role="status"]').text()).toBe('已保存到本机。')
    } finally { wrapper.unmount() }
  })

  it('creates a draft order from the selected local customer and product', async () => {
    const product: LocalRecord = {
      id: 'product-1', kind: 'product', version: 'product-v1', deleted: false,
      data: { name: '商品一', unit_price: 12.5 },
    }
    api.records.mockResolvedValue({ workspace_id: 'desk', cursor: 0, records: [original, product] })
    const wrapper = view()
    try {
      await flushPromises()
      await wrapper.findAll('button').find(button => button.text() === '订单草稿')!.trigger('click')
      await wrapper.findAll('button').find(button => button.text() === '新建订单草稿')!.trigger('click')
      await wrapper.get('form input').setValue('线下订单')
      await wrapper.get('form select').setValue(original.id)
      const add = () => wrapper.findAll('button').find(button => button.text() === '添加商品行')!.trigger('click')
      await add()
      await wrapper.get('.workspace-line select').setValue(product.id)
      const inputs = wrapper.findAll('.workspace-line input')
      expect((inputs[1]!.element as HTMLInputElement).value).toBe('12.5')
      await inputs[0]!.setValue('3')
      await add()
      await wrapper.findAll('.workspace-line')[1]!.get('button').trigger('click')
      await wrapper.get('form').trigger('submit')
      await flushPromises()
      expect(api.write).toHaveBeenCalledWith('desk', expect.objectContaining({
        kind: 'order', base_version: null,
        data: {
          title: '线下订单', status: 'draft', notes: '', customer_id: original.id, customer: '原客户',
          items: [{ product_id: product.id, product_name: '商品一', quantity: 3, unit_price: 12.5 }],
        },
      }))
    } finally { wrapper.unmount() }
  })

  it('requires reading the conflicting version before retrying an edit', async () => {
    const latest = { ...original, version: 'version-2', data: { name: '手机更新客户', internal_note: '新字段' } }
    const wrapper = view()
    try {
      await flushPromises()
      await wrapper.get('[aria-label="编辑 原客户"]').trigger('click')
      await wrapper.get('form input').setValue('桌面编辑')
      api.records.mockResolvedValue({ workspace_id: 'desk', cursor: 1, records: [latest] })
      api.write.mockImplementationOnce((_workspace, operation) => Promise.resolve({
        accepted: [], conflicts: [{ op_id: operation.op_id, current: latest }],
      }))
      await wrapper.get('form').trigger('submit')
      await flushPromises()
      expect(wrapper.get('[role="alert"]').text()).toContain('记录已有更新')
      expect(wrapper.find('form').exists()).toBe(true)
      expect(api.write).toHaveBeenCalledOnce()
      await wrapper.findAll('button').find(button => button.text() === '读取当前版本')!.trigger('click')
      expect((wrapper.get('form input').element as HTMLInputElement).value).toBe('手机更新客户')
      await wrapper.get('form input').setValue('核对后更新')
      await wrapper.get('form').trigger('submit')
      await flushPromises()
      expect(api.write).toHaveBeenLastCalledWith('desk', expect.objectContaining({
        id: original.id, base_version: 'version-2',
        data: expect.objectContaining({ name: '核对后更新', internal_note: '新字段' }),
      }))
      expect(api.write.mock.calls[1]![1].op_id).not.toBe(api.write.mock.calls[0]![1].op_id)
      expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    } finally { wrapper.unmount() }
  })

  it('blocks writes when record and status workspaces differ and discards an old draft after switching', async () => {
    const wrapper = view()
    try {
      await flushPromises()
      await wrapper.get('[aria-label="编辑 原客户"]').trigger('click')
      await wrapper.get('form input').setValue('尚未保存的旧工作区内容')
      api.status.mockResolvedValue({ workspace_id: 'new-desk', cursor: 0, record_count: 0, paired: false, archives: [], archives_total: 0 })
      const refresh = () => wrapper.findAll('button').find(button => button.text() === '刷新记录')!.trigger('click')
      await refresh()
      await flushPromises()
      expect(wrapper.get('[role="alert"]').text()).toContain('工作区已切换')
      expect(wrapper.get('fieldset').attributes('disabled')).toBeDefined()
      await wrapper.get('form').trigger('submit')
      expect(api.write).not.toHaveBeenCalled()
      api.records.mockResolvedValue({ workspace_id: 'new-desk', cursor: 0, records: [] })
      await refresh()
      await flushPromises()
      expect(wrapper.find('form').exists()).toBe(false)
      expect(wrapper.text()).toContain('暂无客户')
      expect(wrapper.find('[role="alert"]').exists()).toBe(false)
      expect(wrapper.findAll('button').find(button => button.text() === '新建客户')!.attributes('disabled')).toBeUndefined()
    } finally { wrapper.unmount() }
  })
})
