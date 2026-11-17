import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import ImplementationGoalsPanel from '../../../admin-console/src/components/admin/ImplementationGoalsPanel.vue'
import api from '@/api/core'

vi.mock('@/api/core', () => ({ default: { get: vi.fn() } }))
const get = vi.mocked(api.get)
let wrapper: VueWrapper
const goal = (id: number, status = 'open') => ({ id, text: `目标 ${id}`, status, priority: 'P1', employee_label: '测试质量运行员', line: 'P-S', day: '2026-11-17', scope_path: 'FHD' })
beforeEach(() => get.mockReset())
afterEach(() => wrapper?.unmount())

describe('ImplementationGoalsPanel', () => {
  it('uses the authenticated update list and preserves merged as distinct from acceptance', async () => {
    get.mockResolvedValue({ success: true, data: { ok: true, day: '2026-11-17', items: [goal(1, 'merged')] } })
    wrapper = mount(ImplementationGoalsPanel)
    await flushPromises()
    expect(get).toHaveBeenCalledWith('/api/xcmax/admin/action-items', { kind: 'update' }, expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(wrapper.text()).toContain('记录日期 2026-11-17')
    expect(wrapper.text()).toContain('已合入')
    expect(wrapper.text()).not.toMatch(/已验收|已闭环|iframe/)
    await wrapper.get('[aria-label="查看目标 1"]').trigger('click')
    expect(wrapper.get('[aria-label="目标详情"]').text()).toContain('测试质量运行员')
    expect(wrapper.get('[aria-label="目标详情"]').text()).toContain('FHD')
  })

  it('paginates results, resets the page when filtering, and searches owners', async () => {
    get.mockResolvedValue({ items: Array.from({ length: 10 }, (_, i) => goal(i + 1, i < 8 ? 'open' : 'in_progress')) })
    wrapper = mount(ImplementationGoalsPanel)
    await flushPromises()
    expect(wrapper.findAll('tbody tr')).toHaveLength(8)
    await wrapper.findAll('.goals-pager button')[1].trigger('click')
    expect(wrapper.findAll('tbody tr')).toHaveLength(2)
    await wrapper.get('[aria-label="目标状态"]').setValue('open')
    expect(wrapper.text()).toContain('1 / 1')
    await wrapper.get('[aria-label="搜索目标"]').setValue('质量运行员')
    expect(wrapper.findAll('tbody tr')).toHaveLength(8)
    await wrapper.get('[aria-label="搜索目标"]').setValue('没有的目标')
    expect(wrapper.text()).toContain('没有符合筛选条件的目标')
  })

  it.each([{ success: false, data: { items: [] } }, { ok: false, items: [] }, { success: true, data: {} }])('does not present a failed or malformed response as an empty list', async response => {
    get.mockResolvedValueOnce(response).mockResolvedValueOnce({ ok: true, items: [] })
    wrapper = mount(ImplementationGoalsPanel)
    await flushPromises()
    expect(wrapper.find('[role="alert"]').exists()).toBe(true)
    expect(wrapper.text()).not.toContain('暂无目标记录')
    await wrapper.get('[role="alert"] button').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('暂无目标记录')
  })

  it('ignores superseded dates and cancels requests when leaving the page', async () => {
    let finish!: (value: unknown) => void
    get.mockReturnValueOnce(new Promise(resolve => { finish = resolve })).mockResolvedValueOnce({ day: '2026-11-16', items: [goal(2)] })
    wrapper = mount(ImplementationGoalsPanel)
    const firstSignal = get.mock.calls[0][2]?.signal
    await wrapper.get('[aria-label="记录日期"]').setValue('2026-11-16')
    await flushPromises()
    expect(firstSignal?.aborted).toBe(true)
    expect(get.mock.calls[1][1]).toEqual({ kind: 'update', day: '2026-11-16' })
    finish({ day: '2026-11-17', items: [goal(1)] })
    await flushPromises()
    expect(wrapper.text()).toContain('记录日期 2026-11-16')
    expect(wrapper.find('[aria-label="查看目标 1"]').exists()).toBe(false)
    wrapper.unmount()
    expect(get.mock.calls[1][2]?.signal?.aborted).toBe(true)
  })
})
