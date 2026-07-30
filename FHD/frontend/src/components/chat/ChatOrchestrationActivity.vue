<template>
  <section
    class="orchestration-activity"
    data-testid="chat-orchestration-activity"
    aria-label="智能编排执行记录"
  >
    <button
      class="orchestration-activity__header"
      type="button"
      :aria-expanded="expanded"
      @click="expanded = !expanded"
    >
      <span class="orchestration-activity__chevron" aria-hidden="true">{{ expanded ? '⌄' : '›' }}</span>
      <span class="orchestration-activity__title">智能编排执行记录</span>
      <span v-if="changeSummary" class="orchestration-activity__changes">{{ changeSummary }}</span>
      <span class="orchestration-activity__progress">{{ progressLabel }}</span>
    </button>

    <div v-if="expanded" class="orchestration-activity__list" role="list">
      <article
        v-for="step in steps"
        :key="step.id"
        class="orchestration-step"
        :class="[`orchestration-step--${step.evidence.kind}`, `orchestration-step--${step.status}`]"
        data-testid="orchestration-activity-step"
        :data-kind="step.evidence.kind"
        :data-status="step.status"
        role="listitem"
      >
        <span class="orchestration-step__icon" aria-hidden="true">{{ kindIcon(step.evidence.kind) }}</span>
        <div class="orchestration-step__body">
          <div class="orchestration-step__title-row">
            <span class="orchestration-step__title">{{ stepTitle(step) }}</span>
            <span class="orchestration-step__status">{{ statusLabel(step.status) }}</span>
          </div>
          <div
            v-for="(detail, detailIndex) in stepDetails(step)"
            :key="`${step.id}-${detailIndex}`"
            class="orchestration-step__detail"
          >
            {{ detail }}
          </div>
        </div>
      </article>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type {
  OrchestrationChange,
  OrchestrationDatabase,
  OrchestrationEvidence,
  OrchestrationEvidenceKind,
  OrchestrationTraceStep,
} from '@/types/orchestration'

const props = defineProps<{
  steps: OrchestrationTraceStep[]
}>()

const expanded = ref(false)

const finishedCount = computed(() => props.steps.filter((step) =>
  ['completed', 'success', 'failed'].includes(String(step.status || '').toLowerCase()),
).length)

const progressLabel = computed(() => {
  if (!props.steps.length) return '等待执行'
  if (finishedCount.value >= props.steps.length) return `已处理 ${props.steps.length} 个编排步骤`
  return `第 ${Math.min(finishedCount.value + 1, props.steps.length)} / ${props.steps.length} 步`
})

const changeSummary = computed(() => {
  const stats = { created: 0, updated: 0, deleted: 0 }
  for (const step of props.steps) {
    for (const change of step.evidence.changes || []) {
      stats.created += Number(change.counts?.created || 0)
      stats.updated += Number(change.counts?.updated || 0)
      stats.deleted += Number(change.counts?.deleted || 0)
    }
  }
  const parts = [
    stats.created ? `+${stats.created}` : '',
    stats.updated ? `~${stats.updated}` : '',
    stats.deleted ? `−${stats.deleted}` : '',
  ].filter(Boolean)
  return parts.length ? `产品变更 ${parts.join(' ')}` : ''
})

function kindIcon(kind: OrchestrationEvidenceKind): string {
  return {
    employee: '员',
    print: '单',
    database_write: '改',
    database_read: '读',
    tool: '行',
  }[kind] || '行'
}

function statusLabel(status: string): string {
  const normalized = String(status || '').toLowerCase()
  if (normalized === 'running' || normalized === 'started') return '执行中'
  if (normalized === 'failed' || normalized === 'error') return '失败'
  if (normalized === 'inconclusive') return '待核验'
  if (normalized === 'verified') return '已核验'
  if (normalized === 'completed' || normalized === 'success') return '已完成'
  return '已记录'
}

function databaseLabel(database: OrchestrationDatabase): string {
  const name = String(database.database_name || database.database_id || '业务数据库').trim()
  const runtime = String(database.runtime_database || '').trim()
  return runtime && runtime !== name ? `${name}（${runtime}）` : name
}

