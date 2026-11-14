import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { nextTick } from 'vue'

const echarts = vi.hoisted(() => ({ use: vi.fn(), init: vi.fn() }))
vi.mock('echarts/core', () => echarts)
vi.mock('echarts/charts', () => ({ BarChart: {}, LineChart: {}, PieChart: {} }))
vi.mock('echarts/components', () => ({ GridComponent: {}, LegendComponent: {}, TooltipComponent: {} }))
vi.mock('echarts/renderers', () => ({ CanvasRenderer: {} }))

const api = vi.hoisted(() => ({ getFinancialDashboard: vi.fn() }))
vi.mock('@/api/kitten', () => ({ kittenApi: api }))

vi.mock('@/utils', () => ({ downloadBlob: vi.fn() }))
vi.mock('@/utils/appDialog', () => ({ appAlert: vi.fn().mockResolvedValue(undefined) }))
vi.mock('xlsx', () => ({
  utils: {
    book_new: vi.fn(() => ({})),
    book_append_sheet: vi.fn(),
    json_to_sheet: vi.fn(() => ({})),
  },
  write: vi.fn(() => new ArrayBuffer(8)),
}))

import { getCurrentInstance, h } from 'vue'

const ElTableStub = {
  props: { data: { type: Array, default: () => [] } },
  setup(_props: unknown, { slots }: { slots: { default?: () => unknown } }) {
    return () => h('div', { class: 'el-table-stub' }, slots.default ? (slots.default() as never) : [])
  },
}

const ElTableColumnStub = {
  props: { prop: String, label: String },
  setup(_props: unknown, { slots }: { slots: { default?: (slotProps: { row: unknown }) => unknown } }) {
    const instance = getCurrentInstance()
    return () => {
      const rows = ((instance?.parent?.props as { data?: unknown[] })?.data ?? []) as unknown[]
      const row = rows[0] ?? {}
      return h('div', { class: 'el-table-column-stub' }, slots.default ? (slots.default({ row }) as never) : [])
    }
  },
}

import KittenBusinessDashboard from './KittenBusinessDashboard.vue'
import { normalizeDashboard } from '@/composables/kittenAnalyzer/useKittenFinancialDashboard'
import { downloadBlob } from '@/utils'
import { appAlert } from '@/utils/appDialog'

const payload = {
  generated_at: '2026-11-14T02:00:00Z',
  months: 6,
  cost_estimate_ratio: 0.62,
  kpis: [
    { key: 'revenue', label: '营收', value: 1234567, unit: '元', delta_pct: 12.5, hint: '近 6 个月' },
    { key: 'orders', label: '出货单', value: 88, unit: '单', delta_pct: -3.2 },
    { key: 'products', label: '在售产品', value: 12, unit: '个' },
  ],
  charts: {
    revenue_trend: {
      labels: ['2026-06', '2026-07'],
      revenue: [100, 200],
      orders: [3, 5],
      cost: [60, 120],
      profit: [40, 80],
    },
    product_mix: { labels: ['A', 'B', 'C'], values: [50, 30, 20] },
    customer_ranking: { labels: ['客户甲', '客户乙'], amounts: [300, 200], orders: [2, 1] },
    inventory_mix: { labels: ['原料', '包材'], values: [500, 120] },
  },
  tables: {
    monthly: [
      { month: '2026-06', revenue: 100, orders: 3, estimated_cost: 60, profit: 40, margin_pct: 40 },
      { month: '2026-07', revenue: 200, orders: 5, estimated_cost: 120, profit: 80, margin_pct: 40 },
    ],
    products: [
      { rank: 1, product_name: '产品A', revenue: 50, quantity_kg: 10, quantity_tins: 3, orders: 2, share_pct: 50 },
    ],
    customers: [{ rank: 1, customer: '客户甲', revenue: 300, orders: 2, avg_order: 150, share_pct: 60 }],
    inventory: [{ category: '原料', value: 500, items: 12, low_stock: 2 }],
  },
  notes: ['成本为按出货量估算口径'],
}

