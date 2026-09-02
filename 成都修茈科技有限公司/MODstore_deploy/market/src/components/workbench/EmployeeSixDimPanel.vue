<script setup lang="ts">
import { computed } from 'vue'
import type { SixDimensionReport } from '../../types/sixDimension'

/** 与 modstore_server/employee_six_dimension.SIX_DIMENSION_KEYS 顺序一致 */
const DIM_ORDER = [
  'requirement_clarity',
  'pack_compliance',
  'code_robustness',
  'executability',
  'workflow_connectivity',
  'domain_delivery',
] as const

const GRADE_BADGE_CLASS: Record<string, string> = {
  S: 'wb-six-dim-grade--s',
  A: 'wb-six-dim-grade--a',
  B: 'wb-six-dim-grade--b',
  P: 'wb-six-dim-grade--p',
  C: 'wb-six-dim-grade--c',
  D: 'wb-six-dim-grade--d',
  F: 'wb-six-dim-grade--f',
  G: 'wb-six-dim-grade--g',
}

function gradeBadgeClass(code: string | undefined): string {
  const c = String(code || 'G')
    .trim()
    .toUpperCase()
  return GRADE_BADGE_CLASS[c] || 'wb-six-dim-grade--g'
}

const props = withDefaults(
  defineProps<{
    report: SixDimensionReport | null
    loading?: boolean
    error?: string
    compact?: boolean
    title?: string
    showGradeScale?: boolean
  }>(),
  {
    loading: false,
    error: '',
    compact: false,
    title: '六维质量评估',
    showGradeScale: true,
  },
)

const chartGeom = computed(() =>
  props.compact ? { cx: 200, cy: 200, rMax: 100, labelRadius: 0 } : { cx: 200, cy: 200, rMax: 118, labelRadius: 36 },
)

const CX = computed(() => chartGeom.value.cx)
const CY = computed(() => chartGeom.value.cy)
const R_MAX = computed(() => chartGeom.value.rMax)
const LABEL_RADIUS = computed(() => chartGeom.value.labelRadius)

function polar(angleDeg: number, radius: number, cx: number, cy: number): { x: number; y: number } {
  const rad = ((angleDeg - 90) * Math.PI) / 180
  return {
    x: cx + radius * Math.cos(rad),
    y: cy + radius * Math.sin(rad),
  }
}

const scores = computed(() => {
  const dims = props.report?.dimensions || {}
  const cx = CX.value
  const cy = CY.value
  const rMax = R_MAX.value
  const labelR = LABEL_RADIUS.value
  return DIM_ORDER.map((key, i) => {
    const entry = dims[key]
    const score = Math.max(0, Math.min(100, Number(entry?.score ?? 0)))
    const angle = i * 60
    const onChart = polar(angle, (score / 100) * rMax, cx, cy)
    const onRing = polar(angle, rMax, cx, cy)
    const labelPt = labelR > 0 ? polar(angle, rMax + labelR, cx, cy) : { x: 0, y: 0 }
    return {
      key,
      score,
      label: entry?.label || key,
      grade: entry?.grade || '',
      gradeLabel: entry?.grade_label || '',
      description: entry?.description || '',
      reasons: Array.isArray(entry?.reasons) ? entry.reasons : [],
      onChart,
      onRing,
      labelPt,
    }
  })
})

const dataPolygon = computed(() => scores.value.map((s) => `${s.onChart.x.toFixed(1)},${s.onChart.y.toFixed(1)}`).join(' '))

const gridPolygons = computed(() => {
  const cx = CX.value
  const cy = CY.value
  const rMax = R_MAX.value
  const levels = [0.25, 0.5, 0.75, 1]
  return levels.map((lv) =>
    DIM_ORDER.map((_, i) => {
      const p = polar(i * 60, rMax * lv, cx, cy)
      return `${p.x.toFixed(1)},${p.y.toFixed(1)}`
    }).join(' '),
  )
})

const showChartLabels = computed(() => !props.compact)
const showPanelTitle = computed(() => Boolean(props.title?.trim()))

const overall = computed(() => Number(props.report?.overall_score ?? 0))
const passed = computed(() => Boolean(props.report?.passed))
const overallGrade = computed(() =>
  String(props.report?.overall_grade || '')
    .trim()
    .toUpperCase(),
)
const overallGradeLabel = computed(() => String(props.report?.overall_grade_label || '').trim())
const gradeScale = computed(() => props.report?.grade_scale || null)
const hasReport = computed(() => Boolean(props.report?.dimensions))
</script>