function tablesLabel(database: OrchestrationDatabase): string {
  const tables = String(database.tables || '').trim()
  return tables ? `表：${tables}` : ''
}

function changeCountLabel(change: OrchestrationChange): string {
  const counts = change.counts || {}
  const labels = [
    ['created', '新增'],
    ['updated', '修改'],
    ['deleted', '删除'],
  ] as const
  const parts = labels
    .filter(([key]) => Number(counts[key] || 0) > 0)
    .map(([key, label]) => `${label} ${Number(counts[key] || 0)}`)
  return parts.join(' · ') || String(change.label || '已写入')
}

function itemLabel(item: Record<string, unknown>): string {
  const name = String(
    item.model_number || item.product_code || item.product_name || item.name || item.id || '',
  ).trim()
  const quantity = item.qty ?? item.quantity
  if (!name) return quantity == null ? '' : `数量 ${String(quantity)}`
  return quantity == null ? name : `${name} · 数量 ${String(quantity)}`
}

function itemChangePrefix(item: Record<string, unknown>, change: OrchestrationChange): string {
  const kind = String(item.change_type || '').toLowerCase()
  if (kind === 'added' || change.operation === 'create') return '+ 新增'
  if (kind === 'deleted' || change.operation === 'delete') return '− 删除'
  if (kind === 'updated' || change.operation === 'update') return '~ 修改'
  return '↔ 变更'
}

function stepTitle(step: OrchestrationTraceStep): string {
  const evidence = step.evidence
  if (evidence.kind === 'employee') {
    const employee = evidence.employees[0]
    return `已调用 AI 员工：${employee?.employee_name || employee?.employee_id || '未命名员工'}`
  }
  if (evidence.kind === 'print') {
    const printKind = evidence.print?.kind === 'document' ? '文档' : '标签'
    return `已执行${printKind}打单`
  }
  if (evidence.kind === 'database_write') {
    const change = evidence.changes[0]
    const database = evidence.databases[0]
    return `已更改 ${databaseLabel(database || {})}：${changeCountLabel(change || {})}`
  }
  if (evidence.kind === 'database_read') {
    const database = evidence.databases[0]
    const count = evidence.result_count == null ? '' : ` · ${evidence.result_count} 条`
    return `已读取 ${databaseLabel(database || {})}${count}`
  }
  return evidence.label || `${evidence.tool_id || '工具'} 已执行`
}

function stepDetails(step: OrchestrationTraceStep): string[] {
  const evidence = step.evidence
  const details: string[] = []
  if (step.verification?.reason) {
    details.push(`验收：${step.verification.reason}`)
  }
  if (step.verification?.recovery_hint) {
    details.push(`下一步：${step.verification.recovery_hint}`)
  }
  if (evidence.kind === 'employee') {
    const employee = evidence.employees[0]
    if (employee?.task) details.push(`任务：${employee.task}`)
    if (evidence.action) details.push(`能力：${evidence.tool_id || 'employee'}.${evidence.action}`)
    return details
  }

  if (evidence.kind === 'database_read') {
    for (const database of evidence.databases) {
      details.push([databaseLabel(database), tablesLabel(database)].filter(Boolean).join(' · '))
    }
    if (evidence.query) details.push(`查询：${evidence.query}`)
    return details
  }

  if (evidence.kind === 'database_write') {
    for (const change of evidence.changes) {
      const changeText = [
        `${change.database_name || change.database_id || '业务数据库'} · ${changeCountLabel(change)}`,
      ].filter(Boolean).join(' · ')
      if (changeText) details.push(changeText)
      for (const item of (change.items || []).slice(0, 8)) {
        const label = itemLabel(item)
        if (label) details.push(`${itemChangePrefix(item, change)}：${label}`)
      }
      for (const field of (change.field_changes || []).slice(0, 8)) {
        const fieldName = String(field.field || '').trim()
        if (!fieldName) continue
        details.push(`~ ${fieldName}：${field.before || '空'} → ${field.after || '空'}`)
      }
    }
    return details
  }

  if (evidence.kind === 'print') {
    for (const database of evidence.databases) {
      details.push(`读取：${databaseLabel(database)}${tablesLabel(database) ? ` · ${tablesLabel(database)}` : ''}`)
    }
    const print = evidence.print
    if (print?.printer_name) details.push(`打印机：${print.printer_name}`)
    if (print?.copies != null) details.push(`份数：${print.copies}`)
    if (print?.template) details.push(`模板：${print.template}`)
    if (evidence.tool_id || evidence.action) details.push(`调用：${evidence.tool_id || 'print'}.${evidence.action || 'execute'}`)
    return details
  }

  if (evidence.tool_id || evidence.action) details.push(`调用：${evidence.tool_id || 'tool'}.${evidence.action || 'execute'}`)
  return details
}
</script>