function emptyPayload() {
  return {
    generated_at: '',
    months: 6,
    cost_estimate_ratio: 0,
    kpis: [],
    charts: {
      revenue_trend: { labels: [], revenue: [], orders: [], cost: [], profit: [] },
      product_mix: { labels: [], values: [] },
      customer_ranking: { labels: [], amounts: [], orders: [] },
      inventory_mix: { labels: [], values: [] },
    },
    tables: { monthly: [], products: [], customers: [], inventory: [] },
    notes: [],
  }
}

let wrapper: VueWrapper | undefined
let charts: Array<{ setOption: ReturnType<typeof vi.fn>; resize: ReturnType<typeof vi.fn>; dispose: ReturnType<typeof vi.fn> }>

beforeEach(() => {
  charts = []
  echarts.init.mockReset().mockImplementation(() => {
    const chart = { setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn() }
    charts.push(chart)
    return chart
  })
  api.getFinancialDashboard.mockReset().mockResolvedValue({ success: true, data: payload })
  vi.mocked(downloadBlob).mockReset()
  vi.mocked(appAlert).mockReset().mockResolvedValue(undefined)
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = undefined
})

async function open() {
  wrapper = mount(KittenBusinessDashboard, {
    global: {
      stubs: {
        'el-table': ElTableStub,
        'el-table-column': ElTableColumnStub,
      },
    },
  })
  await flushPromises()
  await nextTick()
  await nextTick()
  return wrapper
}

describe('normalizeDashboard', () => {
  it('falls back to safe defaults for unknown payloads', () => {
    const dashboard = normalizeDashboard(undefined)
    expect(dashboard.months).toBe(6)
    expect(dashboard.kpis).toEqual([])
    expect(dashboard.charts.revenue_trend.labels).toEqual([])
    expect(dashboard.tables.monthly).toEqual([])
    expect(dashboard.notes).toEqual([])
  })

  it('keeps numbers, strings and null deltas', () => {
    const dashboard = normalizeDashboard({
      ...payload,
      kpis: [{ key: 'revenue', label: '营收', value: '42', unit: '元', delta_pct: '3.5', hint: 7 }],
    })
    expect(dashboard.kpis[0]).toEqual({ key: 'revenue', label: '营收', value: 42, unit: '元', delta_pct: 3.5, hint: '7' })
    expect(dashboard.charts.customer_ranking.amounts).toEqual([300, 200])
    expect(dashboard.tables.inventory[0].low_stock).toBe(2)
  })
})

