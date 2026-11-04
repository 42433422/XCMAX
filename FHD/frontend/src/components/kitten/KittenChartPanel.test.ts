import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import KittenChartPanel from './KittenChartPanel.vue'
import type { KittenChartConfig } from '@/composables/useKittenAnalyzer'
import type { KittenFieldProfile } from '@/utils/kittenDatasetParser'

const renderer = vi.hoisted(() => ({ use: vi.fn(), init: vi.fn() }))
vi.mock('echarts/core', () => renderer)
const profiles: KittenFieldProfile[] = [
  { name: 'customer', type: 'category', nonEmpty: 3, uniqueCount: 2 },
  { name: 'amount', type: 'number', nonEmpty: 3, uniqueCount: 3 },
  { name: 'channel', type: 'text', nonEmpty: 3, uniqueCount: 2 },
  { name: 'day', type: 'date', nonEmpty: 3, uniqueCount: 2 },
]
const config: KittenChartConfig = { type: 'bar', xField: 'customer', yField: 'amount', groupField: '', aggregate: 'sum' }
const rows = [
  { customer: 'A', amount: 10, channel: 'retail' },
  { customer: 'A', amount: '￥ 1,200', channel: 'retail' },
  { customer: 'B', amount: 20, channel: 'online' },
]
let wrapper: VueWrapper | undefined
let charts: Array<{ setOption: ReturnType<typeof vi.fn>; resize: ReturnType<typeof vi.fn>; dispose: ReturnType<typeof vi.fn> }>
beforeEach(() => {
  charts = []
  renderer.init.mockReset().mockImplementation(() => {
    const chart = { setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn() }
    charts.push(chart)
    return chart
  })
})
afterEach(() => { wrapper?.unmount(); wrapper = undefined })
async function open(overrides: Partial<InstanceType<typeof KittenChartPanel>['$props']> = {}) {
  wrapper = mount(KittenChartPanel, { props: { rows, fieldProfiles: profiles, config: { ...config }, recommendations: [], ...overrides } })
  await flushPromises()
  return wrapper
}
function option(index = 0) { return charts[index].setOption.mock.lastCall![0] }

