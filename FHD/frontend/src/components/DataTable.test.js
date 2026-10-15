import { afterEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { h, nextTick } from 'vue'
import DataTable from './DataTable.vue'

let wrapper
afterEach(() => { wrapper?.unmount(); wrapper = undefined; vi.restoreAllMocks() })
function open(props = {}, slots = {}) {
  wrapper = mount(DataTable, { props: { columns: [{ key: 'name', label: '客户名称' }], ...props }, slots })
  return wrapper
}

describe('Business data table', () => {
  it('distinguishes an empty business dataset from loading and computes the complete column span', async () => {
    const view = open({ selectable: true, emptyText: '没有客户' }, { actions: () => h('button', '查看客户') })
    expect(view.get('.empty-state').text()).toBe('没有客户')
    expect(view.get('.empty-state').attributes('colspan')).toBe('3')
    await view.setProps({ loading: true })
    expect(view.get('.empty-state').text()).toBe('加载中...')
    await view.setProps({ data: [{ id: 1, name: 'SUNBIRD' }] })
    expect(view.text()).toContain('SUNBIRD')
    expect(view.get('.loading-state').text()).toBe('加载中...')
    await view.setProps({ loading: false, hasMore: false })
    expect(view.get('.no-more-tip').text()).toBe('没有更多数据了')
    expect(view.find('.loading-state').exists()).toBe(false)
  })

  it('renders nested fields with explicit missing defaults while retaining zero business values', () => {
    const view = open({ columns: [
      { key: 'customer.name', label: '客户' }, { key: 'amount', label: '金额' },
      { key: 'optional.value', label: '说明', default: '未填写' }, { key: 'missing', label: '缺项' },
    ], data: [{ id: 1, customer: { name: 'Mac验收客户' }, amount: 0 }, { id: 2, customer: null, amount: null }] })
    const rows = view.findAll('tbody tr')
    expect(rows[0].findAll('td').map((cell) => cell.text())).toEqual(['Mac验收客户', '0', '未填写', '-'])
    expect(rows[1].findAll('td').map((cell) => cell.text())).toEqual(['-', '-', '未填写', '-'])
  })

  it('passes actual row values and indexes to custom cells and action controls', async () => {
    const action = vi.fn()
    const view = open({ data: [{ id: 1, name: 'SUNBIRD' }] }, {
      'cell-name': ({ value }) => h('strong', `企业：${value}`),
      actions: ({ row, index }) => h('button', { onClick: () => action(row.id, index) }, '查看客户'),
    })
    expect(view.get('strong').text()).toBe('企业：SUNBIRD')
    await view.get('tbody button').trigger('click')
    expect(action).toHaveBeenCalledExactlyOnceWith(1, 0)
  })

  it('selects displayed customer IDs and publishes the selected set once for each checkbox change', async () => {
    vi.spyOn(console, 'log').mockImplementation(() => {})
    const view = open({ selectable: true, data: [{ id: 1, name: 'A' }, { id: 2, name: 'B' }] })
    await view.findAll('tbody input')[0].setValue(true)
    await nextTick()
    expect(view.emitted('update:selectedIds')).toEqual([[[1]]])
    expect(view.emitted('select-change')).toEqual([[[1]]])
    await view.get('thead input').setValue(true)
    await nextTick()
    expect(view.emitted('update:selectedIds').at(-1)).toEqual([[1, 2]])
    await view.get('thead input').setValue(false)
    await nextTick()
    expect(view.emitted('update:selectedIds').at(-1)).toEqual([[]])
  })

  it('syncs an external selection without echoing a second update back to its parent', async () => {
    const view = open({ selectable: true, data: [{ id: 1, name: 'A' }, { id: 2, name: 'B' }], selectedIds: [1] })
    expect(view.findAll('tbody input')[0].element.checked).toBe(true)
    await view.setProps({ selectedIds: [2] })
    await nextTick()
    expect(view.findAll('tbody input').map((input) => input.element.checked)).toEqual([false, true])
    expect(view.emitted('update:selectedIds')).toBeUndefined()
    await view.setProps({ data: [{ id: 2, name: 'B updated' }] })
    expect(view.text()).toContain('B updated')
  })

  it('supports custom row identifiers and its public select-all/clear-selection controls', async () => {
    const view = open({ selectable: true, rowKey: 'customerId', data: [{ customerId: 'C1', name: 'A' }, { customerId: 'C2', name: 'B' }] })
    view.vm.selectAll()
    await nextTick()
    await nextTick()
    expect(view.emitted('update:selectedIds').at(-1)).toEqual([['C1', 'C2']])
    expect(view.get('thead input').element.checked).toBe(true)
    view.vm.clearSelection()
    await nextTick()
    expect(view.emitted('update:selectedIds').at(-1)).toEqual([[]])
    expect(view.get('thead input').element.checked).toBe(false)
  })

  it.each([{ loading: true }, { hasMore: false }])('does not request more data while unavailable: %s', async (flags) => {
    const view = open({ data: [{ id: 1, name: 'A' }], ...flags })
    await view.get('.data-table-wrapper').trigger('scroll')
    expect(view.emitted('load-more')).toBeUndefined()
  })

  it('requests the next page only near the bottom of the actual scroll container', async () => {
    const view = open({ data: [{ id: 1, name: 'A' }] })
    const scroll = view.get('.data-table-wrapper')
    Object.defineProperties(scroll.element, { scrollTop: { value: 0, writable: true }, scrollHeight: { value: 1000 }, clientHeight: { value: 500 } })
    await scroll.trigger('scroll')
    expect(view.emitted('load-more')).toBeUndefined()
    scroll.element.scrollTop = 401
    await scroll.trigger('scroll')
    expect(view.emitted('load-more')).toEqual([[]])
    expect(view.get('.has-more-tip').text()).toBe('滚动加载更多')
  })
})