describe('KittenBusinessDashboard', () => {
  it('loads the dashboard and renders KPIs, charts, tables and notes', async () => {
    const view = await open()
    expect(api.getFinancialDashboard).toHaveBeenCalledWith(6)
    const text = view.text()
    expect(text).toContain('经营财报看板')
    expect(text).toContain('营收')
    expect(text).toContain('¥1,234,567')
    expect(text).toContain('↑ 12.5%')
    expect(text).toContain('↓ 3.2%')
    expect(text).toContain('88 单')
    expect(text).toContain('12 个')
    expect(text).toContain('成本为按出货量估算口径')
    expect(echarts.init).toHaveBeenCalledTimes(4)
    expect(charts).toHaveLength(4)
    charts.forEach((chart) => expect(chart.setOption).toHaveBeenCalledTimes(1))
    expect((charts[0].setOption.mock.lastCall![0] as { series: unknown[] }).series).toHaveLength(4)
    expect((charts[1].setOption.mock.lastCall![0] as { series: { data: unknown[] }[] }).series[0].data).toHaveLength(3)
  })

  it('reloads when the range changes and resizes with the window', async () => {
    const view = await open()
    api.getFinancialDashboard.mockResolvedValueOnce({ success: true, data: payload })
    await view.find('select.fin-select').setValue('12')
    await flushPromises()
    expect(api.getFinancialDashboard).toHaveBeenLastCalledWith(12)
    charts.forEach((chart) => chart.resize.mockClear())
    window.dispatchEvent(new Event('resize'))
    charts.forEach((chart) => expect(chart.resize).toHaveBeenCalled())
  })

  it('refreshes on demand and renders the detail tables', async () => {
    const view = await open()
    expect(view.text()).toContain('¥100')
    expect(view.text()).toContain('¥50')
    expect(view.text()).toContain('¥300')
    expect(view.text()).toContain('¥500')
    expect(view.find('.el-table-stub').exists()).toBe(true)
    await view.findAll('button').find((button) => button.text() === '刷新')!.trigger('click')
    await flushPromises()
    expect(api.getFinancialDashboard).toHaveBeenCalledTimes(2)
  })

  it('formats chart tooltips and groups the long tail of product revenue', async () => {
    const labels = Array.from({ length: 10 }, (_, index) => `产品${index + 1}`)
    api.getFinancialDashboard.mockResolvedValue({
      success: true,
      data: {
        ...payload,
        charts: {
          ...payload.charts,
          product_mix: { labels, values: [9, 8, 7, 6, 5, 4, 3, 2, 1, 1] },
        },
      },
    })
    await open()
    const pie = charts[1].setOption.mock.lastCall![0] as {
      tooltip: { valueFormatter: (value: unknown) => string }
      series: { data: { name: string; value: number }[] }[]
    }
    expect(pie.tooltip.valueFormatter(50)).toBe('¥50')
    expect(pie.series[0].data).toHaveLength(9)
    expect(pie.series[0].data[8]).toEqual({ name: '其他', value: 2 })

    const customer = charts[2].setOption.mock.lastCall![0] as {
      tooltip: { valueFormatter: (value: unknown) => string }
      series: { label: { formatter: (params: { value?: unknown }) => string } }[]
    }
    expect(customer.tooltip.valueFormatter(300)).toBe('¥300')
    expect(customer.series[0].label.formatter({ value: 200 })).toBe('¥200')

    const inventory = charts[3].setOption.mock.lastCall![0] as {
      tooltip: { valueFormatter: (value: unknown) => string }
    }
    expect(inventory.tooltip.valueFormatter(500)).toBe('¥500')
  })

  it('shows placeholders when the business database has no rows yet', async () => {
    api.getFinancialDashboard.mockResolvedValue({ success: true, data: emptyPayload() })
    const view = await open()
    const text = view.text()
    expect(text).toContain('暂无出货数据')
    expect(text).toContain('本月暂无产品出货')
    expect(text).toContain('本月暂无客户出货')
    expect(text).toContain('暂无原材料库存')
    expect(view.find('.fin-btn--primary').attributes('disabled')).toBeUndefined()
  })

  it('surfaces backend failures and retries', async () => {
    api.getFinancialDashboard.mockResolvedValueOnce({ success: false, message: '业务库暂不可用' })
    const view = await open()
    expect(view.text()).toContain('看板加载失败')
    expect(view.text()).toContain('业务库暂不可用')
    api.getFinancialDashboard.mockResolvedValueOnce({ success: true, data: payload })
    await view.findAll('button').find((button) => button.text() === '重试')!.trigger('click')
    await flushPromises()
    expect(view.text()).toContain('经营财报看板')
    expect(view.text()).toContain('¥1,234,567')
  })

  it('exports the dashboard to Excel and reports export failures', async () => {
    const view = await open()
    await view.find('.fin-btn--primary').trigger('click')
    await flushPromises()
    expect(downloadBlob).toHaveBeenCalledTimes(1)
    const [blob, filename] = vi.mocked(downloadBlob).mock.lastCall as [Blob, string]
    expect(blob.type).toContain('spreadsheetml')
    expect(filename).toMatch(/^经营财报看板_.+\.xlsx$/)

    vi.mocked(downloadBlob).mockImplementationOnce(() => {
      throw new Error('磁盘已满')
    })
    await view.find('.fin-btn--primary').trigger('click')
    await flushPromises()
    expect(appAlert).toHaveBeenCalledWith('导出失败：磁盘已满')
  })

  it('disposes charts on unmount', async () => {
    await open()
    wrapper!.unmount()
    wrapper = undefined
    charts.forEach((chart) => expect(chart.dispose).toHaveBeenCalledTimes(1))
  })
})
