<template>
  <section class="fin-dashboard">
    <header class="fin-dashboard__head">
      <div>
        <div class="fin-dashboard__title">经营财报看板</div>
        <div class="fin-dashboard__subtitle">
          业务库实时聚合 · 出货 / 产品 / 客户 / 库存
          <span v-if="data?.generated_at"> · {{ formatTime(data.generated_at) }}</span>
        </div>
      </div>
      <div class="fin-dashboard__actions">
        <select class="fin-select" :value="months" aria-label="统计区间" @change="onMonthsChange">
          <option :value="6">近 6 个月</option>
          <option :value="12">近 12 个月</option>
          <option :value="24">近 24 个月</option>
        </select>
        <button class="fin-btn" type="button" :disabled="loading" @click="load()">
          {{ loading ? '刷新中…' : '刷新' }}
        </button>
        <button class="fin-btn fin-btn--primary" type="button" :disabled="!data" @click="exportExcel">
          导出 Excel
        </button>
      </div>
    </header>

    <div v-if="error" class="fin-state fin-state--error">
      <strong>看板加载失败</strong>
      <p>{{ error }}</p>
      <button class="fin-btn" type="button" @click="load()">重试</button>
    </div>

    <div v-else-if="loading && !data" class="fin-state">正在从业务库聚合看板数据…</div>

    <template v-else-if="data">
      <div class="fin-kpis">
        <div v-for="kpi in data.kpis" :key="kpi.key" class="fin-kpi">
          <div class="fin-kpi__label">{{ kpi.label }}</div>
          <div class="fin-kpi__value">{{ formatKpi(kpi) }}</div>
          <div class="fin-kpi__meta">
            <span
              v-if="kpi.delta_pct !== null && kpi.delta_pct !== undefined"
              :class="['fin-delta', kpi.delta_pct >= 0 ? 'is-up' : 'is-down']"
            >
              {{ kpi.delta_pct >= 0 ? '↑' : '↓' }} {{ Math.abs(kpi.delta_pct) }}%
            </span>
            <span v-if="kpi.hint">{{ kpi.hint }}</span>
          </div>
        </div>
      </div>

      <div class="fin-charts">
        <div class="fin-card fin-card--wide">
          <div class="fin-card__head">
            <span>营收 / 成本 / 估算毛利趋势</span>
            <span class="fin-card__tag">双轴</span>
          </div>
          <div ref="trendEl" class="fin-chart fin-chart--trend" />
          <div v-if="!data.charts.revenue_trend.labels.length" class="fin-chart-empty">暂无出货数据</div>
        </div>
        <div class="fin-card">
          <div class="fin-card__head"><span>本月产品营收占比</span></div>
          <div ref="productEl" class="fin-chart" />
          <div v-if="!data.charts.product_mix.labels.length" class="fin-chart-empty">本月暂无产品出货</div>
        </div>
        <div class="fin-card">
          <div class="fin-card__head"><span>本月客户销售额排行</span></div>
          <div ref="customerEl" class="fin-chart" />
          <div v-if="!data.charts.customer_ranking.labels.length" class="fin-chart-empty">本月暂无客户出货</div>
        </div>
        <div class="fin-card">
          <div class="fin-card__head"><span>原材料库存货值结构</span></div>
          <div ref="inventoryEl" class="fin-chart" />
          <div v-if="!data.charts.inventory_mix.labels.length" class="fin-chart-empty">暂无原材料库存</div>
        </div>
      </div>

      <div class="fin-tables">
        <div class="fin-card">
          <div class="fin-card__head"><span>月度经营明细</span><span class="fin-card__tag">估算口径</span></div>
          <el-table :data="data.tables.monthly" size="small" border stripe max-height="280" empty-text="暂无数据">
            <el-table-column prop="month" label="月份" width="90" />
            <el-table-column label="营收" min-width="110">
              <template #default="{ row }">{{ formatMoney(row.revenue) }}</template>
            </el-table-column>
            <el-table-column prop="orders" label="出货单" width="80" />
            <el-table-column label="估算成本" min-width="110">
              <template #default="{ row }">{{ formatMoney(row.estimated_cost) }}</template>
            </el-table-column>
            <el-table-column label="估算毛利" min-width="110">
              <template #default="{ row }">{{ formatMoney(row.profit) }}</template>
            </el-table-column>
            <el-table-column label="毛利率" width="90">
              <template #default="{ row }">{{ row.margin_pct }}%</template>
            </el-table-column>
          </el-table>
        </div>

        <div class="fin-card">
          <div class="fin-card__head"><span>产品出货明细（本月）</span></div>
          <el-table :data="data.tables.products" size="small" border stripe max-height="280" empty-text="暂无数据">
            <el-table-column prop="rank" label="#" width="50" />
            <el-table-column prop="product_name" label="产品" min-width="130" show-overflow-tooltip />
            <el-table-column label="营收" min-width="110">
              <template #default="{ row }">{{ formatMoney(row.revenue) }}</template>
            </el-table-column>
            <el-table-column prop="quantity_kg" label="出货 kg" width="95" />
            <el-table-column prop="quantity_tins" label="罐数" width="80" />
            <el-table-column prop="orders" label="单数" width="70" />
            <el-table-column label="占比" width="80">
              <template #default="{ row }">{{ row.share_pct }}%</template>
            </el-table-column>
          </el-table>
        </div>

        <div class="fin-card">
          <div class="fin-card__head"><span>客户销售排行（本月）</span></div>
          <el-table :data="data.tables.customers" size="small" border stripe max-height="280" empty-text="暂无数据">
            <el-table-column prop="rank" label="#" width="50" />
            <el-table-column prop="customer" label="客户" min-width="140" show-overflow-tooltip />
            <el-table-column label="营收" min-width="110">
              <template #default="{ row }">{{ formatMoney(row.revenue) }}</template>
            </el-table-column>
            <el-table-column prop="orders" label="单数" width="70" />
            <el-table-column label="客单价" min-width="100">
              <template #default="{ row }">{{ formatMoney(row.avg_order) }}</template>
            </el-table-column>
            <el-table-column label="占比" width="80">
              <template #default="{ row }">{{ row.share_pct }}%</template>
            </el-table-column>
          </el-table>
        </div>

        <div class="fin-card">
          <div class="fin-card__head"><span>原材料库存结构</span></div>
          <el-table :data="data.tables.inventory" size="small" border stripe max-height="280" empty-text="暂无库存数据">
            <el-table-column prop="category" label="分类" min-width="120" show-overflow-tooltip />
            <el-table-column label="库存货值" min-width="120">
              <template #default="{ row }">{{ formatMoney(row.value) }}</template>
            </el-table-column>
            <el-table-column prop="items" label="条目" width="70" />
            <el-table-column prop="low_stock" label="低库存" width="80" />
          </el-table>
        </div>
      </div>

      <ul v-if="data.notes.length" class="fin-notes">
        <li v-for="note in data.notes" :key="note">{{ note }}</li>
      </ul>
    </template>
  </section>