<style scoped>
.orchestration-activity {
  margin-top: 13px;
  border-top: 1px solid color-mix(in srgb, var(--xc-color-border, #d9dee8) 72%, transparent);
  padding-top: 8px;
  color: var(--xc-color-text-secondary, #667085);
}

.orchestration-activity__header {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 3px 0;
  border: 0;
  background: transparent;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.orchestration-activity__chevron {
  width: 16px;
  color: var(--xc-color-primary, #3867d6);
  font-size: 17px;
  line-height: 1;
}

.orchestration-activity__title {
  color: var(--xc-color-text, #344054);
  font-size: 12px;
  font-weight: 650;
}

.orchestration-activity__progress {
  margin-left: auto;
  border: 1px solid color-mix(in srgb, var(--xc-color-primary, #3867d6) 22%, transparent);
  border-radius: 999px;
  padding: 2px 8px;
  color: var(--xc-color-primary, #3867d6);
  font-size: 11px;
  white-space: nowrap;
}

.orchestration-activity__changes {
  color: var(--xc-color-text-tertiary, #98a2b3);
  font-size: 11px;
  white-space: nowrap;
}

.orchestration-activity__list {
  display: grid;
  gap: 2px;
  margin: 6px 0 1px 3px;
  padding-left: 4px;
  border-left: 1px solid color-mix(in srgb, var(--xc-color-border, #d9dee8) 80%, transparent);
}

.orchestration-step {
  display: flex;
  gap: 8px;
  padding: 7px 8px 7px 9px;
  border-radius: 8px;
  transition: background-color 120ms ease;
}

.orchestration-step:hover {
  background: color-mix(in srgb, var(--xc-color-primary, #3867d6) 5%, transparent);
}

.orchestration-step__icon {
  display: inline-flex;
  flex: 0 0 22px;
  width: 22px;
  height: 22px;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: color-mix(in srgb, var(--xc-color-primary, #3867d6) 12%, transparent);
  color: var(--xc-color-primary, #3867d6);
  font-size: 11px;
  font-weight: 700;
}

.orchestration-step--employee .orchestration-step__icon {
  background: color-mix(in srgb, #8b5cf6 14%, transparent);
  color: #7c3aed;
}

.orchestration-step--print .orchestration-step__icon {
  background: color-mix(in srgb, #0ea5e9 14%, transparent);
  color: #0284c7;
}

.orchestration-step--database_write .orchestration-step__icon {
  background: color-mix(in srgb, #16a34a 14%, transparent);
  color: #15803d;
}

.orchestration-step--failed .orchestration-step__icon {
  background: color-mix(in srgb, #dc2626 14%, transparent);
  color: #dc2626;
}

.orchestration-step__body {
  min-width: 0;
  flex: 1;
}

.orchestration-step__title-row {
  display: flex;
  align-items: baseline;
  gap: 7px;
}

.orchestration-step__title {
  color: var(--xc-color-text, #344054);
  font-size: 12px;
  line-height: 1.45;
}

.orchestration-step__status {
  flex: 0 0 auto;
  color: var(--xc-color-text-tertiary, #98a2b3);
  font-size: 10px;
}

.orchestration-step--failed .orchestration-step__status {
  color: #dc2626;
}

.orchestration-step__detail {
  overflow: hidden;
  color: var(--xc-color-text-tertiary, #98a2b3);
  font-size: 11px;
  line-height: 1.5;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
