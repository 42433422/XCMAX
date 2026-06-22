<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRouter, type RouteLocationRaw } from 'vue-router'
import {
  DEPARTMENT_COLORS,
  DEPARTMENT_ORDER,
  SIX_LINE_DEPARTMENTS,
} from '@/domain/yuangonDutyRoster'
import { useDutyRoster } from '@/composables/useDutyRoster'
import { useDutyRosterLoopStatus } from '@/composables/useDutyRosterLoopStatus'

type EmployeeFlowPlacement = {
  deptId: string
  deptLabel: string
  subzoneLabel: string
  color: string
}

const props = withDefaults(defineProps<{
  surface?: 'employee-space' | 'workflow-visualization'
  compact?: boolean
}>(), {
  surface: 'workflow-visualization',
  compact: false,
})

const router = useRouter()
// SSOT 派生：运行时从后端 /api/system/duty-roster 获取编制矩阵
const { allPlannedIds, employeeLabels, employeeDescriptions, ensureLoaded } = useDutyRoster()
const { status, loading, ready, healthLabel, detailLine, refresh } = useDutyRosterLoopStatus({
  autoRefreshMs: 30000,
})

onMounted(() => {
  // 触发 SSOT 派生数据加载（失败时 composable 自动回退到构建时硬编码常量）
  ensureLoaded()
})

function routeTarget(name: string, path: string): RouteLocationRaw {
  if (!router.hasRoute(name)) {
    return { path }
  }
  if (name === 'duty-roster-graph') {
    return { name, query: { view: 'department' } }
  }
  return { name }
}

const loopNodes = computed(() => [
  {
    key: 'duty',
    title: '编制图谱',
    meta: `${status.value.plannedCount} 岗`,
    text: '主索引，只认编制内员工包与本机安装状态。',
    to: routeTarget('duty-roster-graph', '/duty-roster-graph'),
  },
  {
    key: 'space',
    title: '员工空间',
    meta: props.surface === 'employee-space' ? '当前' : '观测',
    text: '把编制员工映射成前端工位、空态、托管和任务快照。',
    to: routeTarget('workflow-employee-space', '/workflow-employee-space'),
  },
  {
    key: 'flow',
    title: '流程可视化',
    meta: props.surface === 'workflow-visualization' ? '当前' : '链路',
    text: '按部门与阶段可视化编制员工如何进入协作、派发与回写。',
    to: routeTarget('workflow-visualization', '/workflow-visualization'),
  },
  {
    key: 'runtime',
    title: '执行回写',
    meta: ready.value ? '可运行' : '待对齐',
    text: '后端执行、调度、审计结果回到图谱和员工空间。',
    to: routeTarget('duty-roster-graph', '/duty-roster-graph'),
  },
])

const departments = computed(() =>
  DEPARTMENT_ORDER.map((id) => {
    const dept = SIX_LINE_DEPARTMENTS[id]
    const ids = Object.values(dept.subzones).flatMap((z) => z.ids)
    const uniqueIds = [...new Set(ids)]
    const missingLocal = uniqueIds.filter((eid) => status.value.missingLocalIds.includes(eid)).length
    const missingCatalog = uniqueIds.filter((eid) => status.value.missingCatalogIds.includes(eid)).length
    return {
      id,
      label: dept.label,
      count: uniqueIds.length,
      subzoneCount: Object.keys(dept.subzones).length,
      missingLocal,
      missingCatalog,
      color: DEPARTMENT_COLORS[id] || '#2563eb',
    }
  }),
)

