/**
 * 智慧分析 · 经营/财报可视化看板：从业务库实时聚合 KPI、图表序列与明细表。
 */
import { ref } from 'vue'
import { kittenApi } from '@/api/kitten'
import { downloadBlob } from '@/utils'
import { appAlert } from '@/utils/appDialog'
import { formatExportTimestamp } from './kittenAnalyzerShared'

export interface KittenDashboardKpi {
  key: string
  label: string
  value: number
  unit: string
  delta_pct?: number | null
  hint?: string
}

export interface KittenDashboardCharts {
  revenue_trend: { labels: string[]; revenue: number[]; orders: number[]; cost: number[]; profit: number[] }
  product_mix: { labels: string[]; values: number[] }
  customer_ranking: { labels: string[]; amounts: number[]; orders: number[] }
  inventory_mix: { labels: string[]; values: number[] }
}

export interface KittenMonthlyRow {
  month: string
  revenue: number
  orders: number
  estimated_cost: number
  profit: number
  margin_pct: number
}

export interface KittenProductRow {
  rank: number
  product_name: string
  revenue: number
  quantity_kg: number
  quantity_tins: number
  orders: number
  share_pct: number
}

export interface KittenCustomerRow {
  rank: number
  customer: string
  revenue: number
  orders: number
  avg_order: number
  share_pct: number
}

export interface KittenInventoryRow {
  category: string
  value: number
  items: number
  low_stock: number
}

export interface KittenFinancialDashboard {
  generated_at: string
  months: number
  cost_estimate_ratio: number
  kpis: KittenDashboardKpi[]
  charts: KittenDashboardCharts
  tables: {
    monthly: KittenMonthlyRow[]
    products: KittenProductRow[]
    customers: KittenCustomerRow[]
    inventory: KittenInventoryRow[]
  }
  notes: string[]
}

function num(value: unknown): number {
  const n = Number(value)
  return Number.isFinite(n) ? n : 0
}

function str(value: unknown): string {
  return value == null ? '' : String(value)
}

function numList(value: unknown): number[] {
  return Array.isArray(value) ? value.map(num) : []
}

function strList(value: unknown): string[] {
  return Array.isArray(value) ? value.map(str) : []
}

function rec(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : {}
}

function list(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.map(rec) : []
}

export function normalizeDashboard(raw: unknown): KittenFinancialDashboard {
  const payload = rec(raw)
  const charts = rec(payload.charts)
  const tables = rec(payload.tables)
  const trend = rec(charts.revenue_trend)
  const productMix = rec(charts.product_mix)
  const customerRanking = rec(charts.customer_ranking)
  const inventoryMix = rec(charts.inventory_mix)
  return {
    generated_at: str(payload.generated_at),
    months: num(payload.months) || 6,
    cost_estimate_ratio: num(payload.cost_estimate_ratio),
    kpis: list(payload.kpis).map((item) => ({
      key: str(item.key),
      label: str(item.label),
      value: num(item.value),
      unit: str(item.unit),
      delta_pct: item.delta_pct == null ? null : num(item.delta_pct),
      hint: str(item.hint),
    })),
    charts: {
      revenue_trend: {
        labels: strList(trend.labels),
        revenue: numList(trend.revenue),
        orders: numList(trend.orders),
        cost: numList(trend.cost),
        profit: numList(trend.profit),
      },
      product_mix: { labels: strList(productMix.labels), values: numList(productMix.values) },
      customer_ranking: {
        labels: strList(customerRanking.labels),
        amounts: numList(customerRanking.amounts),
        orders: numList(customerRanking.orders),
      },
      inventory_mix: { labels: strList(inventoryMix.labels), values: numList(inventoryMix.values) },
    },
    tables: {
      monthly: list(tables.monthly).map((row) => ({
        month: str(row.month),
        revenue: num(row.revenue),
        orders: num(row.orders),
        estimated_cost: num(row.estimated_cost),
        profit: num(row.profit),
        margin_pct: num(row.margin_pct),
      })),
      products: list(tables.products).map((row) => ({
        rank: num(row.rank),
        product_name: str(row.product_name),
        revenue: num(row.revenue),
        quantity_kg: num(row.quantity_kg),
        quantity_tins: num(row.quantity_tins),
        orders: num(row.orders),
        share_pct: num(row.share_pct),
      })),
      customers: list(tables.customers).map((row) => ({
        rank: num(row.rank),
        customer: str(row.customer),
        revenue: num(row.revenue),
        orders: num(row.orders),
        avg_order: num(row.avg_order),
        share_pct: num(row.share_pct),
      })),
      inventory: list(tables.inventory).map((row) => ({
        category: str(row.category),
        value: num(row.value),
        items: num(row.items),
        low_stock: num(row.low_stock),
      })),
    },
    notes: strList(payload.notes),
  }
}

export function useKittenFinancialDashboard() {
  const data = ref<KittenFinancialDashboard | null>(null)
  const loading = ref(false)
  const error = ref('')
  const months = ref(6)

  const load = async (nextMonths?: number) => {
    if (typeof nextMonths === 'number') months.value = nextMonths
    loading.value = true
    error.value = ''
    try {
      const body = rec(await kittenApi.getFinancialDashboard(months.value))
      if (body.success === false || !body.data) {
        throw new Error(str(body.message) || '经营看板数据暂不可用')
      }
      data.value = normalizeDashboard(body.data)
    } catch (err) {
      data.value = null
      error.value = err instanceof Error ? err.message : String(err)
    } finally {
      loading.value = false
    }
  }

  const exportExcel = async () => {
    const dashboard = data.value
    if (!dashboard) return
    try {
      const XLSX = await import('xlsx')
      const workbook = XLSX.utils.book_new()
      XLSX.utils.book_append_sheet(
        workbook,
        XLSX.utils.json_to_sheet(
          dashboard.kpis.map((kpi) => ({ 指标: kpi.label, 数值: kpi.value, 单位: kpi.unit })),
        ),
        '核心指标',
      )
      XLSX.utils.book_append_sheet(workbook, XLSX.utils.json_to_sheet(dashboard.tables.monthly), '月度经营')
      XLSX.utils.book_append_sheet(workbook, XLSX.utils.json_to_sheet(dashboard.tables.products), '产品明细')
      XLSX.utils.book_append_sheet(workbook, XLSX.utils.json_to_sheet(dashboard.tables.customers), '客户排行')
      XLSX.utils.book_append_sheet(workbook, XLSX.utils.json_to_sheet(dashboard.tables.inventory), '库存结构')
      const array = XLSX.write(workbook, { bookType: 'xlsx', type: 'array' })
      downloadBlob(
        new Blob([array as unknown as BlobPart], {
          type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        }),
        `经营财报看板_${formatExportTimestamp()}.xlsx`,
      )
    } catch (err) {
      await appAlert(`导出失败：${err instanceof Error ? err.message : String(err)}`)
    }
  }

  return { data, loading, error, months, load, exportExcel }
}
