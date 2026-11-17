import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import MarketOverviewPanel from '../../../admin-console/src/components/admin/MarketOverviewPanel.vue'
import { xcmaxMarketProxy } from '@/api/xcmaxMarketProxy'

const { listCatalog, reviewCatalog, confirm, prompt } = vi.hoisted(() => ({
  listCatalog: vi.fn(),
  reviewCatalog: vi.fn(),
  confirm: vi.fn(),
  prompt: vi.fn(),
}))

vi.mock('@/api/xcmaxMarketProxy', () => ({
  xcmaxMarketProxy: {
    adminListCatalog: (...args: unknown[]) => listCatalog(...args),
    adminReviewCatalog: (...args: unknown[]) => reviewCatalog(...args),
  },
}))
vi.mock('@/utils/appDialog', () => ({
  appConfirm: (...args: unknown[]) => confirm(...args),
  appPrompt: (...args: unknown[]) => prompt(...args),
}))

const pendingItem = {
  id: 7,
  pkg_id: 'contract-review-employee',
  name: '合同审核员工',
  artifact: 'employee_pack',
  industry: '法务',
  version: '1.2.0',
  author_id: 12,
  author_name: 'guosheng',
  compliance_status: 'under_review',
  is_public: false,
  price: 199,
  created_at: '2026-11-17T08:00:00',
  delist_reason: '',
}

const payload = {
  items: [pendingItem],
  total: 1,
  counts: { total: 12, pending: 1, listed: 8, restricted: 1, delisted: 2 },
}

function mountPanel() {
  return mount(MarketOverviewPanel, { global: { stubs: { transition: false } } })
}

beforeEach(() => {
  vi.clearAllMocks()
  listCatalog.mockResolvedValue(structuredClone(payload))
  reviewCatalog.mockResolvedValue({ ok: true })
  confirm.mockResolvedValue(true)
  prompt.mockResolvedValue('质量证据不足')
})

describe('MarketOverviewPanel 运营台', () => {
  it('renders audit counts and pending employee rows', async () => {
    const wrapper = mountPanel()
    await flushPromises()
    const text = wrapper.text()
    expect(text).toContain('智能生态市场 · 运营台')
    for (const value of ['12', '1', '8', '1', '2']) expect(text).toContain(value)
    expect(text).toContain('合同审核员工')
    expect(text).toContain('contract-review-employee')
    expect(text).toContain('待审核')
    expect(text).toContain('通过并上架')
    expect(text).toContain('下架')
    wrapper.unmount()
  })

  it('searches and filters by audit status through the catalog endpoint', async () => {
    const wrapper = mountPanel()
    await flushPromises()
    await wrapper.find('input').setValue('合同')
    await wrapper.find('input').trigger('keyup.enter')
    await flushPromises()
    expect(listCatalog).toHaveBeenLastCalledWith(50, 0, '', '合同')

    wrapper.findComponent({ name: 'ElSelect' }).vm.$emit('update:modelValue', 'pending')
    await wrapper.vm.load()
    await flushPromises()
    expect(listCatalog).toHaveBeenLastCalledWith(50, 0, 'pending', '合同')
    wrapper.unmount()
  })

  it('keeps a newer filter result when an earlier request finishes late', async () => {
    let finishOld!: (value: typeof payload) => void
    listCatalog.mockImplementationOnce(() => new Promise((resolve) => { finishOld = resolve }))
    const wrapper = mountPanel()
    await flushPromises()
    listCatalog.mockResolvedValueOnce({ ...payload, items: [{ ...pendingItem, name: '新筛选结果' }] })
    await wrapper.find('input').setValue('新筛选')
    await wrapper.find('input').trigger('keyup.enter')
    await flushPromises()
    expect(listCatalog).toHaveBeenLastCalledWith(50, 0, '', '新筛选')
    expect(wrapper.text()).toContain('新筛选结果')
    finishOld(payload)
    await flushPromises()
    expect(wrapper.text()).toContain('新筛选结果')
    expect(wrapper.text()).not.toContain('合同审核员工')
    wrapper.unmount()
  })

  it('approves a pending employee after confirmation' , async () => {
    const wrapper = mountPanel()
    await flushPromises()
    const approve = wrapper.findAll('button').find((row) => row.text() === '通过并上架')!
    await approve.trigger('click')
    await flushPromises()
    expect(confirm).toHaveBeenCalled()
    expect(reviewCatalog).toHaveBeenCalledWith(7, 'approve', '')
    expect(listCatalog).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })

  it('requires a concrete reason before delisting', async () => {
    const wrapper = mountPanel()
    await flushPromises()
    prompt.mockResolvedValueOnce('短')
    const delist = wrapper.findAll('button').find((row) => row.text() === '下架')!
    await delist.trigger('click')
    await flushPromises()
    expect(reviewCatalog).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('下架原因至少 4 个字')

    prompt.mockResolvedValueOnce('质量证据不足')
    await wrapper.findAll('button').find((row) => row.text() === '下架')!.trigger('click')
    await flushPromises()
    expect(reviewCatalog).toHaveBeenCalledWith(7, 'delist', '质量证据不足')
    wrapper.unmount()
  })

  it('shows the server error without inventing data', async () => {
    listCatalog.mockRejectedValueOnce(new Error('市场接口不可用'))
    const wrapper = mountPanel()
    await flushPromises()
    expect(wrapper.text()).toContain('市场接口不可用')
    expect(wrapper.text()).toContain('暂无数据')
    wrapper.unmount()
  })
})