const employeeCards = computed(() => {
  const assignments = new Map<string, EmployeeFlowPlacement[]>()
  const orderedIds: string[] = []

  for (const deptId of DEPARTMENT_ORDER) {
    const dept = SIX_LINE_DEPARTMENTS[deptId]
    const color = DEPARTMENT_COLORS[deptId] || '#2563eb'
    for (const subzone of Object.values(dept.subzones)) {
      for (const employeeId of subzone.ids) {
        if (!assignments.has(employeeId)) {
          assignments.set(employeeId, [])
          orderedIds.push(employeeId)
        }
        const rows = assignments.get(employeeId) || []
        if (!rows.some((row) => row.deptId === deptId && row.subzoneLabel === subzone.label)) {
          rows.push({
            deptId,
            deptLabel: dept.label,
            subzoneLabel: subzone.label,
            color,
          })
        }
        assignments.set(employeeId, rows)
      }
    }
  }

  for (const employeeId of allPlannedIds.value) {
    if (!assignments.has(employeeId)) {
      assignments.set(employeeId, [])
      orderedIds.push(employeeId)
    }
  }

  return orderedIds.map((employeeId, index) => {
    const flows = assignments.get(employeeId) || []
    const primary = flows[0]
    const missingLocal = status.value.missingLocalIds.includes(employeeId)
    const missingCatalog = status.value.missingCatalogIds.includes(employeeId)
    const statusLabel = missingLocal
      ? '本机缺包'
      : missingCatalog
        ? 'Catalog 缺岗'
        : '已对齐'

    return {
      id: employeeId,
      index: index + 1,
      name: employeeLabels.value[employeeId] || employeeId,
      description: employeeDescriptions.value[employeeId] || '等待补充员工职责说明。',
      primaryDeptLabel: primary?.deptLabel || '未分配部门',
      primarySubzoneLabel: primary?.subzoneLabel || '未分配流程节点',
      color: primary?.color || '#2563eb',
      flows,
      statusLabel,
      statusKind: missingLocal || missingCatalog ? 'warn' : 'ok',
    }
  })
})

const healthCards = computed(() => [
  { label: '编制员工', value: status.value.plannedCount, sub: '编制主索引' },
  { label: '本机安装', value: `${status.value.localInstalledCount}/${status.value.plannedCount}`, sub: 'mods/_employees' },
  { label: 'Catalog', value: `${status.value.catalogRegisteredCount}/${status.value.plannedCount}`, sub: '员工包登记' },
  { label: '缺口', value: status.value.missingLocalCount + status.value.missingCatalogCount, sub: '本机 + Catalog' },
])

const riskLine = computed(() => {
  if (ready.value) return '编制、本机员工包与 Catalog 已对齐，前端可直接观察闭环。'
  const parts = []
  if (status.value.missingLocalCount) parts.push(`本机缺包 ${status.value.missingLocalCount}`)
  if (status.value.missingCatalogCount) parts.push(`Catalog 缺岗 ${status.value.missingCatalogCount}`)
  if (status.value.extraCount) parts.push(`编制外 ${status.value.extraCount}`)
  return parts.join('，') || '等待编制健康状态刷新'
})
</script>