<template>
  <div class="wb-six-dim-panel" :class="{ 'wb-six-dim-panel--compact': compact }">
    <div v-if="loading" class="wb-six-dim-panel-state">正在计算六维评估…</div>
    <div v-else-if="error" class="wb-six-dim-panel-state wb-six-dim-panel-state--err">
      {{ error }}
    </div>
    <template v-else-if="hasReport">
      <header class="wb-six-dim-panel-head">
        <div v-if="overallGrade" class="wb-six-dim-grade-badge" :class="gradeBadgeClass(overallGrade)" :title="overallGradeLabel">
          <span class="wb-six-dim-grade-code">{{ overallGrade }}</span>
          <span class="wb-six-dim-grade-tier">级</span>
        </div>
        <div>
          <h3 v-if="showPanelTitle" class="wb-six-dim-panel-title">{{ title }}</h3>
          <p class="wb-six-dim-sub" :class="{ 'wb-six-dim-sub--solo': !showPanelTitle }">
            综合
            <strong :class="{ 'wb-six-dim-pass': passed, 'wb-six-dim-fail': !passed }">
              {{ overall.toFixed(1) }}
            </strong>
            分
            <span v-if="overallGradeLabel" class="wb-six-dim-grade-caption">{{ overallGradeLabel }}</span>
            <span v-if="report?.pipeline_label" class="wb-six-dim-pipe">（{{ report.pipeline_label }}）</span>
          </p>
        </div>
      </header>

      <div class="wb-six-dim-body">
        <div class="wb-six-dim-chart-wrap">
          <svg class="wb-six-dim-chart" viewBox="0 0 400 400" aria-hidden="true">
            <polygon v-for="(pts, gi) in gridPolygons" :key="gi" :points="pts" class="wb-six-dim-grid" />
            <g v-for="s in scores" :key="s.key">
              <line :x1="CX" :y1="CY" :x2="s.onRing.x" :y2="s.onRing.y" class="wb-six-dim-axis" />
              <circle :cx="s.onChart.x" :cy="s.onChart.y" r="4" class="wb-six-dim-vertex" />
              <template v-if="showChartLabels">
                <text :x="s.labelPt.x" :y="s.labelPt.y" class="wb-six-dim-label" text-anchor="middle" dominant-baseline="middle">
                  {{ s.label }}
                </text>
                <text :x="s.labelPt.x" :y="s.labelPt.y + 14" class="wb-six-dim-score" text-anchor="middle" dominant-baseline="middle">
                  {{ s.grade || s.score }}
                </text>
              </template>
            </g>
            <polygon :points="dataPolygon" class="wb-six-dim-fill" />
            <polygon :points="dataPolygon" class="wb-six-dim-stroke" />
          </svg>
        </div>

        <ul v-if="compact" class="wb-six-dim-chips" aria-label="六维等级">
          <li v-for="s in scores" :key="'chip-' + s.key" class="wb-six-dim-chip" :class="{ 'wb-six-dim-chip--low': s.score < 50 }">
            <span class="wb-six-dim-chip-label">{{ s.label }}</span>
            <span class="wb-six-dim-chip-grade" :class="gradeBadgeClass(s.grade)">{{ s.grade || '-' }}</span>
            <span class="wb-six-dim-chip-score">{{ s.score }}</span>
          </li>
        </ul>

        <ul class="wb-six-dim-list" :class="{ 'wb-six-dim-list--compact': compact }">
          <li v-for="s in scores" :key="s.key" class="wb-six-dim-item" :class="{ 'wb-six-dim-item--low': s.score < 50 }">
            <div class="wb-six-dim-item-head">
              <span class="wb-six-dim-item-label">{{ s.label }}</span>
              <span class="wb-six-dim-item-meta">
                <span v-if="s.grade" class="wb-six-dim-item-grade" :class="gradeBadgeClass(s.grade)">{{ s.grade }}级</span>
                <span class="wb-six-dim-item-score">{{ s.score }} 分</span>
              </span>
            </div>
            <p v-if="!compact && s.description" class="wb-six-dim-item-desc">{{ s.description }}</p>
            <ul v-if="!compact && s.reasons.length" class="wb-six-dim-reasons">
              <li v-for="(r, ri) in s.reasons" :key="ri">{{ r }}</li>
            </ul>
          </li>
        </ul>
      </div>

      <footer v-if="!compact || !passed" class="wb-six-dim-panel-foot">
        <p v-if="!passed" class="wb-six-dim-warn">未达通过线（综合 ≥70、各维 ≥50、关键维 ≥60）。</p>
        <p v-else-if="!compact" class="wb-six-dim-ok">六维评估达标。</p>
        <details v-if="!compact && showGradeScale && gradeScale" class="wb-six-dim-scale">
          <summary>等级说明</summary>
          <ul>
            <li v-for="(desc, code) in gradeScale" :key="code">
              <strong>{{ code }}</strong
              >：{{ desc }}
            </li>
          </ul>
        </details>
      </footer>
    </template>
    <div v-else class="wb-six-dim-panel-state">暂无评估数据</div>
  </div>
</template>

<!-- 拆分后本文件为组装入口（façade）：样式外移至 ./EmployeeSixDimPanel.css，模板与逻辑保持原样。 -->
<style scoped src="./EmployeeSixDimPanel.css"></style>
