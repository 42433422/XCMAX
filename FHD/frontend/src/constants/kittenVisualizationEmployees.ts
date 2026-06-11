import type { KittenChartType } from '@/composables/useKittenAnalyzer'

/** 小猫分析 · 可视化 AI 员工（办公员工附属包2） */
export interface KittenVizEmployeeDef {
  pkgId: string
  name: string
  icon: string
  chartType: KittenChartType
  description: string
  /** ECharts 主题色 */
  palette: string[]
  /** 综合看板员工：一次生成多图 */
  dashboard?: boolean
}

export const KITTEN_VIZ_EMPLOYEES: KittenVizEmployeeDef[] = [
  {
    pkgId: 'chart-bar-employee',
    name: '柱状图可视化员',
    icon: '📊',
    chartType: 'bar',
    description: '对比分类指标，突出排名与差异',
    palette: ['#2563eb', '#60a5fa', '#93c5fd', '#1d4ed8'],
  },
  {
    pkgId: 'chart-line-employee',
    name: '趋势折线可视化员',
    icon: '📈',
    chartType: 'line',
    description: '时间序列与走势分析，发现拐点',
    palette: ['#059669', '#34d399', '#6ee7b7', '#047857'],
  },
  {
    pkgId: 'chart-pie-employee',
    name: '占比饼图可视化员',
    icon: '🥧',
    chartType: 'pie',
    description: '结构占比与分布，一图看清构成',
    palette: ['#d97706', '#fbbf24', '#fcd34d', '#b45309'],
  },
  {
    pkgId: 'chart-dashboard-employee',
    name: '综合看板可视化员',
    icon: '🎛️',
    chartType: 'bar',
    dashboard: true,
    description: '多图联动看板，KPI + 趋势 + 占比一屏呈现',
    palette: ['#7c3aed', '#a78bfa', '#c4b5fd', '#5b21b6'],
  },
]

export const KITTEN_VIZ_EMPLOYEE_PKG_IDS = KITTEN_VIZ_EMPLOYEES.map((e) => e.pkgId)

export function findKittenVizEmployee(pkgId?: string | null): KittenVizEmployeeDef | undefined {
  const id = (pkgId || '').trim()
  return KITTEN_VIZ_EMPLOYEES.find((e) => e.pkgId === id)
}