<template>
  <section class="drlv" :class="{ 'drlv--compact': compact }" aria-labelledby="drlv-title">
    <div class="drlv-head">
      <div>
        <p class="drlv-kicker">编制驱动流程</p>
        <h3 id="drlv-title" class="drlv-title">编制 → 员工空间 → 流程可视化 → 执行回写</h3>
        <p class="drlv-desc">{{ detailLine }}</p>
      </div>
      <button type="button" class="drlv-refresh" :disabled="loading" @click="refresh">
        {{ loading ? '刷新中' : '刷新' }}
      </button>
    </div>

    <div class="drlv-health" role="list" aria-label="编制闭环实时指标">
      <div v-for="card in healthCards" :key="card.label" class="drlv-health-card" role="listitem">
        <span class="drlv-health-label">{{ card.label }}</span>
        <strong class="drlv-health-value">{{ card.value }}</strong>
        <span class="drlv-health-sub">{{ card.sub }}</span>
      </div>
    </div>

    <div class="drlv-loop" role="list" aria-label="编制员工闭环">
      <router-link
        v-for="node in loopNodes"
        :key="node.key"
        :to="node.to"
        class="drlv-node"
        role="listitem"
      >
        <span class="drlv-node-title">{{ node.title }}</span>
        <strong class="drlv-node-meta">{{ node.meta }}</strong>
        <span class="drlv-node-text">{{ node.text }}</span>
      </router-link>
    </div>

    <div class="drlv-status" :class="ready ? 'drlv-status--ok' : 'drlv-status--warn'">
      <span class="drlv-status-dot" aria-hidden="true" />
      <strong>{{ healthLabel }}</strong>
      <span>{{ riskLine }}</span>
    </div>

    <div class="drlv-depts" role="list" aria-label="六部门编制流转">
      <div
        v-for="dept in departments"
        :key="dept.id"
        class="drlv-dept"
        role="listitem"
        :style="{ '--dept-color': dept.color }"
      >
        <div class="drlv-dept-head">
          <strong>{{ dept.label }}</strong>
          <span>{{ dept.count }} 员工</span>
        </div>
        <div class="drlv-dept-meter">
          <span />
        </div>
        <p class="drlv-dept-sub">
          {{ dept.subzoneCount }} 个子区
          <template v-if="dept.missingLocal || dept.missingCatalog">
            · 缺口 {{ dept.missingLocal + dept.missingCatalog }}
          </template>
          <template v-else>
            · 已对齐
          </template>
        </p>
      </div>
    </div>

    <section
      v-if="!compact && surface === 'workflow-visualization'"
      class="drlv-employees"
      aria-labelledby="drlv-employees-title"
    >
      <div class="drlv-employees-head">
        <div>
          <p class="drlv-kicker">员工说明</p>
          <h4 id="drlv-employees-title" class="drlv-employees-title">
            52 个编制员工如何进入流程
          </h4>
          <p class="drlv-employees-sub">
            每张卡对应一个本机员工包 manifest 的岗位说明，并标出它参与的六部门流程节点。
          </p>
        </div>
        <strong class="drlv-employees-count">{{ employeeCards.length }} 员工</strong>
      </div>

      <div class="drlv-employee-grid" role="list" aria-label="编制员工职责说明">
        <article
          v-for="employee in employeeCards"
          :key="employee.id"
          class="drlv-employee"
          role="listitem"
          :style="{ '--dept-color': employee.color }"
        >
          <div class="drlv-employee-top">
            <span class="drlv-employee-index">#{{ employee.index }}</span>
            <span
              class="drlv-employee-status"
              :class="'drlv-employee-status--' + employee.statusKind"
            >
              {{ employee.statusLabel }}
            </span>
          </div>
          <h5 class="drlv-employee-name">{{ employee.name }}</h5>
          <code class="drlv-employee-id">{{ employee.id }}</code>
          <p class="drlv-employee-desc">{{ employee.description }}</p>
          <div class="drlv-employee-primary">
            <span>{{ employee.primaryDeptLabel }}</span>
            <strong>{{ employee.primarySubzoneLabel }}</strong>
          </div>
          <div class="drlv-employee-flows" aria-label="参与流程节点">
            <span
              v-for="flow in employee.flows"
              :key="flow.deptId + flow.subzoneLabel"
              class="drlv-employee-flow"
            >
              {{ flow.subzoneLabel }}
            </span>
          </div>
        </article>
      </div>
    </section>
  </section>
</template>

<style scoped>
.drlv {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 16px;
  border: 1px solid #dbe3ef;
  border-radius: 12px;
  background: #fff;
}

.drlv-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.drlv-kicker {
  margin: 0 0 4px;
  color: #2563eb;
  font-size: 12px;
  font-weight: 800;
}

.drlv-title {
  margin: 0 0 6px;
  color: #0f172a;
  font-size: 17px;
  font-weight: 800;
}

.drlv-desc {
  margin: 0;
  color: #64748b;
  font-size: 13px;
  line-height: 1.5;
}

.drlv-refresh {
  border: 1px solid #bfdbfe;
  border-radius: 8px;
  background: #eff6ff;
  color: #1d4ed8;
  font-size: 12px;
  font-weight: 800;
  padding: 8px 10px;
  cursor: pointer;
}

.drlv-health,
.drlv-loop,
.drlv-depts {
  display: grid;
  gap: 10px;
}

