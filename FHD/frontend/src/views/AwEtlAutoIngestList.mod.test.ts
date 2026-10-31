import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import AwEtlAutoIngestList from '../../../mods/xcagi-approval-bridge/frontend/views/approval-workspace/AwEtlAutoIngestList.vue'

const { autoIngestBatches, withdrawAutoIngestBatch } = vi.hoisted(() => ({
  autoIngestBatches: vi.fn(),
  withdrawAutoIngestBatch: vi.fn(),
}))

vi.mock('@/api/elt', () => ({
  eltApi: {
    autoIngestBatches,
    withdrawAutoIngestBatch,
    autoIngestProgress: vi.fn(),
  },
}))

const appliedBatch = {
  batch_id: 'aib/42',
  file_name: '客户账.xlsx',
  status: 'applied',
  detection: { target_type: 'customer' },
  knowledge: { match_ref: 'kb/abc' },
  business: { run_id: 'run-9', target_type: 'customer' },
}

const withdrawnBatch = {
  batch_id: 'aib/7',
  file_name: '已撤批次.xlsx',
  status: 'withdrawn',
}

describe('AwEtlAutoIngestList (approval Mod bridge)', () => {
  beforeEach(() => {
    autoIngestBatches.mockReset()
    withdrawAutoIngestBatch.mockReset()
    autoIngestBatches.mockResolvedValue([])
    withdrawAutoIngestBatch.mockResolvedValue({ ok: true })
  })

  it('loads mine batches on mount and shows the empty state', async () => {
    const wrapper = mount(AwEtlAutoIngestList)
    await flushPromises()
    expect(autoIngestBatches).toHaveBeenCalledWith(50, true)
    expect(wrapper.get('[aria-label="数据对接自动入库"]').text()).toContain('暂无自动入库批次')
    expect(wrapper.find('ul.aw-etl-auto-ingest__list').exists()).toBe(false)
    wrapper.unmount()
  })

  it('renders batch rows with domain / KB / business markers and a withdraw control', async () => {
    autoIngestBatches.mockResolvedValue([appliedBatch, withdrawnBatch])
    const wrapper = mount(AwEtlAutoIngestList)
    await flushPromises()
    const section = wrapper.get('[aria-label="数据对接自动入库"]')
    expect(section.text()).toContain('客户账.xlsx')
    expect(section.text()).toContain('业务域 customer')
    expect(section.text()).toContain('KB kb/abc')
    expect(section.text()).toContain('ETL run-9')
    expect(section.text()).toContain('已撤批次.xlsx')
    const withdrawBtn = wrapper.findAll('button').find((b) => b.text() === '撤回')
    const withdrawnBtn = wrapper.findAll('button').find((b) => b.text() === '已撤回')
    expect(withdrawBtn).toBeTruthy()
    expect(withdrawnBtn).toBeTruthy()
    expect(withdrawnBtn!.attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })

  it('keeps a list failure distinct from empty and retries the same scope', async () => {
    autoIngestBatches.mockRejectedValueOnce(new Error('暂时无法读取入库批次'))
    const wrapper = mount(AwEtlAutoIngestList)
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('暂时无法读取入库批次')
    expect(wrapper.text()).not.toContain('暂无自动入库批次')
    autoIngestBatches.mockResolvedValueOnce([appliedBatch])
    await wrapper.get('[role="alert"] button').trigger('click')
    await flushPromises()
    expect(autoIngestBatches).toHaveBeenLastCalledWith(50, true)
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('客户账.xlsx')
    wrapper.unmount()
  })

  it('withdraws an applied batch then reloads the list', async () => {
    autoIngestBatches
      .mockResolvedValueOnce([appliedBatch])
      .mockResolvedValueOnce([{ ...appliedBatch, status: 'withdrawn' }])
    const wrapper = mount(AwEtlAutoIngestList)
    await flushPromises()
    await wrapper.findAll('button').find((b) => b.text() === '撤回')!.trigger('click')
    await flushPromises()
    expect(withdrawAutoIngestBatch).toHaveBeenCalledWith('aib/42')
    expect(autoIngestBatches).toHaveBeenCalledTimes(2)
    expect(wrapper.findAll('button').some((b) => b.text() === '已撤回')).toBe(true)
    expect(wrapper.findAll('button').some((b) => b.text() === '撤回')).toBe(false)
    wrapper.unmount()
  })

  it('surfaces a withdraw failure without clearing the visible list', async () => {
    autoIngestBatches.mockResolvedValue([appliedBatch])
    withdrawAutoIngestBatch.mockRejectedValueOnce(new Error('撤回失败：批次依赖未解绑'))
    const wrapper = mount(AwEtlAutoIngestList)
    await flushPromises()
    await wrapper.findAll('button').find((b) => b.text() === '撤回')!.trigger('click')
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('撤回失败：批次依赖未解绑')
    expect(wrapper.text()).toContain('客户账.xlsx')
    expect(autoIngestBatches).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('refresh button reloads with the same mine scope', async () => {
    autoIngestBatches.mockResolvedValueOnce([]).mockResolvedValueOnce([appliedBatch])
    const wrapper = mount(AwEtlAutoIngestList)
    await flushPromises()
    await wrapper.findAll('button').find((b) => b.text() === '刷新')!.trigger('click')
    await flushPromises()
    expect(autoIngestBatches).toHaveBeenNthCalledWith(1, 50, true)
    expect(autoIngestBatches).toHaveBeenNthCalledWith(2, 50, true)
    expect(wrapper.text()).toContain('客户账.xlsx')
    wrapper.unmount()
  })
})
