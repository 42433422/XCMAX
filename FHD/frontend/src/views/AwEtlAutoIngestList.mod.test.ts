import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'
import AwEtlAutoIngestList from '../../../mods/xcagi-approval-bridge/frontend/views/approval-workspace/AwEtlAutoIngestList.vue'

const { autoIngestBatches, withdrawAutoIngestBatch, appConfirm } = vi.hoisted(() => ({
  appConfirm: vi.fn(),
  autoIngestBatches: vi.fn(),
  withdrawAutoIngestBatch: vi.fn(),
}))

vi.mock('@/utils/appDialog', () => ({ appConfirm }))

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
    appConfirm.mockReset().mockResolvedValue(true)
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
    expect(section.text()).toContain('业务域 客户')
    expect(section.get('details').text()).toContain('kb/abc')
    expect(section.get('details').text()).toContain('run-9')
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
  it('does not withdraw a running batch or submit after cancelling the scope confirmation', async () => {
    autoIngestBatches.mockResolvedValue([appliedBatch, { ...withdrawnBatch, status: 'running' }])
    appConfirm.mockResolvedValue(false)
    const wrapper = mount(AwEtlAutoIngestList)
    await flushPromises()
    expect(wrapper.findAll('li')[1].get('button').attributes('disabled')).toBeDefined()
    await wrapper.findAll('li')[0].get('button').trigger('click')
    await flushPromises()
    expect(appConfirm).toHaveBeenCalledWith(expect.stringContaining('原件和已保存模板保留'), { danger: true })
    expect(withdrawAutoIngestBatch).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it.each(['account', 'unmount'])('retires a pending withdrawal after %s changes', async (change) => {
    autoIngestBatches.mockResolvedValueOnce([appliedBatch]).mockResolvedValue([])
    let resolveConfirm!: (confirmed: boolean) => void
    appConfirm.mockImplementation(() => new Promise(resolve => { resolveConfirm = resolve }))
    const wrapper = mount(AwEtlAutoIngestList)
    await flushPromises()
    await wrapper.findAll('li')[0].get('button').trigger('click')
    if (change === 'account') productReadAccountEpoch.value++
    else wrapper.unmount()
    resolveConfirm(true)
    await flushPromises()
    expect(withdrawAutoIngestBatch).not.toHaveBeenCalled()
    if (change === 'account') {
      expect(wrapper.text()).not.toContain(appliedBatch.file_name)
      wrapper.unmount()
    }
  })

  it('ignores a prior account list response arriving after the new account', async () => {
    let resolveOld!: (items: unknown[]) => void
    autoIngestBatches.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve })).mockResolvedValue([])
    const wrapper = mount(AwEtlAutoIngestList)
    productReadAccountEpoch.value++
    await flushPromises()
    resolveOld([appliedBatch])
    await flushPromises()
    expect(wrapper.text()).not.toContain(appliedBatch.file_name)
    wrapper.unmount()
  })

})