.drlv-health {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.drlv-health-card,
.drlv-node,
.drlv-dept {
  min-width: 0;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: #f8fafc;
  padding: 11px 12px;
}

.drlv-health-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.drlv-health-label,
.drlv-health-sub,
.drlv-node-text,
.drlv-dept-sub {
  color: #64748b;
  font-size: 12px;
  line-height: 1.35;
}

.drlv-health-value {
  color: #0f172a;
  font-size: 18px;
  line-height: 1;
}

.drlv-loop {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.drlv-node {
  display: flex;
  flex-direction: column;
  gap: 6px;
  color: inherit;
  text-decoration: none;
  border-color: #cbd5e1;
  background: #fff;
}

.drlv-node:hover {
  border-color: #93c5fd;
  background: #eff6ff;
}

.drlv-node-title {
  color: #1e293b;
  font-size: 13px;
  font-weight: 800;
}

.drlv-node-meta {
  color: #1d4ed8;
  font-size: 16px;
  line-height: 1;
}

.drlv-status {
  display: flex;
  align-items: center;
  gap: 8px;
  border-radius: 10px;
  padding: 10px 12px;
  font-size: 13px;
  line-height: 1.4;
}

.drlv-status--ok {
  border: 1px solid #bbf7d0;
  background: #f0fdf4;
  color: #166534;
}

.drlv-status--warn {
  border: 1px solid #fed7aa;
  background: #fff7ed;
  color: #9a3412;
}

.drlv-status-dot {
  flex: 0 0 auto;
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: currentColor;
}

.drlv-depts {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.drlv-dept {
  background: #fff;
  border-top: 3px solid var(--dept-color);
}

.drlv-dept-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
  color: #0f172a;
  font-size: 13px;
}

.drlv-dept-head span {
  flex: 0 0 auto;
  color: #64748b;
  font-size: 12px;
  font-weight: 700;
}

.drlv-dept-meter {
  margin: 9px 0 7px;
  height: 6px;
  overflow: hidden;
  border-radius: 999px;
  background: #e2e8f0;
}

.drlv-dept-meter span {
  display: block;
  width: 100%;
  height: 100%;
  border-radius: inherit;
  background: var(--dept-color);
}

.drlv-dept-sub {
  margin: 0;
}

.drlv-employees {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding-top: 2px;
}

.drlv-employees-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.drlv-employees-title {
  margin: 0 0 6px;
  color: #0f172a;
  font-size: 16px;
  font-weight: 800;
}

.drlv-employees-sub {
  margin: 0;
  color: #64748b;
  font-size: 13px;
  line-height: 1.5;
}

.drlv-employees-count {
  flex: 0 0 auto;
  border: 1px solid #bfdbfe;
  border-radius: 8px;
  background: #eff6ff;
  color: #1d4ed8;
  font-size: 12px;
  line-height: 1;
  padding: 8px 10px;
}

.drlv-employee-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.drlv-employee {
  min-width: 0;
  border: 1px solid #e2e8f0;
  border-left: 4px solid var(--dept-color);
  border-radius: 10px;
  background: #fff;
  padding: 12px;
}

.drlv-employee-top,
.drlv-employee-primary,
.drlv-employee-flows {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.drlv-employee-top {
  justify-content: space-between;
  margin-bottom: 8px;
}

.drlv-employee-index {
  color: #64748b;
  font-size: 11px;
  font-weight: 800;
}

.drlv-employee-status {
  border-radius: 999px;
  font-size: 11px;
  font-weight: 800;
  line-height: 1;
  padding: 5px 7px;
}

.drlv-employee-status--ok {
  background: #dcfce7;
  color: #166534;
}

.drlv-employee-status--warn {
  background: #ffedd5;
  color: #9a3412;
}

.drlv-employee-name {
  margin: 0 0 4px;
  color: #0f172a;
  font-size: 14px;
  font-weight: 800;
  line-height: 1.25;
}

.drlv-employee-id {
  display: block;
  margin-bottom: 9px;
  color: #64748b;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 11px;
  white-space: normal;
  overflow-wrap: anywhere;
}

.drlv-employee-desc {
  margin: 0 0 10px;
  color: #334155;
  font-size: 12px;
  line-height: 1.55;
}

.drlv-employee-primary {
  margin-bottom: 8px;
  color: #475569;
  font-size: 12px;
}

.drlv-employee-primary strong {
  color: #0f172a;
}

.drlv-employee-flow {
  border: 1px solid #e2e8f0;
  border-radius: 999px;
  background: #f8fafc;
  color: #475569;
  font-size: 11px;
  font-weight: 700;
  line-height: 1;
  padding: 5px 7px;
}

@media (max-width: 900px) {
  .drlv-health,
  .drlv-loop,
  .drlv-depts,
  .drlv-employee-grid {
    grid-template-columns: 1fr 1fr;
  }
}

@media (max-width: 640px) {
  .drlv-health,
  .drlv-loop,
  .drlv-depts,
  .drlv-employee-grid {
    grid-template-columns: 1fr;
  }
}
</style>