</template>

<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart, LineChart, PieChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { EChartsCoreOption } from 'echarts/core'
import {
  useKittenFinancialDashboard,
  type KittenDashboardKpi,
} from '@/composables/kittenAnalyzer/useKittenFinancialDashboard'

echarts.use([BarChart, LineChart, PieChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

const { data, loading, error, months, load, exportExcel } = useKittenFinancialDashboard()

const trendEl = ref<HTMLDivElement | null>(null)
const productEl = ref<HTMLDivElement | null>(null)
const customerEl = ref<HTMLDivElement | null>(null)
const inventoryEl = ref<HTMLDivElement | null>(null)
let trendChart: echarts.ECharts | null = null
let productChart: echarts.ECharts | null = null
let customerChart: echarts.ECharts | null = null
let inventoryChart: echarts.ECharts | null = null

const PALETTE = ['#2563eb', '#059669', '#d97706', '#7c3aed', '#dc2626', '#0891b2', '#ca8a04', '#9333ea']

function formatMoney(value: number): string {
  return `¥${Number(value || 0).toLocaleString('zh-CN', { maximumFractionDigits: 2 })}`
}

function formatKpi(kpi: KittenDashboardKpi): string {
  if (kpi.unit === '元') return formatMoney(kpi.value)
  return `${Number(kpi.value || 0).toLocaleString('zh-CN')} ${kpi.unit}`.trim()
}

function formatTime(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

function onMonthsChange(event: Event) {
  void load(Number((event.target as HTMLSelectElement).value) || 6)
}

function sliceTop(labels: string[], values: number[], top = 8) {
  if (labels.length <= top) return { labels, values }
  const headLabels = labels.slice(0, top)
  const headValues = values.slice(0, top)
  const rest = values.slice(top).reduce((sum, value) => sum + value, 0)
  return rest > 0
    ? { labels: [...headLabels, '其他'], values: [...headValues, rest] }
    : { labels: headLabels, values: headValues }
}

function buildTrendOption(): EChartsCoreOption {
  const trend = data.value?.charts.revenue_trend
  if (!trend) return {}
  return {
    color: PALETTE,
    tooltip: { trigger: 'axis' },
    legend: { top: 0, type: 'scroll' },
    grid: { left: 52, right: 52, top: 42, bottom: 46 },
    xAxis: { type: 'category', data: trend.labels, axisLabel: { rotate: trend.labels.length > 8 ? 35 : 0 } },
    yAxis: [
      { type: 'value', name: '金额（元）' },
      { type: 'value', name: '单数' },
    ],
    series: [
      { name: '营收', type: 'bar', data: trend.revenue, barMaxWidth: 26 },
      { name: '估算成本', type: 'bar', data: trend.cost, barMaxWidth: 26 },
      { name: '估算毛利', type: 'line', smooth: true, data: trend.profit, symbolSize: 6 },
      { name: '出货单', type: 'line', smooth: true, yAxisIndex: 1, data: trend.orders, symbolSize: 6 },
    ],
  }
}

function buildPieOption(labels: string[], values: number[]): EChartsCoreOption {
  const sliced = sliceTop(labels, values)
  return {
    color: PALETTE,
    tooltip: { trigger: 'item', valueFormatter: (value: unknown) => formatMoney(Number(value)) },
    legend: { top: 0, type: 'scroll' },
    series: [
      {
        type: 'pie',
        radius: ['38%', '66%'],
        top: 30,
        label: { formatter: '{b}\n{d}%' },
        data: sliced.labels.map((label, idx) => ({ name: label, value: sliced.values[idx] })),
      },
    ],
  }
}

function buildCustomerOption(): EChartsCoreOption {
  const ranking = data.value?.charts.customer_ranking
  if (!ranking) return {}
  const top = 10
  const labels = ranking.labels.slice(0, top).reverse()
  const amounts = ranking.amounts.slice(0, top).reverse()
  return {
    color: ['#2563eb'],
    tooltip: { trigger: 'axis', valueFormatter: (value: unknown) => formatMoney(Number(value)) },
    grid: { left: 90, right: 28, top: 16, bottom: 24 },
    xAxis: { type: 'value' },
    yAxis: { type: 'category', data: labels, axisLabel: { width: 80, overflow: 'truncate' } },
    series: [{ type: 'bar', data: amounts, barMaxWidth: 16, label: { show: true, position: 'right', formatter: (p: { value?: unknown }) => formatMoney(Number(p.value)) } }],
  }
}

function buildInventoryOption(labels: string[], values: number[]): EChartsCoreOption {
  return {
    color: PALETTE,
    tooltip: { trigger: 'item', valueFormatter: (value: unknown) => formatMoney(Number(value)) },
    legend: { top: 0, type: 'scroll' },
    series: [
      {
        type: 'pie',
        radius: ['42%', '68%'],
        top: 30,
        data: labels.map((label, idx) => ({ name: label, value: values[idx] })),
      },
    ],
  }
}

function renderCharts() {
  const dashboard = data.value
  if (!dashboard) return
  if (trendEl.value) {
    if (!trendChart) trendChart = echarts.init(trendEl.value)
    trendChart.setOption(buildTrendOption(), true)
    trendChart.resize()
  }
  if (productEl.value) {
    if (!productChart) productChart = echarts.init(productEl.value)
    productChart.setOption(buildPieOption(dashboard.charts.product_mix.labels, dashboard.charts.product_mix.values), true)
    productChart.resize()
  }
  if (customerEl.value) {
    if (!customerChart) customerChart = echarts.init(customerEl.value)
    customerChart.setOption(buildCustomerOption(), true)
    customerChart.resize()
  }
  if (inventoryEl.value) {
    if (!inventoryChart) inventoryChart = echarts.init(inventoryEl.value)
    inventoryChart.setOption(buildInventoryOption(dashboard.charts.inventory_mix.labels, dashboard.charts.inventory_mix.values), true)
    inventoryChart.resize()
  }
}

function onResize() {
  trendChart?.resize()
  productChart?.resize()
  customerChart?.resize()
  inventoryChart?.resize()
}

watch(data, () => nextTick(renderCharts), { deep: true })

onMounted(() => {
  void load(months.value)
  window.addEventListener('resize', onResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  ;[trendChart, productChart, customerChart, inventoryChart].forEach((chart) => chart?.dispose())
  trendChart = null
  productChart = null
  customerChart = null
  inventoryChart = null
})
</script>

<style scoped>
.fin-dashboard {
  flex: 1;
  min-height: 0;
  margin: 0 16px 16px;
  padding: 16px;
  border: 1px solid #dbeafe;
  border-radius: 14px;
  background: #f8fafc;
  overflow: auto;
}
.fin-dashboard__head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}
.fin-dashboard__title {
  font-size: 17px;
  font-weight: 800;
  color: #0f172a;
}
.fin-dashboard__subtitle {
  margin-top: 3px;
  font-size: 12px;
  color: #64748b;
}
.fin-dashboard__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.fin-select,
.fin-btn {
  border: 1px solid #cbd5e1;
  border-radius: 9px;
  background: #fff;
  color: #334155;
  font-size: 12px;
  padding: 7px 11px;
  cursor: pointer;
}
.fin-btn--primary {
  background: #2563eb;
  border-color: #2563eb;
  color: #fff;
  font-weight: 700;
}
.fin-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.fin-state {
  padding: 40px 16px;
  border-radius: 12px;
  background: #fff;
  color: #64748b;
  text-align: center;
  font-size: 13px;
}
.fin-state--error strong {
  color: #b91c1c;
}
.fin-kpis {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 10px;
  margin-bottom: 12px;
}
.fin-kpi {
  padding: 14px;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: linear-gradient(145deg, #ffffff 0%, #f1f5f9 100%);
}
.fin-kpi__label {
  font-size: 12px;
  color: #64748b;
}
.fin-kpi__value {
  margin-top: 6px;
  font-size: 21px;
  font-weight: 800;
  color: #172554;
  word-break: break-all;
}
.fin-kpi__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 5px;
  font-size: 11px;
  color: #64748b;
}
.fin-delta.is-up {
  color: #047857;
}
.fin-delta.is-down {
  color: #b91c1c;
}
.fin-charts {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 12px;
}
.fin-card {
  position: relative;
  padding: 12px;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: #fff;
}
.fin-card--wide {
  grid-column: span 2;
}
.fin-card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
  font-size: 13px;
  font-weight: 700;
  color: #1e293b;
}
.fin-card__tag {
  padding: 2px 8px;
  border-radius: 999px;
  background: #eff6ff;
  color: #1d4ed8;
  font-size: 11px;
  font-weight: 600;
}
.fin-chart {
  width: 100%;
  height: 240px;
}
.fin-chart--trend {
  height: 300px;
}
.fin-chart-empty {
  position: absolute;
  inset: 40px 12px 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 10px;
  background: rgba(248, 250, 252, 0.92);
  color: #94a3b8;
  font-size: 12px;
}
.fin-tables {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 12px;
}
.fin-notes {
  margin: 12px 0 0;
  padding-left: 18px;
  color: #64748b;
  font-size: 12px;
  line-height: 1.7;
}
@media (max-width: 900px) {
  .fin-charts {
    grid-template-columns: minmax(0, 1fr);
  }
  .fin-card--wide {
    grid-column: span 1;
  }
}
</style>