describe('Business dataset chart panel', () => {
  it('waits for a category selection and exposes field types and configuration changes', async () => {
    const view = await open({ config: { ...config, xField: '' } })
    expect(view.text()).toContain('请选择一个 X / 分类字段')
    expect(renderer.init).not.toHaveBeenCalled()
    expect(view.findAll('select')[0].text()).toContain('day · 日期')
    expect(view.findAll('select')[0].text()).toContain('channel · 文本')
    expect(view.findAll('select')[1].text()).not.toContain('customer')
    await view.findAll('select')[0].setValue('customer')
    await view.findAll('select')[1].setValue('amount')
    await view.findAll('select')[2].setValue('avg')
    await view.findAll('select')[3].setValue('channel')
    await view.findAll('.chart-type-tab')[1].trigger('click')
    expect(view.emitted('updateConfig')).toEqual([[{ xField: 'customer' }], [{ yField: 'amount' }], [{ aggregate: 'avg' }], [{ groupField: 'channel' }], [{ type: 'line' }]])
  })

  it.each([
    ['sum', 1210], ['avg', 605], ['max', 1200], ['min', 10], ['count', 2],
  ] as const)('renders %s using the valid business values', async (aggregate, expected) => {
    await open({ rows: [...rows, { customer: 'A', amount: null }, { customer: 'A', amount: 'invalid' }, { customer: 'A', amount: Infinity }], config: { ...config, aggregate } })
    expect(option().xAxis.data).toEqual(['A', 'B'])
    expect(option().series[0].data).toEqual([aggregate === 'count' ? 5 : expected, aggregate === 'count' ? 1 : 20])
    expect(charts[0].setOption.mock.lastCall![1]).toBe(true)
  })

  it('keeps group totals aligned and fills absent category/group combinations with zero', async () => {
    await open({ config: { ...config, groupField: 'channel' }, palette: ['#123456'] })
    expect(option().color).toEqual(['#123456'])
    expect(option().series).toEqual([
      expect.objectContaining({ name: 'retail', type: 'bar', data: [1210, 0] }),
      expect.objectContaining({ name: 'online', type: 'bar', data: [0, 20] }),
    ])
  })

  it('counts records without a numeric field and preserves empty category labels', async () => {
    await open({ rows: [{ customer: null }, { customer: '' }, { customer: 'A' }], config: { ...config, yField: '', aggregate: 'sum' } })
    const labels = option().xAxis.data as string[]
    expect(option().series[0].data[labels.indexOf('空值')]).toBe(2)
    expect(option().series[0].data[labels.indexOf('A')]).toBe(1)
  })

  it.each(['line', 'area'] as const)('draws %s with correct series style and updates after data changes', async (type) => {
    const view = await open({ config: { ...config, type } })
    expect(option().series[0].type).toBe('line')
    expect(option().series[0].smooth).toBe(true)
    expect(option().series[0].areaStyle).toEqual(type === 'area' ? {} : undefined)
    await view.setProps({ rows: [{ customer: 'C', amount: 42 }] })
    await flushPromises()
    expect(renderer.init).toHaveBeenCalledTimes(1)
    expect(option().xAxis.data).toEqual(['C'])
    expect(option().series[0].data).toEqual([42])
  })

  it('renders pie totals across groups and dispatches a selected recommendation unchanged', async () => {
    const recommendation = { id: 'channel', label: '渠道销售额', description: '按渠道汇总销售额', config: { ...config, type: 'pie' as const } }
    const view = await open({ config: { ...config, type: 'pie', groupField: 'channel' }, recommendations: [recommendation] })
    expect(option().series[0].data).toEqual([{ name: 'A', value: 1210 }, { name: 'B', value: 20 }])
    await view.get('.recommendation-chip').trigger('click')
    expect(view.emitted('applyRecommendation')).toEqual([[recommendation]])
  })

  it('renders only finite scatter pairs, including formatted numbers, and handles missing Y selection', async () => {
    const view = await open({ rows: [
      { amount: '¥1，200', other: '25%' }, { amount: ' ', other: 1 },
      { amount: 'invalid', other: 2 }, { amount: 3, other: NaN },
      { amount: undefined, other: 1 }, { amount: 4, other: 5 },
    ], config: { ...config, type: 'scatter', xField: 'amount', yField: 'other' } })
    expect(option().series[0].data).toEqual([[1200, 25], [4, 5]])
    expect(option().xAxis).toEqual({ type: 'value', name: 'amount' })
    await view.setProps({ config: { ...config, type: 'scatter', xField: 'amount', yField: '' } })
    await flushPromises()
    expect(option().series[0].data).toEqual([])
  })

  it('limits large scatter samples to 500 and rotates dense category labels', async () => {
    const view = await open({ rows: Array.from({ length: 550 }, (_, index) => ({ amount: index, customer: `C${index}` })), config: { ...config, type: 'scatter', xField: 'amount', yField: 'amount' } })
    expect(option().series[0].data).toHaveLength(500)
    await view.setProps({ config: { ...config } })
    await flushPromises()
    expect(option().xAxis.data).toHaveLength(80)
    expect(option().xAxis.axisLabel.rotate).toBe(35)
  })

  it('renders three dashboard views and releases every chart and resize listener on exit', async () => {
    const view = await open({ dashboardMode: true, employeeName: '销售分析员工' })
    expect(view.get('.chart-title').text()).toBe('销售分析员工')
    expect(view.get('.chart-dashboard-kpi__value').text()).toBe('3')
    expect(charts).toHaveLength(3)
    expect(charts.map((_chart, index) => option(index).series[0].type)).toEqual(['bar', 'line', 'pie'])
    window.dispatchEvent(new Event('resize'))
    expect(charts.map((chart) => chart.resize.mock.calls.length)).toEqual([2, 2, 2])
    view.unmount()
    wrapper = undefined
    expect(charts.map((chart) => chart.dispose.mock.calls.length)).toEqual([1, 1, 1])
    window.dispatchEvent(new Event('resize'))
    expect(charts.map((chart) => chart.resize.mock.calls.length)).toEqual([2, 2, 2])
  })
})
